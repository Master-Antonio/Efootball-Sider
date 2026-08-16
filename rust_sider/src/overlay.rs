use std::path::PathBuf;
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::{OnceLock, RwLock};
use std::thread;
use std::time::Duration;
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, RECT, SIZE, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, BitBlt, CreateCompatibleBitmap, CreateCompatibleDC, CreateFontA,
    CreateSolidBrush, DeleteDC, DeleteObject, DrawTextA, EndPaint, FillRect, GetTextExtentPoint32A,
    InvalidateRect, SelectObject, SetTextColor, DT_LEFT, DT_SINGLELINE, DT_VCENTER, HBRUSH,
    HFONT, HDC, PAINTSTRUCT, SRCCOPY,
};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExA, DefWindowProcA, DispatchMessageA, GetSystemMetrics, PeekMessageA,
    RegisterClassA, SetLayeredWindowAttributes, SetWindowPos, ShowWindow, CS_HREDRAW, CS_VREDRAW,
    HWND_TOPMOST, LWA_ALPHA, MSG, PM_REMOVE, SM_CXSCREEN, SWP_NOACTIVATE, SWP_SHOWWINDOW, SW_HIDE,
    SW_SHOWNOACTIVATE, WNDCLASSA, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST,
    WS_EX_TRANSPARENT, WS_POPUP, WS_VISIBLE,
};
use crate::camera;

pub static OVERLAY_VISIBLE: AtomicBool = AtomicBool::new(true);
static OSD_HWND: RwLock<Option<isize>> = RwLock::new(None);
static INI_PATH: OnceLock<PathBuf> = OnceLock::new();

const VK_SPACE: i32 = 0x20;
const VK_F1: i32 = 0x70;
const VK_ADD: i32 = 0x6B;
const VK_SUBTRACT: i32 = 0x6D;
const VK_NUMPAD8: i32 = 0x68;
const VK_NUMPAD2: i32 = 0x62;
const VK_NUMPAD4: i32 = 0x64;
const VK_NUMPAD6: i32 = 0x66;
const VK_OEM_PLUS: i32 = 0xBB;
const VK_OEM_MINUS: i32 = 0xBD;
const VK_F9: i32 = 0x78;
const VK_F10: i32 = 0x79;
pub static MARK_COUNTER: AtomicUsize = AtomicUsize::new(0);

// ---------------------------------------------------------------------------
// Palette (COLORREF = 0x00BBGGRR)
// ---------------------------------------------------------------------------
const COL_BG: u32 = 0x0014141C; // deep charcoal panel
const COL_EDGE_TOP: u32 = 0x00362E2E;
const COL_EDGE_BOT: u32 = 0x000A0808;
const COL_ACCENT: u32 = 0xBFD42D; // teal bar
const COL_TEXT_MAIN: u32 = 0x00F5F5F5;
const COL_TEXT_DIM: u32 = 0x008D8CA0;
const COL_TEXT_VALUE: u32 = 0x00ECECEC;
const COL_OK: u32 = 0x99D334;
const COL_WARN: u32 = 0x24BFFB;
const COL_BAD: u32 = 0x7171F8;
const COL_FLASH: u32 = 0xFFE936;
const COL_GAME_LIVE: u32 = 0x99D334;
const COL_PILL_BG: u32 = 0x002A2836;

const PAINT_TICK_MS: u64 = 150;
const FLASH_TICKS: u32 = 7;

static TICK: AtomicU32 = AtomicU32::new(0);
static PREV_ZOOM: AtomicU32 = AtomicU32::new(0);
static PREV_HEIGHT: AtomicU32 = AtomicU32::new(0);
static PREV_ANGLE: AtomicU32 = AtomicU32::new(0);
static PREV_FOV: AtomicU32 = AtomicU32::new(0);
static CHANGED_ZOOM: AtomicU32 = AtomicU32::new(u32::MAX / 2);
static CHANGED_HEIGHT: AtomicU32 = AtomicU32::new(u32::MAX / 2);
static CHANGED_ANGLE: AtomicU32 = AtomicU32::new(u32::MAX / 2);
static CHANGED_FOV: AtomicU32 = AtomicU32::new(u32::MAX / 2);

