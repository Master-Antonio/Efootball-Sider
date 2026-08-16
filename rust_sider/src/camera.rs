use pelite::pe64::{Pe, PeView};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::{Duration, SystemTime};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleA;
use windows_sys::Win32::System::Memory::{
    VirtualAlloc, VirtualProtect, MEM_COMMIT, MEM_RESERVE, PAGE_EXECUTE_READWRITE,
};

/// List of alternative AOB patterns for multi-version game compatibility
pub const CAMERA_AOB_PATTERNS: &[&str] = &[
    "F3 0F 10 B6 5C 10 00 00 F3 0F 10 BE 60 10 00 00 F3 44 0F 10 86 64 10 00 00 F3 44 0F 10 8E 68 10 00 00",
];

pub static FREECAM_ACTIVE: AtomicBool = AtomicBool::new(false);
pub static FREECAM_OFFSET_X: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Y: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Z: AtomicU32 = AtomicU32::new(0);

pub static CAMERA_TARGETS_COUNT: AtomicUsize = AtomicUsize::new(0);
pub static LAST_CAMERA_HASH: AtomicU32 = AtomicU32::new(0);

pub static CAMERA_STATE: RwLock<CameraConfig> = RwLock::new(CameraConfig {
    enabled: true,
    zoom: 0.82,
    height: 1.32,
    angle: -0.12,
    fov: 50.0,
    freecam_speed: 2.5,
});

/// Refactored CameraConfig with no duplicate fields
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

/// Compute a 32-bit hash combining the camera configuration floats using golden ratio / mixing constants
#[inline]
pub fn compute_camera_hash(cfg: &CameraConfig) -> u32 {
    compute_camera_values_hash(cfg.zoom, cfg.height, cfg.angle, cfg.fov)
}

/// Hash helper combining individual float values and freecam state
#[inline]
pub fn compute_camera_values_hash(zoom: f32, height: f32, angle: f32, fov: f32) -> u32 {
    let mut h = 0x811C9DC5u32;
    h = (h ^ zoom.to_bits()).wrapping_mul(0x9E3779B9);
    h = (h ^ height.to_bits()).wrapping_mul(0x85EBCA6B);
    h = (h ^ angle.to_bits()).wrapping_mul(0xC2B2AE3D);
    h = (h ^ fov.to_bits()).wrapping_mul(0x27D4EB2D);
    h
}

/// Helper to get current freecam position offsets as f32 values
#[inline]
pub fn get_freecam_offsets() -> (f32, f32, f32) {
    (
        f32::from_bits(FREECAM_OFFSET_X.load(Ordering::Relaxed)),
        f32::from_bits(FREECAM_OFFSET_Y.load(Ordering::Relaxed)),
        f32::from_bits(FREECAM_OFFSET_Z.load(Ordering::Relaxed)),
    )
}

/// Adjusts freecam positional offsets scaled by freecam_speed
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

    // Invalidate hash so changes take effect immediately in the detour tick
    LAST_CAMERA_HASH.store(0, Ordering::Relaxed);
}

/// Resets freecam offsets back to zero
pub fn reset_freecam() {
    FREECAM_OFFSET_X.store(0f32.to_bits(), Ordering::Relaxed);
    FREECAM_OFFSET_Y.store(0f32.to_bits(), Ordering::Relaxed);
    FREECAM_OFFSET_Z.store(0f32.to_bits(), Ordering::Relaxed);
    LAST_CAMERA_HASH.store(0, Ordering::Relaxed);
}

/// Toggles freecam mode; resets offsets when disabled
pub fn toggle_freecam() -> bool {
    let prev = FREECAM_ACTIVE.fetch_xor(true, Ordering::SeqCst);
    let new_st = !prev;
    if !new_st {
        reset_freecam();
    }
    crate::log_msg(&format!(">>> Freecam State: {}", new_st));
    new_st
}

/// Loads camera settings from sider.ini, maintaining backward compatibility with existing keys
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
            LAST_CAMERA_HASH.store(0, Ordering::Relaxed);
        }
    }
}

pub fn adjust_zoom(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.zoom = (cfg.zoom + delta).clamp(0.1, 5.0);
        cfg.fov = (cfg.fov + delta * 25.0).clamp(15.0, 120.0);
        LAST_CAMERA_HASH.store(0, Ordering::Relaxed);
        crate::log_msg(&format!(">>> Live Zoom Adjusted: {:.2} (FOV: {:.1} deg)", cfg.zoom, cfg.fov));
    }
}

pub fn adjust_height(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.height = (cfg.height + delta).clamp(0.1, 5.0);
        LAST_CAMERA_HASH.store(0, Ordering::Relaxed);
        crate::log_msg(&format!(">>> Live Height Adjusted: {:.2}", cfg.height));
    }
}

