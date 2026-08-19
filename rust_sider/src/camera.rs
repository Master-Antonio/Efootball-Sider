use pelite::pattern;
use pelite::pe64::{Pe, PeView};
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::{Duration, Instant, SystemTime};
use windows_sys::Win32::System::LibraryLoader::GetModuleHandleA;
use windows_sys::Win32::System::Memory::{
    VirtualAlloc, VirtualProtect, MEM_COMMIT, MEM_RESERVE, PAGE_EXECUTE_READWRITE,
};

use windows_sys::Win32::System::Diagnostics::Debug::{
    AddVectoredExceptionHandler, EXCEPTION_POINTERS,
};

/// SEH return code: continue searching for another handler
const EXCEPTION_CONTINUE_SEARCH: i32 = 0;

static VEH_INSTALLED: AtomicBool = AtomicBool::new(false);

/// SEH handler: logs any hardware exception (access violation, etc.)
/// that catch_unwind cannot see
unsafe extern "system" fn camera_veh_handler(info: *mut EXCEPTION_POINTERS) -> i32 {
    if let Some(record) = (*info).ExceptionRecord.as_ref() {
        crate::log_msg(&format!(
            "[CAMERA VEH] SEH Exception! Code: 0x{:08X} at Address: 0x{:X}",
            record.ExceptionCode,
            record.ExceptionAddress as usize
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

/// Writes directly to a sentinel file, bypassing the async logger.
/// Used to determine whether the camera thread or the logger is dead.
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

/// List of alternative AOB patterns for multi-version game compatibility
pub const CAMERA_AOB_PATTERNS: &[&str] = &[
    "F3 0F 10 B6 5C 10 00 00 F3 0F 10 BE 60 10 00 00 F3 44 0F 10 86 64 10 00 00 F3 44 0F 10 8E 68 10 00 00",
];

pub static FREECAM_ACTIVE: AtomicBool = AtomicBool::new(false);
pub static FREECAM_OFFSET_X: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Y: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Z: AtomicU32 = AtomicU32::new(0);

pub static CAMERA_TARGETS_COUNT: AtomicUsize = AtomicUsize::new(0);
pub static DETOUR_CALL_COUNT: AtomicUsize = AtomicUsize::new(0);
static NULL_PTR_LOGGED: AtomicBool = AtomicBool::new(false);
static SANITY_WARN_LOGGED: AtomicBool = AtomicBool::new(false);

/// Absolute address of the installed JMP patch (0 = not installed).
/// Re-checked periodically by the heartbeat to detect anti-cheat/integrity reverts.
static HOOK_PATCH_ADDR: AtomicUsize = AtomicUsize::new(0);
static HOOK_REVERT_LOGGED: AtomicBool = AtomicBool::new(false);

/// Re-reads the first bytes of the patched location and compares them against the
/// `FF 25` (jmp qword ptr [rip+0]) opcode we wrote during installation.
/// Returns None if no AOB hook is installed, Some(true) if intact, Some(false) if reverted.
fn check_hook_integrity() -> Option<bool> {
    let addr = HOOK_PATCH_ADDR.load(Ordering::Relaxed);
    if addr == 0 {
        return None;
    }
    unsafe {
        let bytes = std::slice::from_raw_parts(addr as *const u8, 2);
        Some(bytes == [0xFF, 0x25])
    }
}

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
}

/// Resets freecam offsets back to zero
pub fn reset_freecam() {
    FREECAM_OFFSET_X.store(0f32.to_bits(), Ordering::Relaxed);
    FREECAM_OFFSET_Y.store(0f32.to_bits(), Ordering::Relaxed);
    FREECAM_OFFSET_Z.store(0f32.to_bits(), Ordering::Relaxed);
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
        }
    }
}

pub fn adjust_zoom(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        cfg.zoom = (cfg.zoom + delta).clamp(0.1, 5.0);
        cfg.fov = (cfg.fov + delta * 25.0).clamp(15.0, 120.0);
        crate::log_msg(&format!(">>> Live Zoom Adjusted: {:.2} (FOV: {:.1} deg)", cfg.zoom, cfg.fov));
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

/// Detour handler called from the x64 trampoline: receives PesCameraComponent pointer (RSI passed into RCX)
#[no_mangle]
pub unsafe extern "C" fn sider_camera_tick_detour(pes_camera_component_ptr: usize) {
    if pes_camera_component_ptr == 0 {
        if !NULL_PTR_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg("[CAMERA DETOUR] Warning: Received null (0) camera component pointer.");
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

        let target_zoom = cfg.zoom + off_x;
        let target_height = cfg.height + off_y;
        let target_angle = cfg.angle + off_z;
        let target_fov = cfg.fov;

        let zoom_ptr = (pes_camera_component_ptr + 0x105C) as *mut f32;
        let height_ptr = (pes_camera_component_ptr + 0x1060) as *mut f32;
        let angle_ptr = (pes_camera_component_ptr + 0x1064) as *mut f32;
        let fov_ptr = (pes_camera_component_ptr + 0x1068) as *mut f32;

        let mem_zoom = *zoom_ptr;
        let mem_height = *height_ptr;
        let mem_angle = *angle_ptr;
        let mem_fov = *fov_ptr;

        let should_log = match calls {
            1 | 2 | 3 | 100 | 1000 => true,
            c if c > 1000 && c % 50000 == 0 => true,
            _ => false,
        };

        // Sentinel for the first 3 calls only (zero performance impact)
        if calls <= 3 {
            sentinella(&format!(
                "DETOUR call #{} ptr=0x{:X} mem_zoom={:.2} mem_height={:.2} mem_angle={:.2} mem_fov={:.1} target_zoom={:.2} target_fov={:.1}",
                calls, pes_camera_component_ptr, mem_zoom, mem_height, mem_angle, mem_fov, target_zoom, target_fov
            ));
        }

        if should_log {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] calls={} ptr=0x{:X} mem_zoom={:.2} mem_height={:.2} mem_angle={:.2} mem_fov={:.1} desired_zoom={:.2} desired_height={:.2} desired_angle={:.2} desired_fov={:.1}",
                calls,
                pes_camera_component_ptr,
                mem_zoom,
                mem_height,
                mem_angle,
                mem_fov,
                target_zoom,
                target_height,
                target_angle,
                target_fov
            ));
        }

        if mem_zoom.is_finite() && mem_zoom.abs() <= 100000.0 {
            if (mem_zoom - target_zoom).abs() > 0.0001 {
                *zoom_ptr = target_zoom;
            }
        } else if !SANITY_WARN_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] Warning: Invalid or non-finite memory value for zoom: {}",
                mem_zoom
            ));
        }

        if mem_height.is_finite() && mem_height.abs() <= 100000.0 {
            if (mem_height - target_height).abs() > 0.0001 {
                *height_ptr = target_height;
            }
        } else if !SANITY_WARN_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] Warning: Invalid or non-finite memory value for height: {}",
                mem_height
            ));
        }

        if mem_angle.is_finite() && mem_angle.abs() <= 100000.0 {
            if (mem_angle - target_angle).abs() > 0.0001 {
                *angle_ptr = target_angle;
            }
        } else if !SANITY_WARN_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] Warning: Invalid or non-finite memory value for angle: {}",
                mem_angle
            ));
        }

        if mem_fov.is_finite() && mem_fov.abs() <= 100000.0 {
            if (mem_fov - target_fov).abs() > 0.0001 {
                *fov_ptr = target_fov;
            }
        } else if !SANITY_WARN_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] Warning: Invalid or non-finite memory value for fov: {}",
                mem_fov
            ));
        }
    }
}