fn track_change(prev: &AtomicU32, changed_at: &AtomicU32, new_bits: u32) {
    let old = prev.swap(new_bits, Ordering::Relaxed);
    if old != new_bits {
        changed_at.store(TICK.load(Ordering::Relaxed), Ordering::Relaxed);
    }
}

fn is_flashing(changed_at: &AtomicU32) -> bool {
    TICK.load(Ordering::Relaxed).wrapping_sub(changed_at.load(Ordering::Relaxed)) < FLASH_TICKS
}

fn hook_status(targets: usize, calls: usize) -> (&'static str, u32) {
    if targets > 0 && calls > 0 {
        ("ACTIVE", COL_OK)
    } else if targets > 0 {
        ("WAITING", COL_WARN)
    } else {
        ("OFFLINE", COL_BAD)
    }
}

pub fn set_ini_path(path: Option<PathBuf>) {
    if let Some(p) = path {
        let _ = INI_PATH.set(p);
    }
}

/// `[OVERLAY] enabled` gate (default on) so a bad HUD build can be bisected
/// away without touching the rest of the runtime.
fn overlay_enabled_from_ini() -> bool {
    let Some(path) = INI_PATH.get() else { return true };
    let Ok(text) = std::fs::read_to_string(path) else { return true };
    let mut in_section = false;
    for line in text.lines() {
        let line = line.trim();
        if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
            continue;
        }
        if line.starts_with('[') && line.ends_with(']') {
            in_section = line[1..line.len() - 1].trim().eq_ignore_ascii_case("overlay");
            continue;
        }
        if in_section {
            if let Some((k, v)) = line.split_once('=') {
                if k.trim().eq_ignore_ascii_case("enabled") {
                    let v = v.trim().trim_matches('"');
                    return v == "1" || v.eq_ignore_ascii_case("true");
                }
            }
        }
    }
    true
}

struct Fonts {
    main: HFONT,  // Consolas Ã¢â‚¬â€ status word and every numeric value
    small: HFONT, // Segoe UI Ã¢â‚¬â€ labels, chips, hints
}

impl Fonts {
    fn get() -> &'static Fonts {
        static FONTS: OnceLock<Fonts> = OnceLock::new();
        FONTS.get_or_init(|| unsafe {
            const ANTIALIASED: u32 = 4;
            Fonts {
                main: CreateFontA(20, 0, 0, 0, 640, 0, 0, 0, 0, 0, 0, ANTIALIASED, 0, b"Consolas\0".as_ptr()),
                small: CreateFontA(15, 0, 0, 0, 520, 0, 0, 0, 0, 0, 0, ANTIALIASED, 0, b"Segoe UI\0".as_ptr()),
            }
        })
    }
}

unsafe fn fill_rect(hdc: HDC, x: i32, y: i32, w: i32, h: i32, color: u32) {
    let brush: HBRUSH = CreateSolidBrush(color);
    let r = RECT { left: x, top: y, right: x + w, bottom: y + h };
    FillRect(hdc, &r, brush);
    DeleteObject(brush as _);
}