pub fn adjust_angle(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.angle = (cfg.angle + delta).clamp(-1.0, 1.0);
        LAST_CAMERA_HASH.store(0, Ordering::Relaxed);
        crate::log_msg(&format!(">>> Live Angle Adjusted: {:.2}", cfg.angle));
    }
}

/// Detour handler called from the x64 trampoline: receives PesCameraComponent pointer (RSI passed into RCX)
#[no_mangle]
pub unsafe extern "C" fn sider_camera_tick_detour(pes_camera_component_ptr: usize) {
    if pes_camera_component_ptr == 0 {
        return;
    }

    CAMERA_TARGETS_COUNT.store(1, Ordering::Relaxed);

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

        let target_zoom = cfg.zoom + off_x;
        let target_height = cfg.height + off_y;
        let target_angle = cfg.angle + off_z;
        let target_fov = cfg.fov;

        let current_hash = compute_camera_values_hash(target_zoom, target_height, target_angle, target_fov);
        let last_hash = LAST_CAMERA_HASH.load(Ordering::Relaxed);

        // Write to memory ONLY when values change to eliminate redundant writes
        if current_hash != last_hash {
            let zoom_ptr = (pes_camera_component_ptr + 0x105C) as *mut f32;
            let height_ptr = (pes_camera_component_ptr + 0x1060) as *mut f32;
            let angle_ptr = (pes_camera_component_ptr + 0x1064) as *mut f32;
            let fov_ptr = (pes_camera_component_ptr + 0x1068) as *mut f32;

            *zoom_ptr = target_zoom;
            *height_ptr = target_height;
            *angle_ptr = target_angle;
            *fov_ptr = target_fov;

            LAST_CAMERA_HASH.store(current_hash, Ordering::Relaxed);
        }
    }
}

/// Scans the .text section with multi-pattern fallback, allocates executable trampoline, and installs inline detour hook
pub fn install_pes_camera_pelite_hook() -> bool {
    unsafe {
        let h_mod = GetModuleHandleA(std::ptr::null());
        if h_mod == 0 {
            crate::log_msg("[CAMERA] ERROR: Could not get main module handle");
            return false;
        }

        let pe_view = PeView::module(h_mod as *const u8);

        let mut matched_rva = None;
        let mut matched_pattern_idx = 0;

        // Try each pattern sequentially with dynamic parsing
        for (idx, pat_str) in CAMERA_AOB_PATTERNS.iter().enumerate() {
            if let Ok(atoms) = pelite::pattern::parse(pat_str) {
                let mut save = [0u32; 4];
                if pe_view.scanner().finds_code(&atoms, &mut save) {
                    matched_rva = Some(save[0] as usize);
                    matched_pattern_idx = idx;
                    break;
                }
            }
        }

        let hook_rva = match matched_rva {
            Some(rva) => rva,
            None => {
                crate::log_msg("[CAMERA] ERROR: None of the AOB patterns matched in .text section");
                return false;
            }
        };

        let hook_addr = (h_mod as usize) + hook_rva;
        crate::log_msg(&format!(
            "[CAMERA] AOB pattern #{} matched at RVA 0x{:X} (Absolute Addr: 0x{:X})",
            matched_pattern_idx + 1,
            hook_rva,
            hook_addr
        ));

        // Allocate 256-byte executable trampoline
        let tramp = VirtualAlloc(
            std::ptr::null(),
            256,
            MEM_COMMIT | MEM_RESERVE,
            PAGE_EXECUTE_READWRITE,
        ) as *mut u8;

        if tramp.is_null() {
            crate::log_msg("[CAMERA] ERROR: VirtualAlloc failed for trampoline");
            return false;
        }

        const PATTERN_SIZE: usize = 34; // 8 + 8 + 9 + 9 bytes
        let return_addr = hook_addr + PATTERN_SIZE;
        let handler_addr = sider_camera_tick_detour as *const () as usize;

        // Build x64 shellcode: preserve registers, pass RSI to RCX, call detour handler, restore registers, execute original instructions, jump back
        let mut shellcode: Vec<u8> = vec![
            0x50,                   // push rax
            0x51,                   // push rcx
            0x52,                   // push rdx
            0x41, 0x50,             // push r8
            0x41, 0x51,             // push r9
            0x41, 0x52,             // push r10
            0x41, 0x53,             // push r11
            0x48, 0x83, 0xEC, 0x28, // sub rsp, 0x28 (shadow space + 16-byte stack alignment)
            0x48, 0x89, 0xF1,       // mov rcx, rsi (pass camera component pointer as 1st parameter)
            0x48, 0xB8,             // mov rax, <handler_addr>
        ];
        shellcode.extend_from_slice(&handler_addr.to_le_bytes());
        shellcode.extend_from_slice(&[
            0xFF, 0xD0,             // call rax
            0x48, 0x83, 0xC4, 0x28, // add rsp, 0x28
            0x41, 0x5B,             // pop r11
            0x41, 0x5A,             // pop r10
            0x41, 0x59,             // pop r9
            0x41, 0x58,             // pop r8
            0x5A,                   // pop rdx
            0x59,                   // pop rcx
            0x58,                   // pop rax
            // Original instructions (34 bytes):
            0xF3, 0x0F, 0x10, 0xB6, 0x5C, 0x10, 0x00, 0x00, // movss xmm6, [rsi+0x105C]
            0xF3, 0x0F, 0x10, 0xBE, 0x60, 0x10, 0x00, 0x00, // movss xmm7, [rsi+0x1060]
            0xF3, 0x44, 0x0F, 0x10, 0x86, 0x64, 0x10, 0x00, 0x00, // movss xmm8, [rsi+0x1064]
            0xF3, 0x44, 0x0F, 0x10, 0x8E, 0x68, 0x10, 0x00, 0x00, // movss xmm9, [rsi+0x1068]
            // 64-bit absolute jump back:
            0xFF, 0x25, 0x00, 0x00, 0x00, 0x00, // jmp qword ptr [rip+0]
        ]);
        shellcode.extend_from_slice(&return_addr.to_le_bytes());

        std::ptr::copy_nonoverlapping(shellcode.as_ptr(), tramp, shellcode.len());

        // Install 64-bit JMP hook with NOP padding
        let mut old_protect = 0u32;
        if VirtualProtect(hook_addr as _, PATTERN_SIZE, PAGE_EXECUTE_READWRITE, &mut old_protect) != 0 {
            let mut hook_patch: Vec<u8> = vec![0xFF, 0x25, 0x00, 0x00, 0x00, 0x00];
            hook_patch.extend_from_slice(&(tramp as usize).to_le_bytes());
            while hook_patch.len() < PATTERN_SIZE {
                hook_patch.push(0x90); // NOP
            }
            std::ptr::copy_nonoverlapping(hook_patch.as_ptr(), hook_addr as *mut u8, PATTERN_SIZE);

            let mut dummy = 0u32;
            VirtualProtect(hook_addr as _, PATTERN_SIZE, old_protect, &mut dummy);
            crate::log_msg("[CAMERA] Inline detour hook installed successfully");
            return true;
        }

        crate::log_msg("[CAMERA] ERROR: VirtualProtect failed during hook installation");
        false
    }
}

