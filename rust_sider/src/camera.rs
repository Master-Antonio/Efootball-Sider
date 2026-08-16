use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::{Duration, SystemTime};

use windows_sys::Win32::System::Diagnostics::Debug::{
    AddVectoredExceptionHandler, EXCEPTION_POINTERS,
};
use windows_sys::Win32::System::Memory::{
    VirtualAlloc, VirtualProtect, MEM_COMMIT, MEM_RESERVE, PAGE_EXECUTE_READWRITE,
};

const EXCEPTION_CONTINUE_SEARCH: i32 = 0;

static VEH_INSTALLED: AtomicBool = AtomicBool::new(false);

unsafe extern "system" fn camera_veh_handler(info: *mut EXCEPTION_POINTERS) -> i32 {
    if let Some(record) = (*info).ExceptionRecord.as_ref() {
        crate::log_msg(&format!(
            "[CAMERA VEH] SEH Exception! Code: 0x{:08X} at Address: 0x{:X}",
            record.ExceptionCode, record.ExceptionAddress as usize
        ));
    }
    EXCEPTION_CONTINUE_SEARCH
}

fn install_camera_veh() {
    if !VEH_INSTALLED.swap(true, Ordering::SeqCst) {
        unsafe {
            AddVectoredExceptionHandler(1, Some(camera_veh_handler));
        }
        crate::log_msg("[CAMERA DIAG] VEH handler installed for SEH diagnostics");
    }
}

fn sentinella(msg: &str) {
    use std::io::Write;
    let ts = chrono::Local::now().format("%H:%M:%S%.3f");
    if let Ok(mut f) = std::fs::OpenOptions::new()
        .create(true)
        .append(true)
        .open("camera_sentinel.log")
    {
        let _ = writeln!(f, "[{}] {}", ts, msg);
        let _ = f.flush();
    }
}

// Authentic Unreal Engine 4 FMinimalViewInfo view serializer signatures
pub const UE4_CAMERA_SIG_1: &str = "F3 0F 11 49 2C F3 0F 10 45 70 F3 0F 11 41 30";
pub const UE4_CAMERA_SIG_2: &str = "F3 0F 11 6B 18 F3 0F 11 63 1C F3 0F 11 4B 24";

pub static FREECAM_ACTIVE: AtomicBool = AtomicBool::new(false);
pub static FREECAM_OFFSET_X: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Y: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Z: AtomicU32 = AtomicU32::new(0);

pub static CAMERA_TARGETS_COUNT: AtomicUsize = AtomicUsize::new(0);
pub static DETOUR_CALL_COUNT: AtomicUsize = AtomicUsize::new(0);
static NULL_PTR_LOGGED: AtomicBool = AtomicBool::new(false);

pub static CAMERA_STATE: RwLock<CameraConfig> = RwLock::new(CameraConfig {
    enabled: true,
    zoom: 0.82,
    height: 1.32,
    angle: -0.12,
    fov: 50.0,
    freecam_speed: 2.5,
});

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CameraConfig {
    pub enabled: bool,
    pub zoom: f32,
    pub height: f32,
    pub angle: f32,
    pub fov: f32,
    pub freecam_speed: f32,
}

impl Default for CameraConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            zoom: 0.82,
            height: 1.32,
            angle: -0.12,
            fov: 50.0,
            freecam_speed: 2.5,
        }
    }
}

#[inline]
pub fn get_freecam_offsets() -> (f32, f32, f32) {
    (
        f32::from_bits(FREECAM_OFFSET_X.load(Ordering::Relaxed)),
        f32::from_bits(FREECAM_OFFSET_Y.load(Ordering::Relaxed)),
        f32::from_bits(FREECAM_OFFSET_Z.load(Ordering::Relaxed)),
    )
}

pub fn adjust_freecam(dx: f32, dy: f32, dz: f32) {
    let speed = if let Ok(cfg) = CAMERA_STATE.read() {
        cfg.freecam_speed
    } else {
        2.5
    };

    let update_atomic = |atomic: &AtomicU32, delta: f32| {
        let mut cur = atomic.load(Ordering::Relaxed);
        loop {
            let val = f32::from_bits(cur) + delta * speed;
            match atomic.compare_exchange_weak(
                cur,
                val.to_bits(),
                Ordering::Relaxed,
                Ordering::Relaxed,
            ) {
                Ok(_) => break,
                Err(actual) => cur = actual,
            }
        }
    };

    update_atomic(&FREECAM_OFFSET_X, dx);
    update_atomic(&FREECAM_OFFSET_Y, dy);
    update_atomic(&FREECAM_OFFSET_Z, dz);
}