/// Text with a 1px black offset outline: readable over any in-game background
/// without resorting to opaque boxes.
unsafe fn draw_str_sh(hdc: HDC, font: HFONT, s: &str, x: i32, height: i32, color: u32) {
    SelectObject(hdc, font as _);
    let mut bytes = s.as_bytes().to_vec();
    bytes.push(0);
    let mut r_shadow = RECT { left: x + 1, top: 1, right: x + measure(hdc, font, s) + 2, bottom: height + 1 };
    SetTextColor(hdc, 0x00000000);
    DrawTextA(hdc, bytes.as_ptr(), -1, &mut r_shadow, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
    let mut r_main = RECT { left: x, top: 0, right: x + measure(hdc, font, s) + 1, bottom: height };
    SetTextColor(hdc, color);
    DrawTextA(hdc, bytes.as_ptr(), -1, &mut r_main, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
}

/// Right-aligned variant (single draw; used for the far-right hints).
unsafe fn draw_str_r(hdc: HDC, font: HFONT, s: &str, x: i32, height: i32, color: u32) {
    SelectObject(hdc, font as _);
    SetTextColor(hdc, color);
    let mut bytes = s.as_bytes().to_vec();
    bytes.push(0);
    let mut r = RECT { left: x, top: 0, right: x + measure(hdc, font, s) + 1, bottom: height };
    DrawTextA(hdc, bytes.as_ptr(), -1, &mut r, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
}

/// Pixel width of `s` rendered with `font` ÃƒÆ’Ã‚Â¢ÃƒÂ¢Ã¢â‚¬Å¡Ã‚Â¬ÃƒÂ¢Ã¢â€šÂ¬Ã‚Â the basis of the measured layout:
/// nothing is positioned by hand, so text can never overlap regardless of metrics.
unsafe fn measure(hdc: HDC, font: HFONT, s: &str) -> i32 {
    SelectObject(hdc, font as _);
    let mut sz = SIZE { cx: 0, cy: 0 };
    let bytes = s.as_bytes();
    GetTextExtentPoint32A(hdc, bytes.as_ptr(), bytes.len() as i32, &mut sz);
    sz.cx
}


unsafe fn paint_scene_inner(hdc: HDC, width: i32, height: i32) {
    let fonts = Fonts::get();

    // Panel chrome
    fill_rect(hdc, 0, 0, width, height, COL_BG);
    fill_rect(hdc, 0, 0, width, 2, COL_EDGE_TOP);
    fill_rect(hdc, 0, height - 1, width, 1, COL_EDGE_BOT);
    fill_rect(hdc, 0, 0, 3, height, COL_ACCENT);

    // Snapshot
    let cfg = match camera::CAMERA_STATE.read() {
        Ok(c) => *c,
        Err(_) => camera::CameraConfig::default(),
    };
    let freecam = camera::FREECAM_ACTIVE.load(Ordering::SeqCst);
    let targets = camera::CAMERA_TARGETS_COUNT.load(Ordering::SeqCst);
    let calls = camera::DETOUR_CALL_COUNT.load(Ordering::SeqCst);
    let data_src = camera::DATA_ADDR.load(Ordering::SeqCst);
    let (status_label, status_color) = if data_src != 0 {
        ("LIVE", COL_OK)
    } else {
        hook_status(targets, calls)
    };

    if let Some((gz, gh, ga, gf, _flag, _c)) = camera::last_game_snapshot() {
        track_change(&PREV_ZOOM, &CHANGED_ZOOM, gz.to_bits());
        track_change(&PREV_HEIGHT, &CHANGED_HEIGHT, gh.to_bits());
        track_change(&PREV_ANGLE, &CHANGED_ANGLE, ga.to_bits());
        track_change(&PREV_FOV, &CHANGED_FOV, gf.to_bits());
    }

    let mut x = 20;

    draw_str_sh(hdc, fonts.main, "SIDER", x, height, COL_TEXT_MAIN);
    x += measure(hdc, fonts.main, "SIDER") + 14;
    draw_str_sh(hdc, fonts.main, status_label, x, height, status_color);
    x += measure(hdc, fonts.main, status_label) + 12;

    let mode_label = match cfg.mode {
        camera::CameraMode::Apply => "[APPLY]",
        camera::CameraMode::Telemetry => "[TEL]",
    };
    let mode_color = match cfg.mode {
        camera::CameraMode::Apply => COL_WARN,
        camera::CameraMode::Telemetry => COL_TEXT_DIM,
    };
    draw_str_sh(hdc, fonts.small, mode_label, x, height, mode_color);
    x += measure(hdc, fonts.small, mode_label) + 12;
    if freecam {
        draw_str_sh(hdc, fonts.small, "[FC]", x, height, COL_WARN);
        x += measure(hdc, fonts.small, "[FC]") + 12;
    }
    draw_str_sh(hdc, fonts.small, "|", x, height, COL_TEXT_DIM);
    x += measure(hdc, fonts.small, "|") + 14;

    // Sider config pairs: dim label + mono value
    let fov_val = if cfg.fov < 10.0 {
        format!("{:.1}", cfg.fov)
    } else {
        format!("{:.0}", cfg.fov)
    };
    for (label, val) in [
        ("z", format!("{:.2}", cfg.zoom)),
        ("h", format!("{:.2}", cfg.height)),
        ("t", format!("{:+.2}", cfg.angle)),
        ("fov", fov_val),
    ] {
        draw_str_sh(hdc, fonts.small, label, x, height, COL_TEXT_DIM);
        x += measure(hdc, fonts.small, label) + 5;
        draw_str_sh(hdc, fonts.main, &val, x, height, COL_TEXT_VALUE);
        x += measure(hdc, fonts.main, &val) + 16;
    }
    draw_str_sh(hdc, fonts.small, "|", x, height, COL_TEXT_DIM);
    x += measure(hdc, fonts.small, "|") + 14;

    // Game live pairs
    draw_str_sh(hdc, fonts.small, "GAME", x, height, COL_GAME_LIVE);
    x += measure(hdc, fonts.small, "GAME") + 10;

    match camera::last_game_snapshot() {
        Some((gz, gh, ga, gf, gflag, _gcomp)) => {
            for (label, val, changed_flag) in [
                ("z", gz, &CHANGED_ZOOM),
                ("h", gh, &CHANGED_HEIGHT),
                ("a", ga, &CHANGED_ANGLE),
                ("f", gf, &CHANGED_FOV),
            ] {
                let hot = is_flashing(changed_flag);
                draw_str_sh(hdc, fonts.small, label, x, height, COL_TEXT_DIM);
                x += measure(hdc, fonts.small, label) + 5;
                let text = format!("{:.2}", val);
                draw_str_sh(
                    hdc,
                    fonts.main,
                    &text,
                    x,
                    height,
                    if hot { COL_FLASH } else { COL_GAME_LIVE },
                );
                x += measure(hdc, fonts.main, &text) + 14;
            }
            let meta = format!("flag {:02x} · #{}", gflag, calls);
            draw_str_sh(hdc, fonts.small, &meta, x, height, COL_TEXT_DIM);
            x += measure(hdc, fonts.small, &meta) + 14;
        }
        None => {
            let msg = "scanning memory for the config object…";
            draw_str_sh(hdc, fonts.small, msg, x, height, COL_TEXT_DIM);
            x += measure(hdc, fonts.small, msg) + 14;
        }
    }

    // Hints, right-aligned when there is room.
    let hint = "F9 mark · F10 dump · Space hide";
    let hw = measure(hdc, fonts.small, hint);
    if x < width - hw - 30 {
        draw_str_r(hdc, fonts.small, hint, width - hw - 20, height, COL_TEXT_DIM);
    }
}

unsafe fn paint_scene(hdc: HDC, width: i32, height: i32) {
    // A panic here must never unwind across the window procedure boundary.
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
        paint_scene_inner(hdc, width, height);
    }));
    if result.is_err() {
        crate::log_msg("[OVERLAY] paint panic suppressed");
        fill_rect(hdc, 0, 0, width, height, COL_BG);
    }
}
unsafe extern "system" fn osd_wnd_proc(
    hwnd: HWND,
    msg: u32,
    wparam: WPARAM,
    lparam: LPARAM,
) -> LRESULT {
    match msg {
        0x000F => {
            let mut ps: PAINTSTRUCT = std::mem::zeroed();
            let hdc = BeginPaint(hwnd, &mut ps);
            let mut rect: RECT = std::mem::zeroed();
            windows_sys::Win32::UI::WindowsAndMessaging::GetClientRect(hwnd, &mut rect);
            let w = rect.right - rect.left;
            let h = rect.bottom - rect.top;

            let mem_dc = CreateCompatibleDC(hdc);
            let mem_bmp = CreateCompatibleBitmap(hdc, w, h);
            let old_bmp = SelectObject(mem_dc, mem_bmp as _);

            paint_scene(mem_dc, w, h);
            BitBlt(hdc, 0, 0, w, h, mem_dc, 0, 0, SRCCOPY);

            SelectObject(mem_dc, old_bmp);
            DeleteObject(mem_bmp as _);
            DeleteDC(mem_dc);
            EndPaint(hwnd, &ps);
            0
        }
        0x0014 => 1, // WM_ERASEBKGND
        _ => DefWindowProcA(hwnd, msg, wparam, lparam),
    }
}

