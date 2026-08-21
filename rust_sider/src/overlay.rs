use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::{Duration, Instant};
use windows_sys::Win32::Foundation::{HWND, LPARAM, LRESULT, RECT, WPARAM};
use windows_sys::Win32::Graphics::Gdi::{
    BeginPaint, CreateFontA, CreateSolidBrush, DeleteObject, DrawTextA, EndPaint, FillRect,
    InvalidateRect, SelectObject, SetBkMode, SetTextColor, DT_CENTER, DT_LEFT, DT_RIGHT,
    DT_SINGLELINE, DT_VCENTER, HBRUSH, HFONT, PAINTSTRUCT, TRANSPARENT,
};
use windows_sys::Win32::UI::Input::KeyboardAndMouse::GetAsyncKeyState;
use windows_sys::Win32::UI::WindowsAndMessaging::{
    CreateWindowExA, DefWindowProcA, DispatchMessageA, PeekMessageA, RegisterClassA,
    SetLayeredWindowAttributes, SetWindowPos, ShowWindow, CS_HREDRAW, CS_VREDRAW, HWND_TOPMOST,
    LWA_ALPHA, MSG, PM_REMOVE, SWP_NOACTIVATE, SWP_SHOWWINDOW, SW_HIDE, SW_SHOWNOACTIVATE,
    WNDCLASSA, WS_EX_LAYERED, WS_EX_TOOLWINDOW, WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_POPUP,
    WS_VISIBLE,
};
use crate::camera;

pub static OVERLAY_VISIBLE: AtomicBool = AtomicBool::new(true);
pub static MENU_STATE: RwLock<Option<MenuState>> = RwLock::new(None);
static OSD_HWND: RwLock<Option<HWND>> = RwLock::new(None);

// Virtual Key Codes
const VK_TAB: i32 = 0x09;
const VK_RETURN: i32 = 0x0D;
const VK_SPACE: i32 = 0x20;
const VK_LEFT: i32 = 0x25;
const VK_UP: i32 = 0x26;
const VK_RIGHT: i32 = 0x27;
const VK_DOWN: i32 = 0x28;
const VK_F1: i32 = 0x70;

#[derive(Copy, Clone, Debug, PartialEq, Eq)]
pub enum MenuTab {
    PlayerStats = 0,
    PlayerSkills = 1,
    MatchCheats = 2,
    CameraSettings = 3,
}

impl MenuTab {
    pub fn title(self) -> &'static str {
        match self {
            MenuTab::PlayerStats => "1.能力 (Stats)",
            MenuTab::PlayerSkills => "2.特技 (Skills)",
            MenuTab::MatchCheats => "3.辅助 (Cheats)",
            MenuTab::CameraSettings => "4.镜头 (Camera)",
        }
    }
}

#[derive(Clone, Debug)]
pub struct MenuState {
    pub active_tab: usize,
    pub selected_index: usize,
    // Tab 0: Player Stats
    pub stat_speed: u8,
    pub stat_finishing: u8,
    pub stat_stamina: u8,
    pub stat_form_top: bool,
    // Tab 1: Player Skills
    pub skill_double_touch: bool,
    pub skill_marseille_turn: bool,
    pub skill_dipping_shot: bool,
    pub skill_interception: bool,
    // Tab 2: Match Cheats
    pub cheat_infinite_stamina: bool,
    pub cheat_game_speed: f32,
    // Notification message
    pub status_message: String,
    pub status_time: Option<Instant>,
}

impl Default for MenuState {
    fn default() -> Self {
        Self {
            active_tab: 0,
            selected_index: 0,
            stat_speed: 90,
            stat_finishing: 90,
            stat_stamina: 90,
            stat_form_top: true,
            skill_double_touch: true,
            skill_marseille_turn: true,
            skill_dipping_shot: true,
            skill_interception: true,
            cheat_infinite_stamina: false,
            cheat_game_speed: 1.0,
            status_message: "OSD 悬浮交互菜单已就绪 [Space呼出/隐藏]".to_string(),
            status_time: Some(Instant::now()),
        }
    }
}