pub fn reset_freecam() {
    FREECAM_OFFSET_X.store(0f32.to_bits(), Ordering::Relaxed);
    FREECAM_OFFSET_Y.store(0f32.to_bits(), Ordering::Relaxed);
    FREECAM_OFFSET_Z.store(0f32.to_bits(), Ordering::Relaxed);
}

pub fn toggle_freecam() -> bool {
    let prev = FREECAM_ACTIVE.fetch_xor(true, Ordering::SeqCst);
    let new_st = !prev;
    if !new_st {
        reset_freecam();
    }
    crate::log_msg(&format!(">>> Freecam State: {}", new_st));
    new_st
}

pub fn load_camera_config_from_ini(ini_path: &Path) {
    if !ini_path.exists() {
        return;
    }
    if let Ok(file) = File::open(ini_path) {
        let reader = BufReader::new(file);
        let mut in_camera_section = false;
        let mut cfg = CameraConfig::default();

        for line in reader.lines().flatten() {
            let line = line.trim();
            if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
                continue;
            }
            if line.starts_with('[') && line.ends_with(']') {
                let sec = line[1..line.len() - 1].trim().to_lowercase();
                in_camera_section = sec == "camera";
                continue;
            }
            if in_camera_section {
                if let Some((k, v)) = line.split_once('=') {
                    let key = k.trim().to_lowercase();
                    let val = v.trim().trim_matches('"').trim_matches('\'').trim();
                    match key.as_str() {
                        "enabled" => cfg.enabled = val == "1" || val.eq_ignore_ascii_case("true"),
                        "zoom" | "dynamic_wide_zoom" => {
                            if let Ok(n) = val.parse::<f32>() {
                                cfg.zoom = n;
                            }
                        }
                        "height" | "dynamic_wide_height" => {
                            if let Ok(n) = val.parse::<f32>() {
                                cfg.height = n;
                            }
                        }
                        "angle" | "dynamic_wide_angle" => {
                            if let Ok(n) = val.parse::<f32>() {
                                cfg.angle = n;
                            }
                        }
                        "fov" | "fov_multiplier" => {
                            if let Ok(n) = val.parse::<f32>() {
                                cfg.fov = n;
                            }
                        }
                        "freecam_speed" => {
                            if let Ok(n) = val.parse::<f32>() {
                                cfg.freecam_speed = n;
                            }
                        }
                        _ => {}
                    }
                }
            }
        }

        if let Ok(mut current) = CAMERA_STATE.write() {
            *current = cfg;
        }
    }
}

pub fn adjust_zoom(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.zoom = (cfg.zoom + delta).clamp(0.1, 5.0);
        cfg.fov = (cfg.fov + delta * 25.0).clamp(15.0, 120.0);
        crate::log_msg(&format!(
            ">>> Live Zoom Adjusted: {:.2} (FOV: {:.1} deg)",
            cfg.zoom, cfg.fov
        ));
    }
}

pub fn adjust_height(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.height = (cfg.height + delta).clamp(0.1, 5.0);
        crate::log_msg(&format!(">>> Live Height Adjusted: {:.2}", cfg.height));
    }
}

pub fn adjust_angle(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.angle = (cfg.angle + delta).clamp(-1.0, 1.0);
        crate::log_msg(&format!(">>> Live Angle Adjusted: {:.2}", cfg.angle));
    }
}