fn run_osd_window_thread() {
    unsafe {
        let class_name = b"eFootballSiderOSDClass\0";
        let wc = WNDCLASSA {
            style: CS_HREDRAW | CS_VREDRAW,
            lpfnWndProc: Some(osd_wnd_proc),
            cbClsExtra: 0,
            cbWndExtra: 0,
            hInstance: 0 as _,
            hIcon: 0 as _,
            hCursor: 0 as _,
            hbrBackground: 0 as _,
            lpszMenuName: std::ptr::null(),
            lpszClassName: class_name.as_ptr(),
        };
        RegisterClassA(&wc);
        let screen_width = GetSystemMetrics(SM_CXSCREEN);
        let win_width = 1280;
        let win_height = 58;
        let pos_x = (screen_width - win_width) / 2;
        let pos_y = 14;
        let hwnd = CreateWindowExA(
            WS_EX_TOPMOST | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW,
            class_name.as_ptr(),
            b"eFootball Sider OSD\0".as_ptr(),
            WS_POPUP | WS_VISIBLE,
            pos_x,
            pos_y,
            win_width,
            win_height,
            0 as _,
            0 as _,
            0 as _,
            std::ptr::null(),
        );
        if hwnd == 0 {
            return;
        }
        SetLayeredWindowAttributes(hwnd, 0, 236, LWA_ALPHA);
        SetWindowPos(hwnd, HWND_TOPMOST, pos_x, pos_y, win_width, win_height, SWP_SHOWWINDOW | SWP_NOACTIVATE);
        if let Ok(mut guard) = OSD_HWND.write() {
            *guard = Some(hwnd);
        }
        crate::log_msg("Visual OSD HUD spawned.");
        let mut msg: MSG = std::mem::zeroed();
        loop {
            if PeekMessageA(&mut msg, 0 as _, 0, 0, PM_REMOVE) != 0 {
                if msg.message == 0x0012 {
                    break;
                }
                DispatchMessageA(&msg);
            } else {
                TICK.fetch_add(1, Ordering::Relaxed);
                InvalidateRect(hwnd, std::ptr::null(), 0);
                thread::sleep(Duration::from_millis(PAINT_TICK_MS));
            }
        }
    }
}

