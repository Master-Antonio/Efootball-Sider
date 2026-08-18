#![allow(dead_code)]

mod camera;
pub mod crypto;
mod livecpk;
pub mod logger;
mod overlay;
mod scanner;
mod server;
mod teams;

use std::ffi::c_void;
use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Once, OnceLock};
use std::thread;
use std::time::Duration;
use windows_sys::Win32::Foundation::{BOOL, HMODULE, TRUE};
use windows_sys::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryA};

const SIDER_VERSION: &str = "v1.1";

/// Main Sider log function: forwards to the async logger module
pub fn log_msg(msg: &str) {
    logger::log_async(msg);
}

static REAL_DXGI: OnceLock<HMODULE> = OnceLock::new();
static SIDER_INITIALIZED: Once = Once::new();
static FIRST_FORWARD_LOGGED: AtomicBool = AtomicBool::new(false);
static SIDER_MODULE: OnceLock<HMODULE> = OnceLock::new();

fn get_real_dxgi() -> HMODULE {
    *REAL_DXGI.get_or_init(|| {
        let sys_path = b"C:\\Windows\\System32\\dxgi.dll\0";
        let h = unsafe { LoadLibraryA(sys_path.as_ptr()) };
        log_msg(&format!("Loaded System32 dxgi.dll: handle = {:?}", h));
        h
    })
}

fn get_proc_cached(slot: &'static OnceLock<usize>, proc_name: &[u8]) -> usize {
    *slot.get_or_init(|| {
        let h = get_real_dxgi();
        let p = unsafe { GetProcAddress(h, proc_name.as_ptr()) };
        p.map(|f| f as usize).unwrap_or(0)
    })
}

unsafe fn forward_cached_call(
    slot: &'static OnceLock<usize>,
    proc_name: &[u8],
    a: *mut c_void,
    b: *mut c_void,
    c: *mut c_void,
    d: *mut c_void,
) -> u32 {
    ensure_sider_initialized();
    if !FIRST_FORWARD_LOGGED.swap(true, Ordering::Relaxed) {
        let name = std::str::from_utf8(proc_name)
            .unwrap_or("unknown")
            .trim_matches('\0');
        log_msg(&format!("[DXGI FORWARD] First exported function called by game: {}", name));
    }
    let addr = get_proc_cached(slot, proc_name);
    if addr != 0 {
        let func: unsafe extern "system" fn(*mut c_void, *mut c_void, *mut c_void, *mut c_void) -> u32 =
            std::mem::transmute(addr);
        func(a, b, c, d)
    } else {
        0x80004005
    }
}

static FN_CREATE_FACTORY: OnceLock<usize> = OnceLock::new();
static FN_CREATE_FACTORY1: OnceLock<usize> = OnceLock::new();
static FN_CREATE_FACTORY2: OnceLock<usize> = OnceLock::new();
static FN_D3D10_CREATE_DEV: OnceLock<usize> = OnceLock::new();
static FN_D3D10_CREATE_LAYERED: OnceLock<usize> = OnceLock::new();
static FN_D3D10_GET_LAYERED_SZ: OnceLock<usize> = OnceLock::new();
static FN_D3D10_REG_LAYERS: OnceLock<usize> = OnceLock::new();
static FN_GET_DEBUG_INTF1: OnceLock<usize> = OnceLock::new();
static FN_REPORT_ADAPTER_CFG: OnceLock<usize> = OnceLock::new();