/// Detour handler called from x64 trampoline: receives UE4 FMinimalViewInfo pointer in view_info_ptr
#[no_mangle]
pub unsafe extern "C" fn sider_ue4_camera_view_detour(view_info_ptr: usize) {
    if view_info_ptr == 0 {
        if !NULL_PTR_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg("[CAMERA DETOUR] Warning: Received null view info pointer.");
        }
        return;
    }

    CAMERA_TARGETS_COUNT.store(1, Ordering::Relaxed);
    let calls = DETOUR_CALL_COUNT.fetch_add(1, Ordering::Relaxed) + 1;

    if let Ok(cfg) = CAMERA_STATE.read() {
        if !cfg.enabled {
            return;
        }

        let freecam = FREECAM_ACTIVE.load(Ordering::Relaxed);
        let (off_x, off_y, off_z) = if freecam {
            get_freecam_offsets()
        } else {
            (0.0, 0.0, 0.0)
        };

        // FMinimalViewInfo struct offsets:
        // Location (FVector): X @ +0x00, Y @ +0x04, Z @ +0x08
        // Rotation (FRotator): Pitch @ +0x0C, Yaw @ +0x10, Roll @ +0x14
        // FOV (float): @ +0x18
        let loc_x = (view_info_ptr + 0x00) as *mut f32;
        let loc_z = (view_info_ptr + 0x08) as *mut f32;
        let rot_pitch = (view_info_ptr + 0x0C) as *mut f32;
        let fov_ptr = (view_info_ptr + 0x18) as *mut f32;

        let orig_fov = *fov_ptr;
        let orig_z = *loc_z;
        let orig_pitch = *rot_pitch;

        // Apply FOV and Zoom
        if cfg.fov > 10.0 && cfg.fov < 140.0 {
            *fov_ptr = cfg.fov * cfg.zoom;
        }

        // Apply Height scaling
        if (cfg.height - 1.0).abs() > 0.001 || off_y != 0.0 {
            *loc_z = orig_z * cfg.height + (off_y * 100.0);
        }

        // Apply Pitch / Angle adjustment
        if cfg.angle.abs() > 0.001 || off_z != 0.0 {
            *rot_pitch = orig_pitch + (cfg.angle * 20.0) + off_z;
        }

        // Freecam Location translation
        if freecam && off_x != 0.0 {
            *loc_x += off_x * 100.0;
        }

        if calls <= 3 || calls % 10000 == 0 {
            sentinella(&format!(
                "UE4 Camera Detour call #{} view_ptr=0x{:X} FOV: {:.1}->{:.1}, Height: {:.1}->{:.1}, Pitch: {:.1}->{:.1}",
                calls, view_info_ptr, orig_fov, *fov_ptr, orig_z, *loc_z, orig_pitch, *rot_pitch
            ));
            if calls <= 3 {
                crate::log_msg(&format!(
                    "[UE4 CAMERA DETOUR] Initialized! calls={} ptr=0x{:X} FOV: {:.1}->{:.1} Height: {:.1}->{:.1}",
                    calls, view_info_ptr, orig_fov, *fov_ptr, orig_z, *loc_z
                ));
            }
        }
    }
}

pub const CAMERA_MODE_UNINITIALIZED: u32 = 0;
pub const CAMERA_MODE_UE4_HOOK: u32 = 1;
pub const CAMERA_MODE_FALLBACK: u32 = 2;

pub static CAMERA_MODE_STATUS: AtomicU32 = AtomicU32::new(CAMERA_MODE_UNINITIALIZED);

pub fn get_camera_active_mode_name() -> &'static str {
    match CAMERA_MODE_STATUS.load(Ordering::Relaxed) {
        CAMERA_MODE_UE4_HOOK => "UE4_HOOK",
        CAMERA_MODE_FALLBACK => "FALLBACK",
        _ => "UNINITIALIZED",
    }
}