/// Spawns the OSD window after a short delay so nothing heavy runs while the
/// game boots. Skipped entirely with `[OVERLAY] enabled = 0`.
pub fn spawn_osd_window() {
    thread::spawn(|| {
        thread::sleep(Duration::from_secs(6));
        if !overlay_enabled_from_ini() {
            crate::log_msg("[OVERLAY] disabled by sider.ini; skipping HUD.");
            return;
        }
        run_osd_window_thread();
    });
}

pub fn start_input_listener() {
    thread::spawn(|| {
        let mut space_pressed_prev = false;
        let mut f1_pressed_prev = false;
        let mut f9_pressed_prev = false;
        let mut f10_pressed_prev = false;
        loop {
            let space_state = unsafe { GetAsyncKeyState(VK_SPACE) } as u16 & 0x8000 != 0;
            if space_state && !space_pressed_prev {
                let visible = OVERLAY_VISIBLE.fetch_xor(true, Ordering::SeqCst);
                let now_visible = !visible;
                if let Ok(guard) = OSD_HWND.read() {
                    if let Some(hwnd) = *guard {
                        unsafe {
                            ShowWindow(hwnd, if now_visible { SW_SHOWNOACTIVATE } else { SW_HIDE });
                        }
                    }
                }
                crate::log_msg(&format!(">>> OSD Overlay Toggled: {}", now_visible));
            }
            space_pressed_prev = space_state;

            let f1_state = unsafe { GetAsyncKeyState(VK_F1) } as u16 & 0x8000 != 0;
            if f1_state && !f1_pressed_prev {
                let fc = camera::toggle_freecam();
                crate::log_msg(&format!(">>> Freecam Toggled: {}", fc));
            }
            f1_pressed_prev = f1_state;

            // F9 marker: timestamped snapshot into the native log.
            let f9_state = unsafe { GetAsyncKeyState(VK_F9) } as u16 & 0x8000 != 0;
            if f9_state && !f9_pressed_prev {
                let n = MARK_COUNTER.fetch_add(1, Ordering::SeqCst) + 1;
                let snap = match camera::last_game_snapshot() {
                    Some((z, h, a, fov, flag, _)) => format!(
                        "zoom={:.3} height={:.3} angle={:.3} fov={:.1} flag={:#04x}",
                        z, h, a, fov, flag
                    ),
                    None => "no-telemetry-yet".to_string(),
                };
                crate::log_msg(&format!("[MARK #{}] {}", n, snap));
            }
            f9_pressed_prev = f9_state;

            // F10 component dump for offline field discovery.
            let f10_state = unsafe { GetAsyncKeyState(VK_F10) } as u16 & 0x8000 != 0;
            if f10_state && !f10_pressed_prev {
                match camera::dump_last_component() {
                    Some(path) => crate::log_msg(&format!("[DUMP] component written to {}", path.display())),
                    None => crate::log_msg("[DUMP] no live component yet; nothing to dump"),
                }
            }
            f10_pressed_prev = f10_state;

            if unsafe { GetAsyncKeyState(VK_ADD) } as u16 & 0x8000 != 0
                || unsafe { GetAsyncKeyState(VK_OEM_PLUS) } as u16 & 0x8000 != 0
            {
                camera::adjust_zoom(-0.03);
            }
            if unsafe { GetAsyncKeyState(VK_SUBTRACT) } as u16 & 0x8000 != 0
                || unsafe { GetAsyncKeyState(VK_OEM_MINUS) } as u16 & 0x8000 != 0
            {
                camera::adjust_zoom(0.03);
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD8) } as u16 & 0x8000 != 0 {
                camera::adjust_height(0.03);
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD2) } as u16 & 0x8000 != 0 {
                camera::adjust_height(-0.03);
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD4) } as u16 & 0x8000 != 0 {
                camera::adjust_angle(-0.01);
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD6) } as u16 & 0x8000 != 0 {
                camera::adjust_angle(0.01);
            }
            thread::sleep(Duration::from_millis(30));
        }
    });
}

