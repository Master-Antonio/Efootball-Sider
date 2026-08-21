use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, CreateFontA, CreateSolidBrush, DeleteObject, DrawTextA, EndPaint, FillRect,
    InvalidateRect, SelectObject, SetBkMode, SetTextColor, DT_CENTER, DT_SINGLELINE, DT_VCENTER,
    HBRUSH, HFONT, PAINTSTRUCT, TRANSPARENT,
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
static LAST_INTERACTION_TIME: RwLock<Option<Instant>> = RwLock::new(None);
static OSD_HWND: RwLock<Option<HWND>> = RwLock::new(None);
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
pub fn start_input_listener() {
    thread::spawn(|| {
        run_osd_window_thread();
    });
    thread::spawn(|| {
        let mut space_pressed_prev = false;
        let mut f1_pressed_prev = false;
        loop {
            let mut changed = false;
            let space_state = unsafe { GetAsyncKeyState(VK_SPACE) } as u16 & 0x8000 != 0;
            if space_state && !space_pressed_prev {
                let current = OVERLAY_VISIBLE.fetch_xor(true, Ordering::SeqCst);
                let new_st = !current;
                crate::log_msg(&format!(">>> OSD Overlay Toggled: {}", new_st));
                trigger_osd_refresh();
            }
            space_pressed_prev = space_state;
            let f1_state = unsafe { GetAsyncKeyState(VK_F1) } as u16 & 0x8000 != 0;
            if f1_state && !f1_pressed_prev {
                let fc = camera::toggle_freecam();
                crate::log_msg(&format!(">>> Freecam Toggled: {}", fc));
                changed = true;
            }
            f1_pressed_prev = f1_state;
            if unsafe { GetAsyncKeyState(VK_ADD) } as u16 & 0x8000 != 0
                || unsafe { GetAsyncKeyState(VK_OEM_PLUS) } as u16 & 0x8000 != 0
            {
                camera::adjust_zoom(-0.03);
                changed = true;
            }
            if unsafe { GetAsyncKeyState(VK_SUBTRACT) } as u16 & 0x8000 != 0
                || unsafe { GetAsyncKeyState(VK_OEM_MINUS) } as u16 & 0x8000 != 0
            {
                camera::adjust_zoom(0.03);
                changed = true;
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD8) } as u16 & 0x8000 != 0 {
                camera::adjust_height(0.03);
                changed = true;
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD2) } as u16 & 0x8000 != 0 {
                camera::adjust_height(-0.03);
                changed = true;
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD4) } as u16 & 0x8000 != 0 {
                camera::adjust_angle(-0.01);
                changed = true;
            }
            if unsafe { GetAsyncKeyState(VK_NUMPAD6) } as u16 & 0x8000 != 0 {
                camera::adjust_angle(0.01);
                changed = true;
            }
            if changed {
                trigger_osd_refresh();
            }
            thread::sleep(Duration::from_millis(60));
        }
    });
}
fn trigger_osd_refresh() {
    if let Ok(mut last) = LAST_INTERACTION_TIME.write() {
        *last = Some(Instant::now());
    }
    if let Ok(guard) = OSD_HWND.read() {
        if let Some(hwnd) = *guard {
            unsafe {
                InvalidateRect(hwnd, std::ptr::null(), 1);
                if OVERLAY_VISIBLE.load(Ordering::SeqCst) {
                    ShowWindow(hwnd, SW_SHOWNOACTIVATE);
                } else {
                    ShowWindow(hwnd, SW_HIDE);
                }
            }
        }
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
            let bg_brush: HBRUSH = CreateSolidBrush(0x00121010); 
            FillRect(hdc, &rect, bg_brush);
            DeleteObject(bg_brush as _);
            let cfg = match camera::CAMERA_STATE.read() {
                Ok(c) => *c,
                Err(_) => camera::CameraConfig::default(),
            };
            let freecam = camera::FREECAM_ACTIVE.load(Ordering::SeqCst);
            SetBkMode(hdc, TRANSPARENT as _);
            SetTextColor(hdc, 0x00E0E0E0); 
            let font: HFONT = CreateFontA(
                18, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0,
                b"Segoe UI\0".as_ptr(),
            );
            let old_font = SelectObject(hdc, font as _);
            let targets_count = camera::CAMERA_TARGETS_COUNT.load(Ordering::SeqCst);
            let text = format!(
                " [SIDER WIP] ZOOM: {:.2} | HEIGHT: {:.2} | TILT: {:.2} | FOV: {:.1} deg | HOOKS: {} | FREECAM: {} [Space=Hide] ",
                cfg.zoom,
                cfg.height,
                cfg.angle,
                cfg.fov,
                targets_count,
                if freecam { "ON (F1)" } else { "OFF (F1)" }
            );
            let mut text_bytes = text.into_bytes();
            text_bytes.push(0);
            DrawTextA(
                hdc,
                text_bytes.as_ptr(),
                -1,
                &mut rect,
                DT_CENTER | DT_VCENTER | DT_SINGLELINE,
            );
            SelectObject(hdc, old_font);
            DeleteObject(font as _);
            EndPaint(hwnd, &ps);
            0
        }
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
        let win_width = 1100;
        let win_height = 42;
        let pos_x = (screen_width - win_width) / 2;
        let pos_y = 18;
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
        if hwnd != 0 as _ {
            SetLayeredWindowAttributes(hwnd, 0, 225, LWA_ALPHA);
            SetWindowPos(
                hwnd,
                HWND_TOPMOST,
                pos_x,
                pos_y,
                win_width,
                win_height,
                SWP_SHOWWINDOW | SWP_NOACTIVATE,
            );
            if let Ok(mut guard) = OSD_HWND.write() {
                *guard = Some(hwnd);
            }
            crate::log_msg("Visual OSD Topmost HUD Window successfully spawned on screen.");
            let mut msg: MSG = std::mem::zeroed();
            loop {
                while PeekMessageA(&mut msg, 0 as _, 0, 0, PM_REMOVE) != 0 {
                    if msg.message == 0x0012 {
                        return;
                    }
                    DispatchMessageA(&msg);
                }
                thread::sleep(Duration::from_millis(16));
            }
        }
    }
}