pub const CAMERA_MODE_UNINITIALIZED: u32 = 0;
pub const CAMERA_MODE_AOB: u32 = 1;
pub const CAMERA_MODE_FALLBACK: u32 = 2;

pub static CAMERA_MODE_STATUS: AtomicU32 = AtomicU32::new(CAMERA_MODE_UNINITIALIZED);
pub static FALLBACK_CAMERA_ADDR: AtomicUsize = AtomicUsize::new(0);

/// Returns the current active camera engine mode description
pub fn get_camera_active_mode_name() -> &'static str {
    match CAMERA_MODE_STATUS.load(Ordering::Relaxed) {
        CAMERA_MODE_AOB => "AOB",
        CAMERA_MODE_FALLBACK => "FALLBACK",
        _ => "UNINITIALIZED",
    }
}

/// Scans dynamic PAGE_READWRITE memory for candidate float pairs (fov 20.0..120.0, zoom 0.1..5.0) as fallback
pub fn scan_camera_fallback_memory() -> Option<usize> {
    unsafe {
        use windows_sys::Win32::System::Memory::{
            VirtualQuery, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_EXECUTE_READWRITE,
            PAGE_GUARD, PAGE_NOACCESS, PAGE_READWRITE,
        };
        let mut addr: usize = 0x10000;
        let mut mbi: MEMORY_BASIC_INFORMATION = std::mem::zeroed();
        let max_addr = 0x00007FFFFFF00000usize;

        while addr < max_addr {
            let res = VirtualQuery(addr as _, &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>());
            if res == 0 {
                break;
            }

            let is_rw = mbi.State == MEM_COMMIT
                && (mbi.Protect & PAGE_GUARD == 0)
                && (mbi.Protect & PAGE_NOACCESS == 0)
                && (mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE) != 0);

            if is_rw && mbi.RegionSize >= 0x2000 && mbi.RegionSize <= 64 * 1024 * 1024 {
                let base = mbi.BaseAddress as usize;
                let size = mbi.RegionSize;

                if size > 0x1070 {
                    let max_scan = size - 0x1070;
                    let mut offset = 0;
                    while offset < max_scan {
                        let comp_ptr = base + offset;
                        let z = *((comp_ptr + 0x105C) as *const f32);
                        let h = *((comp_ptr + 0x1060) as *const f32);
                        let a = *((comp_ptr + 0x1064) as *const f32);
                        let fov = *((comp_ptr + 0x1068) as *const f32);

                        // Match float-pair conditions: fov between 20 and 120, zoom between 0.1 and 5.0
                        if (0.1..=5.0).contains(&z)
                            && (0.1..=5.0).contains(&h)
                            && (-1.5..=1.5).contains(&a)
                            && (20.0..=120.0).contains(&fov)
                        {
                            crate::log_msg(&format!(
                                "[CAMERA FALLBACK] Located candidate PesCameraComponent structure at 0x{:X} (zoom={:.2}, height={:.2}, angle={:.2}, fov={:.1})",
                                comp_ptr, z, h, a, fov
                            ));
                            return Some(comp_ptr);
                        }
                        offset += 8;
                    }
                }
            }

            let next_addr = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
            if next_addr <= addr {
                break;
            }
            addr = next_addr;
        }
        None
    }
}