pub fn trigger_osd_refresh() {
    if let Ok(guard) = OSD_HWND.read() {
        if let Some(hwnd) = *guard {
            unsafe {
                InvalidateRect(hwnd, std::ptr::null(), 0);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_hook_status_lifecycle() {
        assert_eq!(hook_status(0, 0), ("OFFLINE", COL_BAD));
        assert_eq!(hook_status(1, 0), ("WAITING", COL_WARN));
        assert_eq!(hook_status(1, 42), ("ACTIVE", COL_OK));
    }

    #[test]
    fn test_track_change_detects_and_rearms() {
        static PREV: AtomicU32 = AtomicU32::new(0);
        static CHANGED_AT: AtomicU32 = AtomicU32::new(u32::MAX / 2);
        TICK.store(100, Ordering::Relaxed);

        assert!(is_flashing(&CHANGED_AT) == false); // far past, not flashing
        track_change(&PREV, &CHANGED_AT, 5);
        assert!(is_flashing(&CHANGED_AT));

        // Same value: no re-arm.
        TICK.store(101, Ordering::Relaxed);
        track_change(&PREV, &CHANGED_AT, 5);

        // Advance past flash window.
        TICK.store(100 + FLASH_TICKS + 1, Ordering::Relaxed);
        assert!(!is_flashing(&CHANGED_AT));

        // Real change re-arms.
        track_change(&PREV, &CHANGED_AT, 9);
        assert!(is_flashing(&CHANGED_AT));

        PREV.store(0, Ordering::Relaxed);
        CHANGED_AT.store(u32::MAX / 2, Ordering::Relaxed);
    }
}