#[no_mangle]
pub unsafe extern "system" fn CreateDXGIFactory(a: *mut c_void, b: *mut c_void) -> u32 {
    forward_cached_call(&FN_CREATE_FACTORY, b"CreateDXGIFactory\0", a, b, std::ptr::null_mut(), std::ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "system" fn CreateDXGIFactory1(a: *mut c_void, b: *mut c_void) -> u32 {
    forward_cached_call(&FN_CREATE_FACTORY1, b"CreateDXGIFactory1\0", a, b, std::ptr::null_mut(), std::ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "system" fn CreateDXGIFactory2(a: *mut c_void, b: *mut c_void, c: *mut c_void) -> u32 {
    forward_cached_call(&FN_CREATE_FACTORY2, b"CreateDXGIFactory2\0", a, b, c, std::ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "system" fn DXGID3D10CreateDevice(a: *mut c_void, b: *mut c_void, c: *mut c_void, d: *mut c_void) -> u32 {
    forward_cached_call(&FN_D3D10_CREATE_DEV, b"DXGID3D10CreateDevice\0", a, b, c, d)
}

#[no_mangle]
pub unsafe extern "system" fn DXGID3D10CreateLayeredDevice(a: *mut c_void, b: *mut c_void, c: *mut c_void, d: *mut c_void) -> u32 {
    forward_cached_call(&FN_D3D10_CREATE_LAYERED, b"DXGID3D10CreateLayeredDevice\0", a, b, c, d)
}

#[no_mangle]
pub unsafe extern "system" fn DXGID3D10GetLayeredDeviceSize(a: *mut c_void, b: *mut c_void) -> u32 {
    forward_cached_call(&FN_D3D10_GET_LAYERED_SZ, b"DXGID3D10GetLayeredDeviceSize\0", a, b, std::ptr::null_mut(), std::ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "system" fn DXGID3D10RegisterLayers(a: *mut c_void, b: *mut c_void) -> u32 {
    forward_cached_call(&FN_D3D10_REG_LAYERS, b"DXGID3D10RegisterLayers\0", a, b, std::ptr::null_mut(), std::ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "system" fn DXGIGetDebugInterface1(a: *mut c_void, b: *mut c_void, c: *mut c_void) -> u32 {
    forward_cached_call(&FN_GET_DEBUG_INTF1, b"DXGIGetDebugInterface1\0", a, b, c, std::ptr::null_mut())
}

#[no_mangle]
pub unsafe extern "system" fn DXGIReportAdapterConfiguration(a: *mut c_void) -> u32 {
    forward_cached_call(&FN_REPORT_ADAPTER_CFG, b"DXGIReportAdapterConfiguration\0", a, std::ptr::null_mut(), std::ptr::null_mut(), std::ptr::null_mut())
}

fn ensure_sider_initialized() {
    SIDER_INITIALIZED.call_once(|| {
        thread::spawn(worker_loop);
    });
}

/// Returns the directory that contains the Sider dxgi.dll itself.
/// This is independent from the process working directory, which can change
/// depending on how the game is launched (Steam, batch file, direct exe).
fn get_module_dir() -> Option<PathBuf> {
    let h = SIDER_MODULE.get().copied()?;
    let mut buffer = [0u16; 1024];
    let len = unsafe {
        windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW(
            h,
            buffer.as_mut_ptr(),
            buffer.len() as u32,
        )
    };
    if len == 0 {
        return None;
    }
    let s = String::from_utf16_lossy(&buffer[..len as usize]);
    PathBuf::from(s).parent().map(|d| d.to_path_buf())
}

/// Locates sider.ini. Priority order:
/// 1. Next to the Sider DLL (most reliable, independent from CWD)
/// 2. Parent of the DLL directory
/// 3. Legacy CWD-relative candidates
fn find_sider_ini() -> Option<PathBuf> {
    let mut candidates: Vec<PathBuf> = Vec::new();

    if let Some(dir) = get_module_dir() {
        log_msg(&format!("[INI] Sider DLL directory: {:?}", dir));
        candidates.push(dir.join("sider.ini"));
        if let Some(parent) = dir.parent() {
            candidates.push(parent.join("sider.ini"));
        }
    }

    candidates.push(PathBuf::from("sider.ini"));
    candidates.push(PathBuf::from("../sider.ini"));
    candidates.push(PathBuf::from("../../sider.ini"));

    for c in &candidates {
        if c.exists() {
            log_msg(&format!("[INI] Found sider.ini at: {:?}", c));
            return Some(c.clone());
        }
        log_msg(&format!("[INI] Not found: {:?}", c));
    }
    None
}

fn worker_loop() {
    log_msg(&format!("=== eFootball Sider Core {} Initializing Outside Loader Lock ===", SIDER_VERSION));

    if let Ok(cwd) = std::env::current_dir() {
        log_msg(&format!("[INI] Process working directory (CWD): {:?}", cwd));
    }

    let sider_ini_path = find_sider_ini();

    let mut root_dirs = Vec::new();
    if let Some(ref ini_p) = sider_ini_path {
        log_msg(&format!("Master config located: {:?}", ini_p));
        let active_mods = teams::load_active_mods_from_sider_ini(ini_p);
        log_msg(&format!("Loaded {} active LiveCPK packages from sider.ini", active_mods.len()));
        for m in &active_mods {
            log_msg(&format!(" [CPK ROOT] Active Package: '{}' @ {:?}", m.name, m.path));
            root_dirs.push(m.path.clone());
        }
        camera::load_camera_config_from_ini(ini_p);
    } else {
        log_msg("[INI] WARNING: sider.ini not found anywhere. Camera will use default settings.");
    }

    // Camera subsystem ALWAYS starts, even when sider.ini is missing
    camera::start_camera_hook(sider_ini_path.clone());
    log_msg("Camera & FOV real-time controller engaged.");

    livecpk::init_livecpk(root_dirs.clone());

    for r in &root_dirs {
        server::scan_server_directories(r);
    }
    log_msg("KitServer & StadiumServer directory indexing complete.");

    overlay::start_input_listener();
    log_msg("In-Game OSD HUD & Hotkey Listener engaged [Space = Menu, F1 = Freecam, Numpad = Zoom/Height].");

    log_msg("Sider Core background services operational.");

    loop {
        thread::sleep(Duration::from_secs(60));
    }
}

unsafe fn is_game_process() -> bool {
    let mut buffer = [0u16; 512];
    let len = windows_sys::Win32::System::LibraryLoader::GetModuleFileNameW(
        0 as HMODULE,
        buffer.as_mut_ptr(),
        buffer.len() as u32,
    );
    if len == 0 {
        return false;
    }
    let path = String::from_utf16_lossy(&buffer[..len as usize]).to_lowercase();
    path.contains("efootball") || path.contains("pes")
}

#[no_mangle]
pub unsafe extern "system" fn DllMain(hinst: HMODULE, reason: u32, _reserved: *mut c_void) -> BOOL {
    if reason == 1 {
        // Remember our own module handle so we can locate sider.ini next to the DLL
        let _ = SIDER_MODULE.set(hinst);
        if is_game_process() {
            log_msg("SIDER DLL_PROCESS_ATTACH triggered in game process.");
            ensure_sider_initialized();
        } else {
            log_msg("SIDER DLL_PROCESS_ATTACH in non-game host. Runtime hooks skipped.");
        }
    }
    TRUE
}