impl MenuState {
    pub fn next_tab(&mut self) {
        self.active_tab = (self.active_tab + 1) % 4;
        self.selected_index = 0;
    }

    pub fn prev_tab(&mut self) {
        self.active_tab = if self.active_tab == 0 { 3 } else { self.active_tab - 1 };
        self.selected_index = 0;
    }

    pub fn get_items_count(&self) -> usize {
        match self.active_tab {
            0 => 5, // 一键99, 状态绝佳, 速度, 射门, 体力
            1 => 4, // 双触, 马赛回旋, 急坠射门, 拦截大师
            2 => 2, // 无限体能锁, 比赛速度
            3 => 4, // Zoom, Height, Angle, Freecam
            _ => 0,
        }
    }

    pub fn next_item(&mut self) {
        let count = self.get_items_count();
        if count > 0 {
            self.selected_index = (self.selected_index + 1) % count;
        }
    }

    pub fn prev_item(&mut self) {
        let count = self.get_items_count();
        if count > 0 {
            self.selected_index = if self.selected_index == 0 {
                count - 1
            } else {
                self.selected_index - 1
            };
        }
    }

    pub fn adjust_left(&mut self) {
        match self.active_tab {
            0 => match self.selected_index {
                1 => self.stat_form_top = !self.stat_form_top,
                2 => self.stat_speed = self.stat_speed.saturating_sub(1).max(40),
                3 => self.stat_finishing = self.stat_finishing.saturating_sub(1).max(40),
                4 => self.stat_stamina = self.stat_stamina.saturating_sub(1).max(40),
                _ => {}
            },
            1 => match self.selected_index {
                0 => self.skill_double_touch = !self.skill_double_touch,
                1 => self.skill_marseille_turn = !self.skill_marseille_turn,
                2 => self.skill_dipping_shot = !self.skill_dipping_shot,
                3 => self.skill_interception = !self.skill_interception,
                _ => {}
            },
            2 => match self.selected_index {
                0 => self.cheat_infinite_stamina = !self.cheat_infinite_stamina,
                1 => self.cheat_game_speed = (self.cheat_game_speed - 0.05).max(0.7),
                _ => {}
            },
            3 => match self.selected_index {
                0 => camera::adjust_zoom(-0.03),
                1 => camera::adjust_height(-0.03),
                2 => camera::adjust_angle(-0.01),
                3 => { camera::toggle_freecam(); }
                _ => {}
            },
            _ => {}
        }
    }

    pub fn adjust_right(&mut self) {
        match self.active_tab {
            0 => match self.selected_index {
                1 => self.stat_form_top = !self.stat_form_top,
                2 => self.stat_speed = (self.stat_speed + 1).min(99),
                3 => self.stat_finishing = (self.stat_finishing + 1).min(99),
                4 => self.stat_stamina = (self.stat_stamina + 1).min(99),
                _ => {}
            },
            1 => match self.selected_index {
                0 => self.skill_double_touch = !self.skill_double_touch,
                1 => self.skill_marseille_turn = !self.skill_marseille_turn,
                2 => self.skill_dipping_shot = !self.skill_dipping_shot,
                3 => self.skill_interception = !self.skill_interception,
                _ => {}
            },
            2 => match self.selected_index {
                0 => self.cheat_infinite_stamina = !self.cheat_infinite_stamina,
                1 => self.cheat_game_speed = (self.cheat_game_speed + 0.05).min(1.5),
                _ => {}
            },
            3 => match self.selected_index {
                0 => camera::adjust_zoom(0.03),
                1 => camera::adjust_height(0.03),
                2 => camera::adjust_angle(0.01),
                3 => { camera::toggle_freecam(); }
                _ => {}
            },
            _ => {}
        }
    }