pub fn start_camera_hook(ini_path_opt: Option<PathBuf>) {
    thread::spawn(move || {
        crate::log_msg("=== Camera Controller Hook Engine Started ===");
        let mut last_ini_mod_time = SystemTime::UNIX_EPOCH;
        let mut hook_installed = false;

        // 1. Primary Attempt: Inline AOB Detour Hook via Pelite
        for attempt in 1..=10 {
            if install_pes_camera_pelite_hook() {
                hook_installed = true;
                CAMERA_MODE_STATUS.store(CAMERA_MODE_AOB, Ordering::SeqCst);
                crate::log_msg(&format!(
                    "🎉 [PELITE CAMERA HOOK] Successfully hooked PesCameraComponent in .text section on attempt #{}! (Active Mode: AOB)",
                    attempt
                ));
                break;
            }
            thread::sleep(Duration::from_millis(500));
        }

        // 2. Validation & Fallback Memory Scanner
        if !hook_installed {
            CAMERA_MODE_STATUS.store(CAMERA_MODE_FALLBACK, Ordering::SeqCst);
            crate::log_msg("⚠️ [PELITE CAMERA HOOK] AOB pattern does not match this game version!");
            crate::log_msg("💡 [ACTION REQUIRED] Please locate the new AOB signature with x64dbg or Cheat Engine and update CAMERA_AOB_PATTERNS.");
            crate::log_msg("🔄 [CAMERA FALLBACK] Engaging secondary float-pair live RAM scanner mode (Active Mode: FALLBACK)...");

            if let Some(candidate_addr) = scan_camera_fallback_memory() {
                FALLBACK_CAMERA_ADDR.store(candidate_addr, Ordering::Relaxed);
                crate::log_msg(&format!("✅ [CAMERA FALLBACK] Active on memory address 0x{:X}", candidate_addr));
            } else {
                crate::log_msg("⚠️ [CAMERA FALLBACK] No camera structures detected in dynamic RAM yet (will re-scan in background).");
            }
        }

        loop {
            // Apply fallback updates if AOB hook was not installed
            if !hook_installed {
                let fb_addr = FALLBACK_CAMERA_ADDR.load(Ordering::Relaxed);
                if fb_addr != 0 {
                    unsafe {
                        sider_camera_tick_detour(fb_addr);
                    }
                } else if let Some(candidate_addr) = scan_camera_fallback_memory() {
                    FALLBACK_CAMERA_ADDR.store(candidate_addr, Ordering::Relaxed);
                }
            }

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
    fn test_compute_camera_hash() {
        let cfg1 = CameraConfig::default();
        let mut cfg2 = CameraConfig::default();
        cfg2.zoom = 1.0;

        let h1 = compute_camera_hash(&cfg1);
        let h2 = compute_camera_hash(&cfg2);
        assert_ne!(h1, h2);
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

    #[test]
    fn test_pelite_dynamic_pattern_parsing() {
        for pat_str in CAMERA_AOB_PATTERNS {
            let res = pelite::pattern::parse(pat_str);
            assert!(res.is_ok(), "Failed to parse pattern: {}", pat_str);
        }
    }

    #[test]
    fn test_camera_active_mode_status() {
        CAMERA_MODE_STATUS.store(CAMERA_MODE_UNINITIALIZED, Ordering::SeqCst);
        assert_eq!(get_camera_active_mode_name(), "UNINITIALIZED");

        CAMERA_MODE_STATUS.store(CAMERA_MODE_AOB, Ordering::SeqCst);
        assert_eq!(get_camera_active_mode_name(), "AOB");

        CAMERA_MODE_STATUS.store(CAMERA_MODE_FALLBACK, Ordering::SeqCst);
        assert_eq!(get_camera_active_mode_name(), "FALLBACK");
    }
}
