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
use std::path::Path;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Once, OnceLock};
use std::thread;
use std::time::Duration;
use windows_sys::Win32::Foundation::{BOOL, HMODULE, TRUE};
use windows_sys::Win32::System::LibraryLoader::{GetProcAddress, LoadLibraryA};

const SIDER_VERSION: &str = "v1.1";

/// Funzione di log principale di Sider: inoltra al modulo logger asincrono
pub fn log_msg(msg: &str) {
    logger::log_async(msg);
}

static REAL_DXGI: OnceLock<HMODULE> = OnceLock::new();
static SIDER_INITIALIZED: Once = Once::new();
static FIRST_FORWARD_LOGGED: AtomicBool = AtomicBool::new(false);

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

fn worker_loop() {
    log_msg(&format!("=== eFootball Sider Core {} Initializing Outside Loader Lock ===", SIDER_VERSION));
    let ini_candidates = [
        "sider.ini",
        "../sider.ini",
        "../../sider.ini",
    ];
    let mut sider_ini_path = None;
    for cand in ini_candidates {
        let p = Path::new(cand);
        if p.exists() {
            sider_ini_path = Some(p.to_path_buf());
            break;
        }
    }

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
        camera::start_camera_hook(sider_ini_path.clone());
        log_msg("Camera & FOV real-time controller engaged.");
    }

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

#[no_mangle]
pub unsafe extern "system" fn DllMain(_hinst: HMODULE, reason: u32, _reserved: *mut c_void) -> BOOL {
    if reason == 1 {
        log_msg("SIDER DLL_PROCESS_ATTACH triggered safely.");
        ensure_sider_initialized();
    }
    TRUE
}