    pub fn activate(&mut self) {
        match self.active_tab {
            0 => match self.selected_index {
                0 => {
                    self.stat_speed = 99;
                    self.stat_finishing = 99;
                    self.stat_stamina = 99;
                    self.stat_form_top = true;
                    self.set_status("[成功] 球员全属性已一键拉满为 99！");
                }
                1 => {
                    self.stat_form_top = !self.stat_form_top;
                    self.set_status(if self.stat_form_top { "[生效] 状态已设为绝佳 (红/绿大箭头)" } else { "[恢复] 状态已恢复正常" });
                }
                _ => {
                    self.set_status("[已保存] 属性值已设定，离线模式生效中");
                }
            },
            1 => match self.selected_index {
                0 => { self.skill_double_touch = !self.skill_double_touch; self.set_status("双触过人开关已切换"); }
                1 => { self.skill_marseille_turn = !self.skill_marseille_turn; self.set_status("马赛回旋开关已切换"); }
                2 => { self.skill_dipping_shot = !self.skill_dipping_shot; self.set_status("急坠射门开关已切换"); }
                3 => { self.skill_interception = !self.skill_interception; self.set_status("拦截大师开关已切换"); }
                _ => {}
            },
            2 => match self.selected_index {
                0 => {
                    self.cheat_infinite_stamina = !self.cheat_infinite_stamina;
                    self.set_status(if self.cheat_infinite_stamina { "[开启] 无限体能锁已激活" } else { "[关闭] 无限体能锁已关闭" });
                }
                1 => {
                    self.cheat_game_speed = 1.0;
                    self.set_status("[恢复] 游戏速度已重置为 1.0x");
                }
                _ => {}
            },
            3 => match self.selected_index {
                3 => {
                    let fc = camera::toggle_freecam();
                    self.set_status(if fc { "[开启] Freecam 自由视角已开启 (F1)" } else { "[关闭] Freecam 自由视角已关闭" });
                }
                _ => {
                    self.set_status("[已同步] 摄像机参数已应用");
                }
            },
            _ => {}
        }
    }

    pub fn set_status(&mut self, msg: &str) {
        self.status_message = msg.to_string();
        self.status_time = Some(Instant::now());
    }

    pub fn get_tab_items(&self) -> Vec<(String, String)> {
        match self.active_tab {
            0 => vec![
                ("[Enter] 一键全属性拉满 (God Mode)".to_string(), "99 MAX".to_string()),
                ("比赛状态 (Match Form)".to_string(), if self.stat_form_top { "绝佳 (Top Arrow)" } else { "正常 (Normal)" }.to_string()),
                ("速度 & 加速度 (Speed & Accel)".to_string(), format!("< {} >", self.stat_speed)),
                ("射门精度 & 力量 (Finishing)".to_string(), format!("< {} >", self.stat_finishing)),
                ("体能耐力 (Stamina)".to_string(), format!("< {} >", self.stat_stamina)),
            ],
            1 => vec![
                ("双触过人 (Double Touch)".to_string(), if self.skill_double_touch { "[ ON ]" } else { "[ OFF ]" }.to_string()),
                ("马赛回旋 (Marseille Turn)".to_string(), if self.skill_marseille_turn { "[ ON ]" } else { "[ OFF ]" }.to_string()),
                ("急坠射门 (Dipping Shot)".to_string(), if self.skill_dipping_shot { "[ ON ]" } else { "[ OFF ]" }.to_string()),
                ("拦截大师 (Interception)".to_string(), if self.skill_interception { "[ ON ]" } else { "[ OFF ]" }.to_string()),
            ],
            2 => vec![
                ("无限体能锁 (Infinite Stamina)".to_string(), if self.cheat_infinite_stamina { "[ ON ]" } else { "[ OFF ]" }.to_string()),
                ("比赛节奏速度 (Match Speed)".to_string(), format!("< {:.2}x >", self.cheat_game_speed)),
            ],
            3 => {
                let cfg = camera::CAMERA_STATE.read().map(|c| *c).unwrap_or_default();
                let freecam = camera::FREECAM_ACTIVE.load(Ordering::SeqCst);
                vec![
                    ("摄像机缩放 (Camera Zoom)".to_string(), format!("< {:.2} >", cfg.zoom)),
                    ("摄像机高度 (Camera Height)".to_string(), format!("< {:.2} >", cfg.height)),
                    ("视角倾角 (Camera Angle)".to_string(), format!("< {:.2} >", cfg.angle)),
                    ("自由视角模式 (Freecam Mode)".to_string(), if freecam { "[ ON ] (F1)" } else { "[ OFF ] (F1)" }.to_string()),
                ]
            }
            _ => Vec::new(),
        }
    }
}