/// Scans the .text section using the compile-time pattern! macro (proven working),
/// allocates executable trampoline, and installs the inline detour
pub fn install_pes_camera_pelite_hook() -> bool {
    unsafe {
        sentinella("install: getting module handle");
        let h_mod = GetModuleHandleA(std::ptr::null());
        if h_mod == 0 {
            sentinella("install:Error module handle null");
            crate::log_msg("[CAMERA] ERROR: Could not get main module handle");
            return false;
        }
 sentinella("install:creating PeView");
        crate::log_msg("[CAMERA DIAG] Creating PeView");
        let pe_view = PeView::module(h_mod as *const u8);
        sentinella("install: PeView created OK");
        crate::log_msg("[CAMERA DIAG] PeView created successfully");

        // Use the compile-time pattern! macro (this is the exact version that matched yesterday)
                sentinella("install: calling finds_code");

        crate::log_msg("[CAMERA DIAG] Starting finds_code scan (compile-time macro)");
        let pat = pattern!("F3 0F 10 B6 5C 10 00 00 F3 0F 10 BE 60 10 00 00 F3 44 0F 10 86 64 10 00 00 F3 44 0F 10 8E 68 10 00 00");

        // Diagnostic: the pattern has no anchoring context (4 generic movss loads), so it may
        // match more than one location in .text. finds_code() only ever installs the FIRST hit,
        // which is silently wrong if that first hit is not the per-frame camera tick (e.g. a
        // constructor/reset copy of the same struct layout). Enumerate every match so we can see
        // in the log whether the pattern is ambiguous.
        let mut all_matches: Vec<u32> = Vec::new();
        {
            let mut iter = pe_view.scanner().matches_code(pat);
            let mut msave = [0u32; 4];
            while iter.next(&mut msave) {
                all_matches.push(msave[0]);
                if all_matches.len() >= 16 {
                    break;
                }
            }
        }
        crate::log_msg(&format!(
            "[CAMERA DIAG] Pattern occurs {} time(s) in .text: {:?}",
            all_matches.len(),
            all_matches.iter().map(|rva| format!("0x{:X}", rva)).collect::<Vec<_>>()
        ));
        if all_matches.len() > 1 {
            crate::log_msg("[CAMERA DIAG] WARNING: pattern is AMBIGUOUS (multiple matches). The installed hook uses the FIRST match only - if the camera never updates in a real match, this is the most likely cause and the pattern needs disambiguating context bytes.");
        }
        sentinella(&format!("install: match count={}", all_matches.len()));

        let mut save = [0u32; 4];
        let found = pe_view.scanner().finds_code(pat, &mut save);
         sentinella(&format!("install: finds_code returned {}", found));
        crate::log_msg(&format!("[CAMERA DIAG] finds_code returned: {}", found));

        if !found {
            sentinella("install: pattern NOT found, aborting");
            crate::log_msg("[CAMERA] ERROR: AOB pattern not found in .text section");
            return false;
        }

        sentinella(&format!("install: pattern FOUND at RVA 0x{:X}", save[0]));

        let hook_rva = save[0] as usize;
        let hook_addr = (h_mod as usize) + hook_rva;
        crate::log_msg(&format!(
            "[CAMERA] AOB pattern matched at RVA 0x{:X} (Absolute Addr: 0x{:X})",
            hook_rva, hook_addr
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

        const PATTERN_SIZE: usize = 34;
        let return_addr = hook_addr + PATTERN_SIZE;
        let handler_addr = sider_camera_tick_detour as *const () as usize;

        // Build x64 shellcode: preserve registers, pass RSI to RCX, call detour, restore, execute original, jump back
        let mut shellcode: Vec<u8> = vec![
            0x50,                   // push rax
            0x51,                   // push rcx
            0x52,                   // push rdx
            0x41, 0x50,             // push r8
            0x41, 0x51,             // push r9
            0x41, 0x52,             // push r10
            0x41, 0x53,             // push r11
            0x48, 0x83, 0xEC, 0x28, // sub rsp, 0x28
            0x48, 0x89, 0xF1,       // mov rcx, rsi
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

        // Install 64-bit JMP with NOP padding
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
            HOOK_PATCH_ADDR.store(hook_addr, Ordering::SeqCst);
             sentinella("install: hook INSTALLED successfully");
            crate::log_msg("[CAMERA] Inline detour installed successfully");
            return true;
        }

        crate::log_msg("[CAMERA] ERROR: VirtualProtect failed during installation");
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

               // Install VEH handler to catch SEH exceptions (access violations, etc.)
        install_camera_veh();
        sentinella("Camera thread alive, starting countdown");

        // Countdown with 1-second heartbeats so we can see exactly where it stops
        for i in (1..=5).rev() {
            crate::log_msg(&format!("[CAMERA DIAG] Waiting for game load... {}s remaining", i));
            sentinella(&format!("Countdown: {}s remaining", i));
            thread::sleep(Duration::from_secs(1));
        }

        sentinella("Delay complete, starting hook installation");
        crate::log_msg("[CAMERA DIAG] Delay complete, starting hook installation");

        let mut last_ini_mod_time = SystemTime::UNIX_EPOCH;
        let mut hook_installed = false;

        // Wrap installation in catch_unwind to capture any panic
        let install_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            for attempt in 1..=10 {
                crate::log_msg(&format!("[CAMERA DIAG] Attempt #{}", attempt));
                if install_pes_camera_pelite_hook() {
                    return true;
                }
                thread::sleep(Duration::from_millis(500));
            }
            false
        }));

        match install_result {
            Ok(installed) => {
                if installed {
                    hook_installed = true;
                    CAMERA_MODE_STATUS.store(CAMERA_MODE_AOB, Ordering::SeqCst);
                    crate::log_msg("🎉 [PELITE CAMERA HOOK] Successfully hooked PesCameraComponent (Active Mode: AOB)");
                }
            }
            Err(payload) => {
                let msg = if let Some(s) = payload.downcast_ref::<&str>() {
                    s.to_string()
                } else if let Some(s) = payload.downcast_ref::<String>() {
                    s.clone()
                } else {
                    "unknown panic".to_string()
                };
                crate::log_msg(&format!("[CAMERA PANIC] Hook installation panicked: {}", msg));
            }
        }

        if !hook_installed {
            CAMERA_MODE_STATUS.store(CAMERA_MODE_FALLBACK, Ordering::SeqCst);
            crate::log_msg("⚠️ [PELITE CAMERA HOOK] AOB pattern does not match this game version!");
            crate::log_msg("🔄 [CAMERA FALLBACK] Engaging secondary float-pair scanner (Active Mode: FALLBACK)...");

            let fb_result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
                scan_camera_fallback_memory()
            }));

            match fb_result {
                Ok(Some(addr)) => {
                    FALLBACK_CAMERA_ADDR.store(addr, Ordering::Relaxed);
                    crate::log_msg(&format!("✅ [CAMERA FALLBACK] Active on 0x{:X}", addr));
                }
                Ok(None) => {
                    crate::log_msg("⚠️ [CAMERA FALLBACK] No camera structures detected yet.");
                }
                Err(payload) => {
                    let msg = if let Some(s) = payload.downcast_ref::<&str>() {
                        s.to_string()
                    } else if let Some(s) = payload.downcast_ref::<String>() {
                        s.clone()
                    } else {
                        "unknown panic".to_string()
                    };
                    crate::log_msg(&format!("[CAMERA PANIC] Fallback scan panicked: {}", msg));
                }
            }
        }

        let mut last_heartbeat = Instant::now();
        let mut last_heartbeat_calls = 0usize;

        loop {
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

            // Heartbeat every ~3s: makes it possible to tell "detour never fires" apart from
            // "logger died", and catches an anti-cheat/integrity revert of the JMP patch.
            if last_heartbeat.elapsed() >= Duration::from_secs(3) {
                let calls = DETOUR_CALL_COUNT.load(Ordering::Relaxed);
                let delta = calls.saturating_sub(last_heartbeat_calls);
                last_heartbeat_calls = calls;
                last_heartbeat = Instant::now();

                match check_hook_integrity() {
                    Some(true) => {
                        crate::log_msg(&format!(
                            "[CAMERA HEARTBEAT] mode={} total_calls={} calls_last_3s={} hook_bytes=intact",
                            get_camera_active_mode_name(), calls, delta
                        ));
                    }
                    Some(false) => {
                        if !HOOK_REVERT_LOGGED.swap(true, Ordering::Relaxed) {
                            crate::log_msg("[CAMERA HEARTBEAT] ⚠️ WARNING: patched JMP bytes at hook address no longer match what we wrote - the patch was REVERTED (likely by anti-cheat/integrity check). This explains why the detour stops firing after install.");
                        }
                        crate::log_msg(&format!(
                            "[CAMERA HEARTBEAT] mode={} total_calls={} calls_last_3s={} hook_bytes=REVERTED",
                            get_camera_active_mode_name(), calls, delta
                        ));
                    }
                    None => {
                        crate::log_msg(&format!(
                            "[CAMERA HEARTBEAT] mode={} total_calls={} calls_last_3s={}",
                            get_camera_active_mode_name(), calls, delta
                        ));
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
        let mut mock_buffer = [0u8; 0x1070 + 16];
        let ptr = mock_buffer.as_mut_ptr() as usize;

        unsafe {
            let z_ptr = (ptr + 0x105C) as *mut f32;
            let h_ptr = (ptr + 0x1060) as *mut f32;
            let a_ptr = (ptr + 0x1064) as *mut f32;
            let fov_ptr = (ptr + 0x1068) as *mut f32;

            *z_ptr = 1.0;
            *h_ptr = 1.0;
            *a_ptr = 0.0;
            *fov_ptr = 55.0;

            sider_camera_tick_detour(ptr);

            assert!((*z_ptr - 0.82).abs() < 0.001);
            assert!((*h_ptr - 1.32).abs() < 0.001);
            assert!((*a_ptr - (-0.12)).abs() < 0.001);
            assert!((*fov_ptr - 50.0).abs() < 0.001);
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