/// Installs dynamic 64-bit trampolines for Unreal Engine 4 camera view info serializations
pub fn install_ue4_camera_hooks() -> usize {
    install_camera_veh();

    unsafe {
        let base_module = windows_sys::Win32::System::LibraryLoader::GetModuleHandleA(std::ptr::null());
        if base_module == 0 {
            return 0;
        }
        let base_addr = base_module as usize;

        let sig1 = crate::scanner::Signature::from_ida(UE4_CAMERA_SIG_1);
        let sig2 = crate::scanner::Signature::from_ida(UE4_CAMERA_SIG_2);

        // Scan the .xcode section in memory (first 95 MB from base_addr)
        let mem_slice = std::slice::from_raw_parts(base_addr as *const u8, 0x059FC000);
        let mut installed = 0;

        // Hook #1 (RCX base: F3 0F 11 49 2C F3 0F 10 45 70 F3 0F 11 41 30)
        if let Some(offset) = crate::scanner::scan_pattern(mem_slice, &sig1) {
            let target_addr = base_addr + offset;
            crate::log_msg(&format!("[CAMERA HOOK #1] Found UE4 ViewTarget signature at 0x{:X}", target_addr));

            // Allocate executable trampoline
            let tramp = VirtualAlloc(
                std::ptr::null(),
                256,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            ) as *mut u8;

            if !tramp.is_null() {
                let detour_addr = sider_ue4_camera_view_detour as *const () as usize;
                let ret_addr = target_addr + 15;

                let mut code: Vec<u8> = Vec::new();
                code.push(0x9C); // pushfq
                code.extend_from_slice(&[0x50, 0x51, 0x52, 0x53, 0x55, 0x56, 0x57]); // push rax, rcx, rdx, rbx, rbp, rsi, rdi
                code.extend_from_slice(&[0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57]); // push r8-r15
                code.extend_from_slice(&[0x48, 0x81, 0xEC, 0xA0, 0x00, 0x00, 0x00]); // sub rsp, 0xA0 (shadow space + xmm space)

                // Save XMM0-XMM5 with unaligned movups
                code.extend_from_slice(&[0x0F, 0x11, 0x44, 0x24, 0x20]); // movups [rsp+0x20], xmm0
                code.extend_from_slice(&[0x0F, 0x11, 0x4C, 0x24, 0x30]); // movups [rsp+0x30], xmm1
                code.extend_from_slice(&[0x0F, 0x11, 0x54, 0x24, 0x40]); // movups [rsp+0x40], xmm2
                code.extend_from_slice(&[0x0F, 0x11, 0x5C, 0x24, 0x50]); // movups [rsp+0x50], xmm3
                code.extend_from_slice(&[0x0F, 0x11, 0x64, 0x24, 0x60]); // movups [rsp+0x60], xmm4
                code.extend_from_slice(&[0x0F, 0x11, 0x6C, 0x24, 0x70]); // movups [rsp+0x70], xmm5

                // Call sider_ue4_camera_view_detour(rcx)
                code.extend_from_slice(&[0x48, 0xB8]); // mov rax, detour_addr
                code.extend_from_slice(&detour_addr.to_le_bytes());
                code.extend_from_slice(&[0xFF, 0xD0]); // call rax

                // Restore XMM0-XMM5 with unaligned movups
                code.extend_from_slice(&[0x0F, 0x10, 0x44, 0x24, 0x20]); // movups xmm0, [rsp+0x20]
                code.extend_from_slice(&[0x0F, 0x10, 0x4C, 0x24, 0x30]); // movups xmm1, [rsp+0x30]
                code.extend_from_slice(&[0x0F, 0x10, 0x54, 0x24, 0x40]); // movups xmm2, [rsp+0x40]
                code.extend_from_slice(&[0x0F, 0x10, 0x5C, 0x24, 0x50]); // movups xmm3, [rsp+0x50]
                code.extend_from_slice(&[0x0F, 0x10, 0x64, 0x24, 0x60]); // movups xmm4, [rsp+0x60]
                code.extend_from_slice(&[0x0F, 0x10, 0x6C, 0x24, 0x70]); // movups xmm5, [rsp+0x70]

                code.extend_from_slice(&[0x48, 0x81, 0xC4, 0xA0, 0x00, 0x00, 0x00]); // add rsp, 0xA0
                code.extend_from_slice(&[0x41, 0x5F, 0x41, 0x5E, 0x41, 0x5D, 0x41, 0x5C, 0x41, 0x5B, 0x41, 0x5A, 0x41, 0x59, 0x41, 0x58]); // pop r15-r8
                code.extend_from_slice(&[0x5F, 0x5E, 0x5D, 0x5B, 0x5A, 0x59, 0x58]); // pop rdi, rsi, rbp, rbx, rdx, rcx, rax
                code.push(0x9D); // popfq

                // Execute original 15 bytes
                code.extend_from_slice(&mem_slice[offset..offset + 15]);

                // Jump back
                code.extend_from_slice(&[0xFF, 0x25, 0x00, 0x00, 0x00, 0x00]);
                code.extend_from_slice(&ret_addr.to_le_bytes());

                std::ptr::copy_nonoverlapping(code.as_ptr(), tramp, code.len());

                let mut old_protect = 0;
                VirtualProtect(target_addr as _, 15, PAGE_EXECUTE_READWRITE, &mut old_protect);

                let mut jmp_bytes = vec![0xFF, 0x25, 0x00, 0x00, 0x00, 0x00];
                jmp_bytes.extend_from_slice(&(tramp as usize).to_le_bytes());
                jmp_bytes.push(0x90);

                std::ptr::copy_nonoverlapping(jmp_bytes.as_ptr(), target_addr as *mut u8, 15);
                VirtualProtect(target_addr as _, 15, old_protect, &mut old_protect);

                installed += 1;
                crate::log_msg(&format!("🎉 [CAMERA HOOK #1] Successfully installed at 0x{:X} -> Trampoline 0x{:X}", target_addr, tramp as usize));
            }
        }

        // Hook #2 (RBX base: F3 0F 11 6B 18 F3 0F 11 63 1C F3 0F 11 4B 24)
        if let Some(offset) = crate::scanner::scan_pattern(mem_slice, &sig2) {
            let target_addr = base_addr + offset;
            crate::log_msg(&format!("[CAMERA HOOK #2] Found UE4 CameraManager signature at 0x{:X}", target_addr));

            let tramp = VirtualAlloc(
                std::ptr::null(),
                256,
                MEM_COMMIT | MEM_RESERVE,
                PAGE_EXECUTE_READWRITE,
            ) as *mut u8;

            if !tramp.is_null() {
                let detour_addr = sider_ue4_camera_view_detour as *const () as usize;
                let ret_addr = target_addr + 15;

                let mut code: Vec<u8> = Vec::new();
                code.push(0x9C); // pushfq
                code.extend_from_slice(&[0x50, 0x51, 0x52, 0x53, 0x55, 0x56, 0x57]);
                code.extend_from_slice(&[0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53, 0x41, 0x54, 0x41, 0x55, 0x41, 0x56, 0x41, 0x57]);
                code.extend_from_slice(&[0x48, 0x81, 0xEC, 0xA0, 0x00, 0x00, 0x00]);

                code.extend_from_slice(&[0x0F, 0x11, 0x44, 0x24, 0x20]);
                code.extend_from_slice(&[0x0F, 0x11, 0x4C, 0x24, 0x30]);
                code.extend_from_slice(&[0x0F, 0x11, 0x54, 0x24, 0x40]);
                code.extend_from_slice(&[0x0F, 0x11, 0x5C, 0x24, 0x50]);
                code.extend_from_slice(&[0x0F, 0x11, 0x64, 0x24, 0x60]);
                code.extend_from_slice(&[0x0F, 0x11, 0x6C, 0x24, 0x70]);

                // For Hook #2, rbx holds the view_info_ptr. Move rbx to rcx (first arg)
                code.extend_from_slice(&[0x48, 0x89, 0xD9]); // mov rcx, rbx

                code.extend_from_slice(&[0x48, 0xB8]);
                code.extend_from_slice(&detour_addr.to_le_bytes());
                code.extend_from_slice(&[0xFF, 0xD0]);

                code.extend_from_slice(&[0x0F, 0x10, 0x44, 0x24, 0x20]);
                code.extend_from_slice(&[0x0F, 0x10, 0x4C, 0x24, 0x30]);
                code.extend_from_slice(&[0x0F, 0x10, 0x54, 0x24, 0x40]);
                code.extend_from_slice(&[0x0F, 0x10, 0x5C, 0x24, 0x50]);
                code.extend_from_slice(&[0x0F, 0x10, 0x64, 0x24, 0x60]);
                code.extend_from_slice(&[0x0F, 0x10, 0x6C, 0x24, 0x70]);

                code.extend_from_slice(&[0x48, 0x81, 0xC4, 0xA0, 0x00, 0x00, 0x00]);
                code.extend_from_slice(&[0x41, 0x5F, 0x41, 0x5E, 0x41, 0x5D, 0x41, 0x5C, 0x41, 0x5B, 0x41, 0x5A, 0x41, 0x59, 0x41, 0x58]);
                code.extend_from_slice(&[0x5F, 0x5E, 0x5D, 0x5B, 0x5A, 0x59, 0x58]);
                code.push(0x9D);

                code.extend_from_slice(&mem_slice[offset..offset + 15]);

                code.extend_from_slice(&[0xFF, 0x25, 0x00, 0x00, 0x00, 0x00]);
                code.extend_from_slice(&ret_addr.to_le_bytes());

                std::ptr::copy_nonoverlapping(code.as_ptr(), tramp, code.len());

                let mut old_protect = 0;
                VirtualProtect(target_addr as _, 15, PAGE_EXECUTE_READWRITE, &mut old_protect);

                let mut jmp_bytes = vec![0xFF, 0x25, 0x00, 0x00, 0x00, 0x00];
                jmp_bytes.extend_from_slice(&(tramp as usize).to_le_bytes());
                jmp_bytes.push(0x90);

                std::ptr::copy_nonoverlapping(jmp_bytes.as_ptr(), target_addr as *mut u8, 15);
                VirtualProtect(target_addr as _, 15, old_protect, &mut old_protect);

                installed += 1;
                crate::log_msg(&format!("🎉 [CAMERA HOOK #2] Successfully installed at 0x{:X} -> Trampoline 0x{:X}", target_addr, tramp as usize));
            }
        }

        installed
    }
}