pub fn start_input_listener() {
    if let Ok(mut state_guard) = MENU_STATE.write() {
        if state_guard.is_none() {
            *state_guard = Some(MenuState::default());
        }
    }

    thread::spawn(|| {
        run_osd_window_thread();
    });

    thread::spawn(|| {
        let mut key_states: [bool; 256] = [false; 256];

        loop {
            let mut changed = false;

            let check_key_pressed = |vk: i32, key_states: &mut [bool; 256]| -> bool {
                let is_down = unsafe { GetAsyncKeyState(vk) } as u16 & 0x8000 != 0;
                let idx = (vk & 0xFF) as usize;
                let was_down = key_states[idx];
                key_states[idx] = is_down;
                is_down && !was_down
            };

            // Space: Toggle visibility
            if check_key_pressed(VK_SPACE, &mut key_states) {
                let current = OVERLAY_VISIBLE.fetch_xor(true, Ordering::SeqCst);
                let new_st = !current;
                crate::log_msg(&format!(">>> OSD Overlay Toggled: {}", new_st));
                trigger_osd_refresh();
            }

            if OVERLAY_VISIBLE.load(Ordering::SeqCst) {
                if let Ok(mut guard) = MENU_STATE.write() {
                    if let Some(ref mut menu) = *guard {
                        // Tab: Switch category
                        if check_key_pressed(VK_TAB, &mut key_states) {
                            menu.next_tab();
                            changed = true;
                        }

                        // Up: Previous item
                        if check_key_pressed(VK_UP, &mut key_states) {
                            menu.prev_item();
                            changed = true;
                        }

                        // Down: Next item
                        if check_key_pressed(VK_DOWN, &mut key_states) {
                            menu.next_item();
                            changed = true;
                        }

                        // Left: Decrease / toggle
                        if check_key_pressed(VK_LEFT, &mut key_states) {
                            menu.adjust_left();
                            changed = true;
                        }

                        // Right: Increase / toggle
                        if check_key_pressed(VK_RIGHT, &mut key_states) {
                            menu.adjust_right();
                            changed = true;
                        }

                        // Enter: Activate action
                        if check_key_pressed(VK_RETURN, &mut key_states) {
                            menu.activate();
                            changed = true;
                        }
                    }
                }
            }

            // F1: Freecam
            if check_key_pressed(VK_F1, &mut key_states) {
                let fc = camera::toggle_freecam();
                crate::log_msg(&format!(">>> Freecam Toggled: {}", fc));
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

            // 1. Dark Card Background (RGB: 18, 20, 28)
            let bg_brush: HBRUSH = CreateSolidBrush(0x001C1412);
            FillRect(hdc, &rect, bg_brush);
            DeleteObject(bg_brush as _);

            // 2. Top Accent Strip (Emerald Green: RGB 0, 210, 160 = 0x00A0D200)
            let top_strip = RECT { left: 0, top: 0, right: rect.right, bottom: 4 };
            let accent_brush = CreateSolidBrush(0x00A0D200);
            FillRect(hdc, &top_strip, accent_brush);
            DeleteObject(accent_brush as _);

            SetBkMode(hdc, TRANSPARENT as _);

            // Fonts
            let font_title: HFONT = CreateFontA(17, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, b"Segoe UI\0".as_ptr());
            let font_tabs: HFONT = CreateFontA(14, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, b"Segoe UI\0".as_ptr());
            let font_body: HFONT = CreateFontA(15, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, b"Segoe UI\0".as_ptr());
            let font_body_bold: HFONT = CreateFontA(15, 0, 0, 0, 700, 0, 0, 0, 0, 0, 0, 0, 0, b"Segoe UI\0".as_ptr());
            let font_small: HFONT = CreateFontA(13, 0, 0, 0, 400, 0, 0, 0, 0, 0, 0, 0, 0, b"Segoe UI\0".as_ptr());

            let menu_guard = MENU_STATE.read().ok();
            let menu = menu_guard.as_ref().and_then(|g| g.as_ref());

            let active_tab = menu.map(|m| m.active_tab).unwrap_or(0);
            let selected_idx = menu.map(|m| m.selected_index).unwrap_or(0);

            // 3. Header Title
            let old_font = SelectObject(hdc, font_title as _);
            SetTextColor(hdc, 0x00FFFFFF);
            let mut title_rect = RECT { left: 18, top: 12, right: rect.right - 18, bottom: 34 };
            let title_text = b"eFootball Sider Mod Menu (Offline Mode)\0";
            DrawTextA(hdc, title_text.as_ptr(), -1, &mut title_rect, DT_LEFT | DT_VCENTER | DT_SINGLELINE);

            // 4. Tab Headers
            SelectObject(hdc, font_tabs as _);
            let tabs = [
                MenuTab::PlayerStats.title(),
                MenuTab::PlayerSkills.title(),
                MenuTab::MatchCheats.title(),
                MenuTab::CameraSettings.title(),
            ];
            let tab_w = (rect.right - 36) / 4;
            for (i, t_name) in tabs.iter().enumerate() {
                let t_left = 18 + (i as i32 * tab_w);
                let mut t_rect = RECT { left: t_left, top: 40, right: t_left + tab_w - 4, bottom: 64 };
                if i == active_tab {
                    let tab_bg = CreateSolidBrush(0x00A0D200);
                    FillRect(hdc, &t_rect, tab_bg);
                    DeleteObject(tab_bg as _);
                    SetTextColor(hdc, 0x00101010);
                } else {
                    let tab_bg = CreateSolidBrush(0x0028201C);
                    FillRect(hdc, &t_rect, tab_bg);
                    DeleteObject(tab_bg as _);
                    SetTextColor(hdc, 0x00909090);
                }
                let mut t_bytes = t_name.as_bytes().to_vec();
                t_bytes.push(0);
                DrawTextA(hdc, t_bytes.as_ptr(), -1, &mut t_rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);
            }

            // 5. Menu Items List
            if let Some(m) = menu {
                let items = m.get_tab_items();
                let start_y = 76;
                let row_height = 36;

                for (idx, (label, val)) in items.iter().enumerate() {
                    let item_top = start_y + (idx as i32 * row_height);
                    let item_rect = RECT { left: 18, top: item_top, right: rect.right - 18, bottom: item_top + row_height - 4 };

                    if idx == selected_idx {
                        let sel_bg = CreateSolidBrush(0x003D2E26); // Highlighting (RGB: 38, 46, 61)
                        FillRect(hdc, &item_rect, sel_bg);
                        DeleteObject(sel_bg as _);
                        SetTextColor(hdc, 0x00D0FFFF);
                        SelectObject(hdc, font_body_bold as _);
                    } else {
                        let item_bg = CreateSolidBrush(0x00221A16);
                        FillRect(hdc, &item_rect, item_bg);
                        DeleteObject(item_bg as _);
                        SetTextColor(hdc, 0x00CCCCCC);
                        SelectObject(hdc, font_body as _);
                    }

                    // Left Label
                    let prefix = if idx == selected_idx { "▶  " } else { "    " };
                    let mut lbl_text = format!("{}{}", prefix, label).into_bytes();
                    lbl_text.push(0);
                    let mut lbl_rect = RECT { left: item_rect.left + 8, top: item_rect.top, right: item_rect.right - 130, bottom: item_rect.bottom };
                    DrawTextA(hdc, lbl_text.as_ptr(), -1, &mut lbl_rect, DT_LEFT | DT_VCENTER | DT_SINGLELINE);

                    // Right Value
                    let mut val_text = val.clone().into_bytes();
                    val_text.push(0);
                    let mut val_rect = RECT { left: item_rect.right - 140, top: item_rect.top, right: item_rect.right - 12, bottom: item_rect.bottom };
                    DrawTextA(hdc, val_text.as_ptr(), -1, &mut val_rect, DT_RIGHT | DT_VCENTER | DT_SINGLELINE);
                }

                // 6. Notification Bar
                let mut status_rect = RECT { left: 18, top: 310, right: rect.right - 18, bottom: 334 };
                let notif_bg = CreateSolidBrush(0x00251C18);
                FillRect(hdc, &status_rect, notif_bg);
                DeleteObject(notif_bg as _);

                SelectObject(hdc, font_small as _);
                SetTextColor(hdc, 0x0050FF90); // Green accent for status
                let mut notif_bytes = format!(" ℹ  {}", m.status_message).into_bytes();
                notif_bytes.push(0);
                DrawTextA(hdc, notif_bytes.as_ptr(), -1, &mut status_rect, DT_LEFT | DT_VCENTER | DT_SINGLELINE);
            }

            // 7. Footer Instructions
            SelectObject(hdc, font_small as _);
            SetTextColor(hdc, 0x00808080);
            let mut footer_rect = RECT { left: 18, top: 342, right: rect.right - 18, bottom: 364 };
            let mut footer_bytes = "[Space] 呼出/隐藏 | [Tab] 切换分类 | [Up/Down] 选择 | [Left/Right] 调节 | [Enter] 执行".as_bytes().to_vec();
            footer_bytes.push(0);
            DrawTextA(hdc, footer_bytes.as_ptr(), -1, &mut footer_rect, DT_CENTER | DT_VCENTER | DT_SINGLELINE);

            // Cleanup GDI objects
            SelectObject(hdc, old_font);
            DeleteObject(font_title as _);
            DeleteObject(font_tabs as _);
            DeleteObject(font_body as _);
            DeleteObject(font_body_bold as _);
            DeleteObject(font_small as _);

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

        let win_width = 560;
        let win_height = 380;
        let pos_x = 24;
        let pos_y = 24;

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
            SetLayeredWindowAttributes(hwnd, 0, 235, LWA_ALPHA);
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_menu_state_tab_and_item_navigation() {
        let mut state = MenuState::default();
        assert_eq!(state.active_tab, 0);
        assert_eq!(state.selected_index, 0);

        // Tab wrapping
        state.next_tab();
        assert_eq!(state.active_tab, 1);
        state.next_tab();
        assert_eq!(state.active_tab, 2);
        state.next_tab();
        assert_eq!(state.active_tab, 3);
        state.next_tab();
        assert_eq!(state.active_tab, 0);

        // Item navigation wrapping
        let count = state.get_items_count();
        state.prev_item();
        assert_eq!(state.selected_index, count - 1);
        state.next_item();
        assert_eq!(state.selected_index, 0);
    }

    #[test]
    fn test_menu_state_adjust_and_activate() {
        let mut state = MenuState::default();
        state.active_tab = 0; // Stats tab

        // Row 0: activate (Max all to 99)
        state.selected_index = 0;
        state.activate();
        assert_eq!(state.stat_speed, 99);
        assert_eq!(state.stat_finishing, 99);
        assert_eq!(state.stat_stamina, 99);
        assert!(state.stat_form_top);
        assert!(state.status_message.contains("99"));

        // Row 2: Speed adjust bounds
        state.selected_index = 2;
        state.adjust_left();
        assert_eq!(state.stat_speed, 98);
        state.adjust_right();
        assert_eq!(state.stat_speed, 99);
        state.adjust_right(); // should clamp to 99
        assert_eq!(state.stat_speed, 99);
    }
}