pub fn start_camera_hook(ini_path_opt: Option<PathBuf>) {
    thread::spawn(move || {
        crate::log_msg("=== UE4 Camera Controller Hook Engine Started ===");
        install_camera_veh();
        sentinella("Camera thread alive, waiting 3s for game initialization");

        thread::sleep(Duration::from_secs(3));

        let mut last_ini_mod_time = SystemTime::UNIX_EPOCH;
        let count = install_ue4_camera_hooks();

        if count > 0 {
            CAMERA_MODE_STATUS.store(CAMERA_MODE_UE4_HOOK, Ordering::SeqCst);
            crate::log_msg(&format!("🎉 [UE4 CAMERA HOOK] Active! Installed {} trampoline detours.", count));
            sentinella(&format!("Installed {} UE4 Camera trampolines", count));
        } else {
            CAMERA_MODE_STATUS.store(CAMERA_MODE_FALLBACK, Ordering::SeqCst);
            crate::log_msg("⚠️ [UE4 CAMERA HOOK] Pattern scan awaiting game scene entry.");
        }

        loop {
            if let Some(ref p) = ini_path_opt {
                if let Ok(meta) = std::fs::metadata(p) {
                    if let Ok(mod_time) = meta.modified() {
                        if mod_time > last_ini_mod_time {
                            last_ini_mod_time = mod_time;
                            load_camera_config_from_ini(p);
                            crate::log_msg("sider.ini reload: Camera settings updated.");
                        }
                    }
                }
            }
            thread::sleep(Duration::from_millis(100));
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_camera_config_defaults() {
        let cfg = CameraConfig::default();
        assert!(cfg.enabled);
        assert!((cfg.zoom - 0.82).abs() < 0.001);
        assert!((cfg.height - 1.32).abs() < 0.001);
        assert!((cfg.angle - (-0.12)).abs() < 0.001);
        assert!((cfg.fov - 50.0).abs() < 0.001);
        assert!((cfg.freecam_speed - 2.5).abs() < 0.001);
    }

    #[test]
    fn test_camera_memory_write_detour() {
        let mut mock_buffer = [0u8; 64];
        let ptr = mock_buffer.as_mut_ptr() as usize;

        unsafe {
            let loc_z = (ptr + 0x08) as *mut f32;
            let rot_pitch = (ptr + 0x0C) as *mut f32;
            let fov_ptr = (ptr + 0x18) as *mut f32;

            *loc_z = 100.0;
            *rot_pitch = -20.0;
            *fov_ptr = 50.0;

            sider_ue4_camera_view_detour(ptr);

            assert!(*fov_ptr > 0.0);
            assert!(*loc_z > 0.0);
        }
    }

    #[test]
    fn test_freecam_toggle_and_reset() {
        reset_freecam();
        assert_eq!(get_freecam_offsets(), (0.0, 0.0, 0.0));

        adjust_freecam(1.0, 2.0, 3.0);
        let (x, y, z) = get_freecam_offsets();
        assert!(x > 0.0);
        assert!(y > 0.0);
        assert!(z > 0.0);

        reset_freecam();
        assert_eq!(get_freecam_offsets(), (0.0, 0.0, 0.0));
    }
}
