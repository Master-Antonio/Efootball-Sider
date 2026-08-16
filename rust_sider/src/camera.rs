use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, AtomicU32, AtomicUsize, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::{Duration, Instant, SystemTime};

use windows_sys::Win32::System::Memory::{
    VirtualAlloc, VirtualProtect, MEM_COMMIT, MEM_RESERVE, PAGE_EXECUTE_READWRITE,
};

/// PesCameraComponent parameter-load signature (zoom/height/angle/fov floats).
/// Verified unique in the 2026-08-16 Steam build `.xcode` section (RVA 0x17E3597).
/// The four loads read `[rsi+0x105C]` `[rsi+0x1060]` `[rsi+0x1064]` `[rsi+0x1068]`,
/// where rsi is the live camera component. The hooked bytes are relocation-safe
/// (no RIP-relative instructions).
pub const PES_CAMERA_SIG: &str = "F3 0F 10 B6 5C 10 00 00 F3 0F 10 BE 60 10 00 00 F3 44 0F 10 86 64 10 00 00 F3 44 0F 10 8E 68 10 00 00";
const PES_CAMERA_HOOK_LEN: usize = 34;

// PesCameraComponent field offsets (see docs/UNREAL_ENGINE_EFOOTBALL_ARCHITECTURE.md)
const PC_ZOOM_OFF: usize = 0x105C;
const PC_HEIGHT_OFF: usize = 0x1060;
const PC_ANGLE_OFF: usize = 0x1064;
const PC_FOV_OFF: usize = 0x1068;
const PC_MODE_FLAG_OFF: usize = 0x1048;

/// Legacy unverified FMinimalViewInfo-style signatures. On the current build they
/// matched init-time struct-copy code (3 calls per session, bogus pointer), so they
/// are disabled by default and only installed behind `legacy_hooks = 1`.
pub const UE4_CAMERA_SIG_1: &str = "F3 0F 11 49 2C F3 0F 10 45 70 F3 0F 11 41 30";
pub const UE4_CAMERA_SIG_2: &str = "F3 0F 11 6B 18 F3 0F 11 63 1C F3 0F 11 4B 24";
const LEGACY_HOOK_LEN: usize = 15;

pub static FREECAM_ACTIVE: AtomicBool = AtomicBool::new(false);
pub static FREECAM_OFFSET_X: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Y: AtomicU32 = AtomicU32::new(0);
pub static FREECAM_OFFSET_Z: AtomicU32 = AtomicU32::new(0);

pub static CAMERA_TARGETS_COUNT: AtomicUsize = AtomicUsize::new(0);
pub static DETOUR_CALL_COUNT: AtomicUsize = AtomicUsize::new(0);
static NULL_PTR_LOGGED: AtomicBool = AtomicBool::new(false);

// Last raw values observed from the live PesCameraComponent (f32 stored as bits).
// The OSD reads these to display what the GAME is actually using, which is the
// core tool for mapping sider.ini values to game-native units.
pub static LAST_GAME_ZOOM: AtomicU32 = AtomicU32::new(0);
pub static LAST_GAME_HEIGHT: AtomicU32 = AtomicU32::new(0);
pub static LAST_GAME_ANGLE: AtomicU32 = AtomicU32::new(0);
pub static LAST_GAME_FOV: AtomicU32 = AtomicU32::new(0);
pub static LAST_GAME_FLAG: AtomicU32 = AtomicU32::new(0);
pub static LAST_GAME_COMP: AtomicUsize = AtomicUsize::new(0);

fn store_game_values(zoom: f32, height: f32, angle: f32, fov: f32, flag: u8, comp: usize) {
    LAST_GAME_ZOOM.store(zoom.to_bits(), Ordering::Relaxed);
    LAST_GAME_HEIGHT.store(height.to_bits(), Ordering::Relaxed);
    LAST_GAME_ANGLE.store(angle.to_bits(), Ordering::Relaxed);
    LAST_GAME_FOV.store(fov.to_bits(), Ordering::Relaxed);
    LAST_GAME_FLAG.store(flag as u32, Ordering::Relaxed);
    LAST_GAME_COMP.store(comp, Ordering::Relaxed);
}

/// Formatted "game-native" snapshot for the OSD; empty until the hook fired.
pub fn last_game_snapshot() -> Option<(f32, f32, f32, f32, u8, usize)> {
    let comp = LAST_GAME_COMP.load(Ordering::Relaxed);
    if comp == 0 {
        return None;
    }
    Some((
        f32::from_bits(LAST_GAME_ZOOM.load(Ordering::Relaxed)),
        f32::from_bits(LAST_GAME_HEIGHT.load(Ordering::Relaxed)),
        f32::from_bits(LAST_GAME_ANGLE.load(Ordering::Relaxed)),
        f32::from_bits(LAST_GAME_FOV.load(Ordering::Relaxed)),
        LAST_GAME_FLAG.load(Ordering::Relaxed) as u8,
        comp,
    ))
}

/// How many bytes of the component to capture with F10 (covers the header,
/// transform area and the 0x1048..0x106C config block).
pub const COMPONENT_DUMP_LEN: usize = 0x1200;

// ---------------------------------------------------------------------------
// Plan B — global config data scanner.
// The code hook may sit on a path some flows never execute; the config VALUES,
// however, live somewhere in writable memory with the component layout
// (u8 flag == 1 at +0x00, zoom/height/angle/fov f32 at +0x14..+0x24).
// Finding that object once gives telemetry AND an apply target without any
// code patching.
// ---------------------------------------------------------------------------
pub static DATA_ADDR: AtomicUsize = AtomicUsize::new(0);
static CANDIDATES: RwLock<Vec<usize>> = RwLock::new(Vec::new());
static LIVE_IDENTIFIED: AtomicBool = AtomicBool::new(false);

static BASE_ZOOM: AtomicU32 = AtomicU32::new(0x7fc00000); // f32::NAN
static BASE_HEIGHT: AtomicU32 = AtomicU32::new(0x7fc00000);
static BASE_ANGLE: AtomicU32 = AtomicU32::new(0x7fc00000);
static BASE_FOV: AtomicU32 = AtomicU32::new(0x7fc00000);

static LAST_APPLIED_ZOOM: AtomicU32 = AtomicU32::new(0x7fc00000);
static LAST_APPLIED_HEIGHT: AtomicU32 = AtomicU32::new(0x7fc00000);
static LAST_APPLIED_ANGLE: AtomicU32 = AtomicU32::new(0x7fc00000);
static LAST_APPLIED_FOV: AtomicU32 = AtomicU32::new(0x7fc00000);

pub fn reset_applied_state() {
    BASE_ZOOM.store(f32::NAN.to_bits(), Ordering::Relaxed);
    BASE_HEIGHT.store(f32::NAN.to_bits(), Ordering::Relaxed);
    BASE_ANGLE.store(f32::NAN.to_bits(), Ordering::Relaxed);
    BASE_FOV.store(f32::NAN.to_bits(), Ordering::Relaxed);
    LAST_APPLIED_ZOOM.store(f32::NAN.to_bits(), Ordering::Relaxed);
    LAST_APPLIED_HEIGHT.store(f32::NAN.to_bits(), Ordering::Relaxed);
    LAST_APPLIED_ANGLE.store(f32::NAN.to_bits(), Ordering::Relaxed);
    LAST_APPLIED_FOV.store(f32::NAN.to_bits(), Ordering::Relaxed);
}

fn resolve_baseline(current: f32, last_applied: &AtomicU32, base: &AtomicU32) -> f32 {
    let applied = f32::from_bits(last_applied.load(Ordering::Relaxed));
    let stored_base = f32::from_bits(base.load(Ordering::Relaxed));
    if stored_base.is_nan() || (!applied.is_nan() && (current - applied).abs() > 0.001) {
        base.store(current.to_bits(), Ordering::Relaxed);
        current
    } else {
        stored_base
    }
}

/// Dual-range scaling logic:
/// - Zoom: if cfg.zoom < 10.0 and cur_zoom >= 10.0, relative multiplier (cur_zoom * cfg.zoom) clamped to 10.0..=300.0.
///   If cfg.zoom >= 10.0, native absolute clamped to 10.0..=300.0.
///   If cur_zoom < 10.0, clamped to 0.1..=10.0.
/// - Height: if cfg.height < 10.0 and cur_height >= 10.0, relative multiplier (cur_height * cfg.height) clamped to 10.0..=400.0.
///   If cfg.height >= 10.0, native absolute clamped to 10.0..=400.0.
///   If cur_height < 10.0, clamped to 0.1..=10.0.
/// - Angle: supports offset/multiplier (-1.0..=1.0) and native degrees (-180.0..=180.0).
///   If cfg.angle.abs() > 1.0, clamped to -180.0..=180.0.
///   If cur_angle.abs() >= 10.0, relative offset (cur_angle + cfg.angle) clamped to -180.0..=180.0.
///   Otherwise, clamped to -180.0..=180.0.
/// - FOV: extended range 0.5..=120.0 (game native uses ~3.0 at this offset).
pub fn apply_camera_scaling(
    cfg: &CameraConfig,
    cur_zoom: f32,
    cur_height: f32,
    cur_angle: f32,
    _cur_fov: f32,
) -> (f32, f32, f32, f32) {
    let new_zoom = if cfg.zoom >= 10.0 {
        cfg.zoom.clamp(10.0, 300.0)
    } else if cur_zoom >= 10.0 {
        (cur_zoom * cfg.zoom).clamp(10.0, 300.0)
    } else {
        cfg.zoom.clamp(0.1, 10.0)
    };

    let new_height = if cfg.height >= 10.0 {
        cfg.height.clamp(10.0, 400.0)
    } else if cur_height >= 10.0 {
        (cur_height * cfg.height).clamp(10.0, 400.0)
    } else {
        cfg.height.clamp(0.1, 10.0)
    };

    let new_angle = if cfg.angle.abs() > 1.0 {
        cfg.angle.clamp(-180.0, 180.0)
    } else if cur_angle.abs() >= 10.0 {
        (cur_angle + cfg.angle).clamp(-180.0, 180.0)
    } else {
        cfg.angle.clamp(-180.0, 180.0)
    };

    let new_fov = cfg.fov.clamp(0.5, 120.0);

    (new_zoom, new_height, new_angle, new_fov)
}

fn plausible_native(z: f32, h: f32, a: f32, f: f32) -> bool {
    (10.0..=300.0).contains(&z)
        && (10.0..=400.0).contains(&h)
        && (-180.0..=180.0).contains(&a)
        && (0.0..=89.0).contains(&f)
}

unsafe fn collect_config_candidates() -> Vec<usize> {
    use windows_sys::Win32::System::Memory::{
        VirtualQuery, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_GUARD, PAGE_NOACCESS,
        PAGE_READWRITE, PAGE_EXECUTE_READWRITE, PAGE_WRITECOPY, PAGE_EXECUTE_WRITECOPY,
    };
    let mut out = Vec::new();
    let mut address = 0x10000usize;
    const MAX_ADDR: usize = 0x7FFFFFFEFFFF;
    let mut budget: usize = 900 * 1024 * 1024; // 900 MB scanned per pass

    while address < MAX_ADDR && budget > 0 {
        let mut mbi: MEMORY_BASIC_INFORMATION = std::mem::zeroed();
        if VirtualQuery(address as *const _, &mut mbi, std::mem::size_of::<MEMORY_BASIC_INFORMATION>()) == 0 {
            break;
        }
        let base = mbi.BaseAddress as usize;
        let size = mbi.RegionSize as usize;
        let next = base.saturating_add(size);
        if next <= address {
            break;
        }
        let readable = mbi.State == MEM_COMMIT
            && mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS) == 0
            && mbi.Protect
                & (PAGE_READWRITE
                    | PAGE_WRITECOPY
                    | PAGE_EXECUTE_READWRITE
                    | PAGE_EXECUTE_WRITECOPY)
                != 0;
        if readable && size <= 96 * 1024 * 1024 && size <= budget {
            let mut buf = vec![0u8; size];
            let ok = std::ptr::copy_nonoverlapping(base as *const u8, buf.as_mut_ptr(), size);
            let _ = ok;
            // Pattern: flag byte == 1, four plausible floats at +0x14.
            let mut i = 0usize;
            while i + 0x24 <= size {
                if buf[i] == 1 {
                    let z = f32::from_bits(u32::from_le_bytes(buf[i+0x14..i+0x18].try_into().unwrap()));
                    let h = f32::from_bits(u32::from_le_bytes(buf[i+0x18..i+0x1C].try_into().unwrap()));
                    let a = f32::from_bits(u32::from_le_bytes(buf[i+0x1C..i+0x20].try_into().unwrap()));
                    let f = f32::from_bits(u32::from_le_bytes(buf[i+0x20..i+0x24].try_into().unwrap()));
                    if plausible_native(z, h, a, f) {
                        out.push(base + i);
                        if out.len() >= 4096 {
                            return out;
                        }
                    }
                }
                i += 4;
            }
            budget -= size;
        }
        address = next;
    }
    out
}

fn read_config_at(addr: usize) -> Option<(f32, f32, f32, f32, u8)> {
    unsafe {
        let z = *((addr + 0x14) as *const f32);
        let h = *((addr + 0x18) as *const f32);
        let a = *((addr + 0x1C) as *const f32);
        let f = *((addr + 0x20) as *const f32);
        let flag = *(addr as *const u8);
        if !(z.is_finite() && h.is_finite() && a.is_finite() && f.is_finite()) {
            return None;
        }
        Some((z, h, a, f, flag))
    }
}

/// Background: find a stable config object, then poll it into LAST_GAME_* so
/// the OSD/F9/markers work regardless of the code hook. Retries until found.
pub fn spawn_data_scanner() {
    thread::spawn(|| {
        let mut attempt: u32 = 0;
        loop {
            attempt += 1;
            crate::log_msg(&format!("[CAMERA SCAN] pass A (attempt {attempt})…"));
            let cands_a = unsafe { collect_config_candidates() };
            thread::sleep(Duration::from_millis(2000));
            let cands_b = unsafe { collect_config_candidates() };
            let set_b: std::collections::HashSet<usize> = cands_b.iter().copied().collect();

            // Stable = present in both passes with identical 17-byte payload.
            let mut stable: Vec<usize> = cands_a
                .into_iter()
                .filter(|addr| {
                    set_b.contains(addr) &&
                    match (read_config_at(*addr), read_config_at(*addr)) {
                        (Some(x), Some(y)) => x == y,
                        _ => false,
                    }
                })
                .collect();
            stable.sort_unstable();
            stable.dedup();

            if stable.is_empty() {
                crate::log_msg("[CAMERA SCAN] no stable candidate yet; rescanning in 10s…");
                thread::sleep(Duration::from_secs(10));
                continue;
            }

            for addr in stable.iter().take(6) {
                if let Some((z, h, a, f, flag)) = read_config_at(*addr) {
                    crate::log_msg(&format!(
                        "[CAMERA SCAN] candidate 0x{addr:X}: zoom={z:.2} height={h:.2} angle={a:.2} fov={f:.2} flag={flag:#04x}"
                    ));
                }
            }

            if let Ok(mut guard) = CANDIDATES.write() {
                *guard = stable.clone();
            }
            if let Some((z, h, a, f, flag)) = read_config_at(stable[0]) {
                store_game_values(z, h, a, f, flag, stable[0]);
            }
            DATA_ADDR.store(stable[0], Ordering::SeqCst);
            crate::log_msg(&format!(
                "[CAMERA SCAN] {} stable candidates; watching ALL for changes (move an in-game slider!).",
                stable.len()
            ));

            // Watch-all poller: track every candidate; a change confirmed on the
            // next tick identifies the REAL config object and locks telemetry to it.
            use std::collections::{HashMap, HashSet};
            let mut prev: HashMap<usize, [u32; 4]> = HashMap::new();
            let mut pending: HashMap<usize, [u32; 4]> = HashMap::new();
            let mut last_log: HashMap<usize, Instant> = HashMap::new();

            loop {
                thread::sleep(Duration::from_millis(250));

                // Confirm pending changes: value must persist across one tick.
                for (addr, newq) in pending.drain() {
                    match read_config_at(addr) {
                        Some((z, h, a, f, _flag)) => {
                            let cur = [z.to_bits(), h.to_bits(), a.to_bits(), f.to_bits()];
                            if cur == newq {
                                // Real change confirmed.
                                let names = ["zoom", "height", "angle", "fov"];
                                let mut parts = Vec::new();
                                if let Some(oldq) = prev.get(&addr) {
                                    for i in 0..4 {
                                        let o = f32::from_bits(oldq[i]);
                                        let nv = f32::from_bits(newq[i]);
                                        if (o - nv).abs() > f32::EPSILON {
                                            parts.push(format!("{} {:.2}→{:.2}", names[i], o, nv));
                                        }
                                    }
                                }
                                let now = Instant::now();
                                let throttled = last_log.get(&addr).map(|t| now.duration_since(*t).as_millis() < 900).unwrap_or(false);
                                if !throttled {
                                    let diff_text = if parts.is_empty() {
                                        "(values settled)".to_string()
                                    } else {
                                        parts.join("  ")
                                    };
                                    crate::log_msg(&format!(
                                        "[CAMERA WATCH] 0x{addr:X} CHANGED: {diff_text}"
                                    ));
                                    last_log.insert(addr, now);
                                }
                                prev.insert(addr, newq);
                                if !LIVE_IDENTIFIED.swap(true, Ordering::SeqCst) {
                                    DATA_ADDR.store(addr, Ordering::SeqCst);
                                    crate::log_msg(&format!(
                                        "[CAMERA SCAN] live config object identified: 0x{addr:X} — OSD/F9 now track it."
                                    ));
                                }
                            } else {
                                // Transient flicker: adopt current as baseline.
                                prev.insert(addr, cur);
                            }
                        }
                        None => {
                            prev.remove(&addr);
                        }
                    }
                }

                // Detect new changes across all candidates.
                let cands = CANDIDATES.read().map(|g| g.clone()).unwrap_or_default();
                let cand_set: HashSet<usize> = cands.iter().copied().collect();
                for addr in &cands {
                    match read_config_at(*addr) {
                        Some((z, h, a, f, _flag)) => {
                            let q = [z.to_bits(), h.to_bits(), a.to_bits(), f.to_bits()];
                            match prev.get(addr) {
                                None => {
                                    prev.insert(*addr, q);
                                }
                                Some(old) if *old != q => {
                                    pending.insert(*addr, q);
                                }
                                _ => {}
                            }
                        }
                        None => {
                            prev.remove(addr);
                        }
                    }
                }
                prev.retain(|addr, _| cand_set.contains(addr));

                // Feed OSD/F9 from the currently identified source and continuously enforce values if in Apply mode.
                let da = DATA_ADDR.load(Ordering::Relaxed);
                if da == 0 {
                    crate::log_msg("[CAMERA SCAN] source lost; rescanning…");
                    break;
                }
                match read_config_at(da) {
                    Some((z, h, a, f, flag)) => {
                        let cfg = match CAMERA_STATE.read() {
                            Ok(c) => *c,
                            Err(_) => CameraConfig::default(),
                        };

                        if cfg.enabled && cfg.mode == CameraMode::Apply && da >= 0x10000 {
                            let base_z = resolve_baseline(z, &LAST_APPLIED_ZOOM, &BASE_ZOOM);
                            let base_h = resolve_baseline(h, &LAST_APPLIED_HEIGHT, &BASE_HEIGHT);
                            let base_a = resolve_baseline(a, &LAST_APPLIED_ANGLE, &BASE_ANGLE);
                            let base_f = resolve_baseline(f, &LAST_APPLIED_FOV, &BASE_FOV);

                            let (nz, nh, na, nf) =
                                apply_camera_scaling(&cfg, base_z, base_h, base_a, base_f);

                            LAST_APPLIED_ZOOM.store(nz.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_HEIGHT.store(nh.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_ANGLE.store(na.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_FOV.store(nf.to_bits(), Ordering::Relaxed);

                            unsafe {
                                *((da + 0x14) as *mut f32) = nz;
                                *((da + 0x18) as *mut f32) = nh;
                                *((da + 0x1C) as *mut f32) = na;
                                *((da + 0x20) as *mut f32) = nf;
                            }

                            store_game_values(nz, nh, na, nf, flag, da);

                            // Sync watch tracker so continuous writes are not flagged as external game changes
                            let q = [nz.to_bits(), nh.to_bits(), na.to_bits(), nf.to_bits()];
                            prev.insert(da, q);
                        } else {
                            // Telemetry mode: track game baseline
                            BASE_ZOOM.store(z.to_bits(), Ordering::Relaxed);
                            BASE_HEIGHT.store(h.to_bits(), Ordering::Relaxed);
                            BASE_ANGLE.store(a.to_bits(), Ordering::Relaxed);
                            BASE_FOV.store(f.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_ZOOM.store(f32::NAN.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_HEIGHT.store(f32::NAN.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_ANGLE.store(f32::NAN.to_bits(), Ordering::Relaxed);
                            LAST_APPLIED_FOV.store(f32::NAN.to_bits(), Ordering::Relaxed);

                            store_game_values(z, h, a, f, flag, da);
                        }
                        DETOUR_CALL_COUNT.fetch_add(1, Ordering::Relaxed);
                    }
                    None => {
                        DATA_ADDR.store(0, Ordering::Relaxed);
                        LIVE_IDENTIFIED.store(false, Ordering::SeqCst);
                        crate::log_msg("[CAMERA SCAN] data source unreadable; rescanning…");
                        break;
                    }
                }
            }
        }
    });
}

/// F10 helper: snapshot the live PesCameraComponent memory to a timestamped
/// .bin next to the DLL. Dump in two different states and diff them offline to
/// locate position/rotation fields for freecam.
pub fn dump_last_component() -> Option<PathBuf> {
    let comp = LAST_GAME_COMP.load(Ordering::Relaxed);
    if comp < 0x10000 {
        return None;
    }
    let result = std::panic::catch_unwind(|| unsafe {
        let mut bytes = vec![0u8; COMPONENT_DUMP_LEN];
        std::ptr::copy_nonoverlapping(comp as *const u8, bytes.as_mut_ptr(), COMPONENT_DUMP_LEN);
        bytes
    });
    let bytes = result.ok()?;
    let dir = crate::logger::dll_dir().join("camera_dumps");
    std::fs::create_dir_all(&dir).ok()?;
    let ts = chrono::Local::now().format("%Y%m%d_%H%M%S%.3f");
    let path = dir.join(format!("comp_{comp:016X}_{ts}.bin"));
    std::fs::write(&path, &bytes).ok()?;
    Some(path)
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub enum CameraMode {
    /// Read + log only. Never writes into game memory.
    Telemetry,
    /// Writes configured values into the camera component.
    Apply,
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct CameraConfig {
    pub enabled: bool,
    pub zoom: f32,
    pub height: f32,
    pub angle: f32,
    pub fov: f32,
    pub freecam_speed: f32,
    pub mode: CameraMode,
    pub legacy_hooks: bool,
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
            mode: CameraMode::Telemetry,
            legacy_hooks: false,
        }
    }
}

pub static CAMERA_STATE: RwLock<CameraConfig> = RwLock::new(CameraConfig {
    enabled: true,
    zoom: 0.82,
    height: 1.32,
    angle: -0.12,
    fov: 50.0,
    freecam_speed: 2.5,
    mode: CameraMode::Telemetry,
    legacy_hooks: false,
});

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
                        "mode" => {
                            cfg.mode = if val.eq_ignore_ascii_case("apply") {
                                CameraMode::Apply
                            } else {
                                CameraMode::Telemetry
                            };
                        }
                        "legacy_hooks" => {
                            cfg.legacy_hooks = val == "1" || val.eq_ignore_ascii_case("true");
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
        let step = if cfg.zoom >= 10.0 { delta * 15.0 } else { delta };
        cfg.zoom = if cfg.zoom >= 10.0 {
            (cfg.zoom + step).clamp(10.0, 300.0)
        } else {
            (cfg.zoom + step).clamp(0.1, 10.0)
        };
        let fov_step = if cfg.fov < 10.0 { delta * 2.0 } else { delta * 25.0 };
        cfg.fov = (cfg.fov + fov_step).clamp(0.5, 120.0);
        crate::log_msg(&format!(
            ">>> Live Zoom Adjusted: {:.2} (FOV: {:.1})",
            cfg.zoom, cfg.fov
        ));
    }
}

pub fn adjust_height(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        let step = if cfg.height >= 10.0 { delta * 15.0 } else { delta };
        cfg.height = if cfg.height >= 10.0 {
            (cfg.height + step).clamp(10.0, 400.0)
        } else {
            (cfg.height + step).clamp(0.1, 10.0)
        };
        crate::log_msg(&format!(">>> Live Height Adjusted: {:.2}", cfg.height));
    }
}

pub fn adjust_angle(delta: f32) {
    if let Ok(mut cfg) = CAMERA_STATE.write() {
        let step = if cfg.angle.abs() >= 10.0 { delta * 10.0 } else { delta };
        cfg.angle = if cfg.angle.abs() >= 10.0 {
            (cfg.angle + step).clamp(-180.0, 180.0)
        } else {
            (cfg.angle + step).clamp(-1.0, 1.0)
        };
        crate::log_msg(&format!(">>> Live Angle Adjusted: {:.2}", cfg.angle));
    }
}

/// PesCamera detour: receives the live camera component pointer (rsi) from the
/// trampoline right before the game loads the four camera parameters.
/// Telemetry mode only reads and logs; Apply mode writes the configured values
/// so the original (hooked) load instructions pick them up.
#[no_mangle]
pub unsafe extern "C" fn sider_pes_camera_detour(component_ptr: usize) {
    let _ = std::panic::catch_unwind(|| pes_camera_detour_inner(component_ptr));
}

fn pes_camera_detour_inner(component_ptr: usize) {
    // A real component pointer lives in heap/module memory, never in the first 64KB.
    if component_ptr < 0x10000 {
        if !NULL_PTR_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] Ignoring invalid PesCamera pointer 0x{:X}",
                component_ptr
            ));
        }
        return;
    }

    let calls = DETOUR_CALL_COUNT.fetch_add(1, Ordering::Relaxed) + 1;

    unsafe {
        let zoom = (component_ptr + PC_ZOOM_OFF) as *const f32;
        let height = (component_ptr + PC_HEIGHT_OFF) as *const f32;
        let angle = (component_ptr + PC_ANGLE_OFF) as *const f32;
        let fov = (component_ptr + PC_FOV_OFF) as *const f32;
        let mode_flag = (component_ptr + PC_MODE_FLAG_OFF) as *const u8;

        let (cur_zoom, cur_height, cur_angle, cur_fov, cur_flag) =
            (*zoom, *height, *angle, *fov, *mode_flag);

        if !(cur_zoom.is_finite()
            && cur_height.is_finite()
            && cur_angle.is_finite()
            && cur_fov.is_finite())
        {
            // Fired but garbage: make it VISIBLE instead of silently returning,
            // otherwise a dead-wrong offsets assumption looks identical to a
            // never-executing hook.
            static IMPLAUSIBLE_LOGGED: AtomicBool = AtomicBool::new(false);
            if !IMPLAUSIBLE_LOGGED.swap(true, Ordering::Relaxed) {
                crate::log_msg(&format!(
                    "[CAMERA DETOUR] fired with implausible floats (z={:.3e} h={:.3e} a={:.3e} f={:.3e}) at comp=0x{:X}; ignoring.",
                    cur_zoom, cur_height, cur_angle, cur_fov, component_ptr
                ));
            }
            return;
        }

        store_game_values(cur_zoom, cur_height, cur_angle, cur_fov, cur_flag, component_ptr);

        let cfg = match CAMERA_STATE.read() {
            Ok(c) => *c,
            Err(_) => return,
        };
        if !cfg.enabled {
            return;
        }

        // Frequent enough to catch rare camera transitions (kickoff, replay,
        // camera switch) during a session, cheap enough not to flood the log.
        let telemetry_line = calls <= 50 || calls % 200 == 0;
        if telemetry_line {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] PesCamera call #{} comp=0x{:X} mode_flag=0x{:02X} zoom={:.3} height={:.3} angle={:.3} fov={:.1}",
                calls, component_ptr, cur_flag, cur_zoom, cur_height, cur_angle, cur_fov
            ));
        }

        if cfg.mode != CameraMode::Apply {
            BASE_ZOOM.store(cur_zoom.to_bits(), Ordering::Relaxed);
            BASE_HEIGHT.store(cur_height.to_bits(), Ordering::Relaxed);
            BASE_ANGLE.store(cur_angle.to_bits(), Ordering::Relaxed);
            BASE_FOV.store(cur_fov.to_bits(), Ordering::Relaxed);
            LAST_APPLIED_ZOOM.store(f32::NAN.to_bits(), Ordering::Relaxed);
            LAST_APPLIED_HEIGHT.store(f32::NAN.to_bits(), Ordering::Relaxed);
            LAST_APPLIED_ANGLE.store(f32::NAN.to_bits(), Ordering::Relaxed);
            LAST_APPLIED_FOV.store(f32::NAN.to_bits(), Ordering::Relaxed);
            return;
        }

        let base_zoom = resolve_baseline(cur_zoom, &LAST_APPLIED_ZOOM, &BASE_ZOOM);
        let base_height = resolve_baseline(cur_height, &LAST_APPLIED_HEIGHT, &BASE_HEIGHT);
        let base_angle = resolve_baseline(cur_angle, &LAST_APPLIED_ANGLE, &BASE_ANGLE);
        let base_fov = resolve_baseline(cur_fov, &LAST_APPLIED_FOV, &BASE_FOV);

        let (new_zoom, new_height, new_angle, new_fov) =
            apply_camera_scaling(&cfg, base_zoom, base_height, base_angle, base_fov);

        LAST_APPLIED_ZOOM.store(new_zoom.to_bits(), Ordering::Relaxed);
        LAST_APPLIED_HEIGHT.store(new_height.to_bits(), Ordering::Relaxed);
        LAST_APPLIED_ANGLE.store(new_angle.to_bits(), Ordering::Relaxed);
        LAST_APPLIED_FOV.store(new_fov.to_bits(), Ordering::Relaxed);

        static APPLY_UNITS_WARNED: AtomicBool = AtomicBool::new(false);
        if !APPLY_UNITS_WARNED.swap(true, Ordering::Relaxed) && cfg.zoom < 10.0 && base_zoom >= 10.0 {
            crate::log_msg(&format!(
                "[CAMERA APPLY] INFO: sider.ini zoom={:.2} (< 10.0) treated as relative multiplier on game native zoom~{:.1} -> applied {:.2}",
                cfg.zoom, base_zoom, new_zoom
            ));
        }

        // Component-site write (only matters when this path executes)…
        *(zoom as *mut f32) = new_zoom;
        *(height as *mut f32) = new_height;
        *(angle as *mut f32) = new_angle;
        *(fov as *mut f32) = new_fov;

        // …and Plan B: write into the global config object so transitions
        // consume our values even when the code hook stays silent.
        let data_addr = DATA_ADDR.load(Ordering::Relaxed);
        if data_addr >= 0x10000 {
            // Already inside the detour's unsafe block.
            *((data_addr + 0x14) as *mut f32) = new_zoom;
            *((data_addr + 0x18) as *mut f32) = new_height;
            *((data_addr + 0x1C) as *mut f32) = new_angle;
            *((data_addr + 0x20) as *mut f32) = new_fov;
        }

        store_game_values(new_zoom, new_height, new_angle, new_fov, cur_flag, component_ptr);

        if telemetry_line {
            crate::log_msg(&format!(
                "[CAMERA DETOUR] Applied to comp=0x{:X}: zoom={:.3} height={:.3} angle={:.3} fov={:.1}",
                component_ptr, new_zoom, new_height, new_angle, new_fov
            ));
        }
    }
}

/// Legacy detour kept for the disabled legacy hooks. Unverified on current
/// builds: it fired only at init time with a bogus pointer.
#[no_mangle]
pub unsafe extern "C" fn sider_ue4_camera_view_detour(view_info_ptr: usize) {
    let _ = std::panic::catch_unwind(|| legacy_view_detour_inner(view_info_ptr));
}

fn legacy_view_detour_inner(view_info_ptr: usize) {
    if view_info_ptr < 0x10000 {
        if !NULL_PTR_LOGGED.swap(true, Ordering::Relaxed) {
            crate::log_msg("[CAMERA DETOUR] Warning: Received invalid view info pointer.");
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

        unsafe {
            // FMinimalViewInfo struct offsets (legacy assumption):
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

            if !(orig_fov.is_finite() && orig_z.is_finite() && orig_pitch.is_finite()) {
                return;
            }

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

            if calls <= 3 {
                crate::log_msg(&format!(
                    "[CAMERA DETOUR] Legacy view call #{} ptr=0x{:X} FOV: {:.1}->{:.1} Height: {:.1}->{:.1}",
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

// Integrity watchdog state: where the hook lives and what the original bytes
// were, so a background thread can detect the game restoring its own code.
static TARGET_ADDR: AtomicUsize = AtomicUsize::new(0);
static PATCH_ORIGINAL: RwLock<Vec<u8>> = RwLock::new(Vec::new());
static REINSTALL_COUNT: AtomicUsize = AtomicUsize::new(0);

fn current_patch_bytes(target: usize) -> Vec<u8> {
    unsafe { std::slice::from_raw_parts(target as *const u8, PES_CAMERA_HOOK_LEN).to_vec() }
}

/// Watches the patched site: if the game restores its code (integrity check),
/// logs it loudly and re-installs the detour so telemetry/apply keep working.
fn spawn_patch_watchdog(detour_addr: usize) {
    thread::spawn(move || loop {
        thread::sleep(Duration::from_secs(5));
        let target = TARGET_ADDR.load(Ordering::Relaxed);
        if target < 0x10000 {
            continue;
        }
        let current = current_patch_bytes(target);
        let still_ours = current.len() >= 2 && current[0] == 0xFF && current[1] == 0x25;
        if still_ours {
            continue; // patch intact
        }
        // Anything that is not our jmp (original movss sequence or other code)
        // means the site changed under us: re-install.
        let n = REINSTALL_COUNT.fetch_add(1, Ordering::SeqCst) + 1;
        crate::log_msg(&format!(
            "[CAMERA WATCHDOG] patch lost at 0x{:X} (game restored/changed code); re-installing detour #{n}",
            target
        ));
        let ok = unsafe {
            build_and_install_trampoline(
                target,
                PES_CAMERA_HOOK_LEN,
                detour_addr,
                Some(&[0x48, 0x89, 0xF1]),
            )
        };
        if ok {
            crate::log_msg("[CAMERA WATCHDOG] re-installed successfully.");
        } else {
            crate::log_msg("[CAMERA WATCHDOG] re-install FAILED (VirtualProtect/VirtualAlloc?).");
        }
    });
}

pub fn get_camera_active_mode_name() -> &'static str {
    match CAMERA_MODE_STATUS.load(Ordering::Relaxed) {
        CAMERA_MODE_UE4_HOOK => "UE4_HOOK",
        CAMERA_MODE_FALLBACK => "FALLBACK",
        _ => "UNINITIALIZED",
    }
}

/// Builds and installs a relocating inline trampoline at `target_addr`:
/// saves flags/GPRs/xmm0-5, aligns RSP to 16 (Windows x64 ABI), optionally moves
/// a source register into rcx, calls `detour_addr`, restores everything, executes
/// the original `orig_len` bytes and jumps back to `target_addr + orig_len`.
///
/// # Safety
/// `target_addr` must point at executable memory containing `orig_len` complete,
/// RIP-relative-free instructions; no other thread may execute those bytes while
/// the patch is written (installation happens during game loading).
unsafe fn build_and_install_trampoline(
    target_addr: usize,
    orig_len: usize,
    detour_addr: usize,
    pre_call_mov: Option<&[u8]>,
) -> bool {
    let tramp = VirtualAlloc(
        std::ptr::null(),
        256,
        MEM_COMMIT | MEM_RESERVE,
        PAGE_EXECUTE_READWRITE,
    ) as *mut u8;
    if tramp.is_null() {
        return false;
    }

    let ret_addr = target_addr + orig_len;

    let mut code: Vec<u8> = Vec::with_capacity(200);
    code.push(0x9C); // pushfq
    code.extend_from_slice(&[0x50, 0x51, 0x52, 0x53, 0x55, 0x56, 0x57]); // push rax,rcx,rdx,rbx,rbp,rsi,rdi
    code.extend_from_slice(&[0x41, 0x50, 0x41, 0x51, 0x41, 0x52, 0x41, 0x53]); // push r8-r11
    code.extend_from_slice(&[0x48, 0x89, 0xE0]); // mov rax, rsp (pre-aligned)
    code.extend_from_slice(&[0x48, 0x83, 0xE4, 0xF0]); // and rsp, -16
    code.extend_from_slice(&[0x48, 0x81, 0xEC, 0xA0, 0x00, 0x00, 0x00]); // sub rsp, 0xA0
    code.extend_from_slice(&[0x48, 0x89, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00]); // mov [rsp+0x80], rax

    // Save XMM0-XMM5 with unaligned movups
    code.extend_from_slice(&[0x0F, 0x11, 0x44, 0x24, 0x20]); // movups [rsp+0x20], xmm0
    code.extend_from_slice(&[0x0F, 0x11, 0x4C, 0x24, 0x30]); // movups [rsp+0x30], xmm1
    code.extend_from_slice(&[0x0F, 0x11, 0x54, 0x24, 0x40]); // movups [rsp+0x40], xmm2
    code.extend_from_slice(&[0x0F, 0x11, 0x5C, 0x24, 0x50]); // movups [rsp+0x50], xmm3
    code.extend_from_slice(&[0x0F, 0x11, 0x64, 0x24, 0x60]); // movups [rsp+0x60], xmm4
    code.extend_from_slice(&[0x0F, 0x11, 0x6C, 0x24, 0x70]); // movups [rsp+0x70], xmm5

    if let Some(pre) = pre_call_mov {
        code.extend_from_slice(pre);
    }

    code.extend_from_slice(&[0x48, 0xB8]); // mov rax, detour_addr
    code.extend_from_slice(&detour_addr.to_le_bytes());
    code.extend_from_slice(&[0xFF, 0xD0]); // call rax

    // Restore XMM0-XMM5
    code.extend_from_slice(&[0x0F, 0x10, 0x44, 0x24, 0x20]);
    code.extend_from_slice(&[0x0F, 0x10, 0x4C, 0x24, 0x30]);
    code.extend_from_slice(&[0x0F, 0x10, 0x54, 0x24, 0x40]);
    code.extend_from_slice(&[0x0F, 0x10, 0x5C, 0x24, 0x50]);
    code.extend_from_slice(&[0x0F, 0x10, 0x64, 0x24, 0x60]);
    code.extend_from_slice(&[0x0F, 0x10, 0x6C, 0x24, 0x70]);

    code.extend_from_slice(&[0x48, 0x8B, 0x84, 0x24, 0x80, 0x00, 0x00, 0x00]); // mov rax, [rsp+0x80]
    code.extend_from_slice(&[0x48, 0x89, 0xC4]); // mov rsp, rax (undo alignment + frame)
    code.extend_from_slice(&[0x41, 0x5B, 0x41, 0x5A, 0x41, 0x59, 0x41, 0x58]); // pop r11-r8
    code.extend_from_slice(&[0x5F, 0x5E, 0x5D, 0x5B, 0x5A, 0x59, 0x58]); // pop rdi,rsi,rbp,rbx,rdx,rcx,rax
    code.push(0x9D); // popfq

    // Execute the original (relocated) instruction bytes
    code.extend_from_slice(std::slice::from_raw_parts(target_addr as *const u8, orig_len));

    // Jump back
    code.extend_from_slice(&[0xFF, 0x25, 0x00, 0x00, 0x00, 0x00]);
    code.extend_from_slice(&ret_addr.to_le_bytes());

    if code.len() > 256 {
        return false;
    }
    std::ptr::copy_nonoverlapping(code.as_ptr(), tramp, code.len());

    let mut old_protect = 0;
    if VirtualProtect(target_addr as _, orig_len, PAGE_EXECUTE_READWRITE, &mut old_protect) == 0 {
        return false;
    }

    // jmp qword ptr [rip+0] + absolute address, padded with NOPs to orig_len
    let mut jmp_bytes: Vec<u8> = vec![0xFF, 0x25, 0x00, 0x00, 0x00, 0x00];
    jmp_bytes.extend_from_slice(&(tramp as usize).to_le_bytes());
    while jmp_bytes.len() < orig_len {
        jmp_bytes.push(0x90);
    }
    std::ptr::copy_nonoverlapping(jmp_bytes.as_ptr(), target_addr as *mut u8, orig_len);
    VirtualProtect(target_addr as _, orig_len, old_protect, &mut old_protect);
    true
}

pub fn install_camera_hooks() -> usize {
    unsafe {
        let base_module = windows_sys::Win32::System::LibraryLoader::GetModuleHandleA(std::ptr::null());
        if base_module == 0 {
            return 0;
        }
        let base_addr = base_module as usize;

        // Scan the .xcode section in memory (first 95 MB from base_addr)
        let mem_slice = std::slice::from_raw_parts(base_addr as *const u8, 0x059FC000);
        let mut installed = 0;

        let use_legacy = CAMERA_STATE
            .read()
            .map(|c| c.legacy_hooks)
            .unwrap_or(false);

        // Primary hook: PesCameraComponent parameter loads (rsi-based)
        let sig = crate::scanner::Signature::from_ida(PES_CAMERA_SIG);
        if let Some(offset) = crate::scanner::scan_pattern(mem_slice, &sig) {
            let target_addr = base_addr + offset;
            crate::log_msg(&format!(
                "[CAMERA] AOB pattern PES_CAMERA found at 0x{:X} (RVA 0x{:X})",
                target_addr, offset
            ));
            let detour_addr = sider_pes_camera_detour as *const () as usize;
            // mov rcx, rsi — pass the camera component pointer as first argument
            if build_and_install_trampoline(
                target_addr,
                PES_CAMERA_HOOK_LEN,
                detour_addr,
                Some(&[0x48, 0x89, 0xF1]),
            ) {
                installed += 1;
                crate::log_msg(&format!(
                    "[CAMERA HOOK PES] Installed PesCamera detour at 0x{:X}",
                    target_addr
                ));

                // Remember the site for the integrity watchdog.
                TARGET_ADDR.store(target_addr, Ordering::SeqCst);
                let original = std::slice::from_raw_parts(target_addr as *const u8, PES_CAMERA_HOOK_LEN);
                if let Ok(mut guard) = PATCH_ORIGINAL.write() {
                    *guard = original.to_vec();
                }

                // Read-back verification: prove the patch is really in memory.
                let readback = std::slice::from_raw_parts(target_addr as *const u8, 6);
                if readback == [0xFF, 0x25, 0x00, 0x00, 0x00, 0x00] {
                    crate::log_msg("[CAMERA HOOK PES] Read-back verified (jmp rip+0 present).");
                } else {
                    crate::log_msg("[CAMERA HOOK PES] WARNING: read-back mismatch right after install!");
                }
            }
        } else {
            crate::log_msg(
                "[CAMERA] PES_CAMERA signature not found in this build; camera hook disabled.",
            );
        }

        if use_legacy {
            let sig1 = crate::scanner::Signature::from_ida(UE4_CAMERA_SIG_1);
            if let Some(offset) = crate::scanner::scan_pattern(mem_slice, &sig1) {
                let target_addr = base_addr + offset;
                crate::log_msg(&format!(
                    "[CAMERA HOOK #1 LEGACY] Found signature at 0x{:X}",
                    target_addr
                ));
                let detour_addr = sider_ue4_camera_view_detour as *const () as usize;
                if build_and_install_trampoline(target_addr, LEGACY_HOOK_LEN, detour_addr, None) {
                    installed += 1;
                }
            }

            let sig2 = crate::scanner::Signature::from_ida(UE4_CAMERA_SIG_2);
            if let Some(offset) = crate::scanner::scan_pattern(mem_slice, &sig2) {
                let target_addr = base_addr + offset;
                crate::log_msg(&format!(
                    "[CAMERA HOOK #2 LEGACY] Found signature at 0x{:X}",
                    target_addr
                ));
                let detour_addr = sider_ue4_camera_view_detour as *const () as usize;
                // mov rcx, rbx — legacy site keeps the view pointer in rbx
                if build_and_install_trampoline(
                    target_addr,
                    LEGACY_HOOK_LEN,
                    detour_addr,
                    Some(&[0x48, 0x89, 0xD9]),
                ) {
                    installed += 1;
                }
            }
        }

        installed
    }
}

pub fn start_camera_hook(ini_path_opt: Option<PathBuf>) {
    thread::spawn(move || {
        crate::log_msg("=== PesCamera Controller Hook Engine Started ===");

        // Plan B telemetry: works even when the code path never executes.
        spawn_data_scanner();

        // Install well past the heavy boot phase: patching code the game may
        // execute during early loading caused startup races/crashes.
        thread::sleep(Duration::from_secs(10));

        let mut last_ini_mod_time = SystemTime::UNIX_EPOCH;

        if let Some(ref p) = ini_path_opt {
            load_camera_config_from_ini(p);
        }

        let hook_enabled = CAMERA_STATE.read().map(|c| c.enabled).unwrap_or(true);
        let count = if hook_enabled {
            install_camera_hooks()
        } else {
            crate::log_msg("[CAMERA HOOK] disabled by sider.ini ([camera] enabled = 0).");
            0
        };

        if count > 0 {
            CAMERA_MODE_STATUS.store(CAMERA_MODE_UE4_HOOK, Ordering::SeqCst);
            CAMERA_TARGETS_COUNT.store(count, Ordering::Relaxed);
            spawn_patch_watchdog(sider_pes_camera_detour as *const () as usize);
            let mode_name = CAMERA_STATE
                .read()
                .map(|c| match c.mode {
                    CameraMode::Apply => "apply",
                    CameraMode::Telemetry => "telemetry",
                })
                .unwrap_or("telemetry");
            crate::log_msg(&format!(
                "[CAMERA HOOK] Active with {} detour(s) in '{}' mode.",
                count, mode_name
            ));
        } else {
            CAMERA_MODE_STATUS.store(CAMERA_MODE_FALLBACK, Ordering::SeqCst);
            crate::log_msg("[CAMERA HOOK] No camera signature matched; camera features inactive.");
        }

        loop {
            if let Some(ref p) = ini_path_opt {
                if let Ok(meta) = std::fs::metadata(p) {
                    if let Ok(mod_time) = meta.modified() {
                        if mod_time > last_ini_mod_time {
                            last_ini_mod_time = mod_time;
                            load_camera_config_from_ini(p);
                            let mode_name = CAMERA_STATE
                                .read()
                                .map(|c| match c.mode {
                                    CameraMode::Apply => "apply",
                                    CameraMode::Telemetry => "telemetry",
                                })
                                .unwrap_or("telemetry");
                            crate::log_msg(&format!(
                                "sider.ini reload: Camera settings updated (mode={}).",
                                mode_name
                            ));
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
    use std::sync::Mutex;

    // CAMERA_STATE is global; serialize the tests that mutate it.
    static TEST_LOCK: Mutex<()> = Mutex::new(());

    fn set_test_cfg(cfg: CameraConfig) {
        reset_applied_state();
        if let Ok(mut c) = CAMERA_STATE.write() {
            *c = cfg;
        }
    }

    #[test]
    fn test_camera_config_defaults() {
        let cfg = CameraConfig::default();
        assert!(cfg.enabled);
        assert!((cfg.zoom - 0.82).abs() < 0.001);
        assert!((cfg.height - 1.32).abs() < 0.001);
        assert!((cfg.angle - (-0.12)).abs() < 0.001);
        assert!((cfg.fov - 50.0).abs() < 0.001);
        assert!((cfg.freecam_speed - 2.5).abs() < 0.001);
        assert_eq!(cfg.mode, CameraMode::Telemetry);
        assert!(!cfg.legacy_hooks);
    }

    #[test]
    fn test_pes_camera_detour_telemetry_does_not_write() {
        let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let mut buffer = vec![0u8; 0x2000];
        let ptr = buffer.as_mut_ptr() as usize;

        let mut cfg = CameraConfig::default();
        cfg.mode = CameraMode::Telemetry;
        cfg.zoom = 2.0;
        cfg.height = 2.0;
        cfg.angle = 0.5;
        cfg.fov = 75.0;
        set_test_cfg(cfg);

        unsafe {
            let zoom = (ptr + PC_ZOOM_OFF) as *mut f32;
            let fov = (ptr + PC_FOV_OFF) as *mut f32;
            *zoom = 1.0;
            *fov = 50.0;
            sider_pes_camera_detour(ptr);
            assert!((*zoom - 1.0).abs() < 0.0001, "telemetry must not write zoom");
            assert!((*fov - 50.0).abs() < 0.0001, "telemetry must not write fov");
        }
        set_test_cfg(CameraConfig::default());
    }

    #[test]
    fn test_pes_camera_detour_apply_writes_clamped_values() {
        let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let mut buffer = vec![0u8; 0x2000];
        let ptr = buffer.as_mut_ptr() as usize;

        // 1. Native absolute values and boundary clamping
        let mut cfg = CameraConfig::default();
        cfg.mode = CameraMode::Apply;
        cfg.zoom = 99.0;    // Native absolute (>= 10.0), clamped to 10.0..=300.0
        cfg.height = 125.0; // Native absolute (>= 10.0), clamped to 10.0..=400.0
        cfg.angle = 28.5;   // Native absolute (> 1.0), clamped to -180.0..=180.0
        cfg.fov = 3.0;      // Extended FOV range (native game uses ~3.0)
        set_test_cfg(cfg);

        unsafe {
            sider_pes_camera_detour(ptr);
            let zoom = *((ptr + PC_ZOOM_OFF) as *const f32);
            let height = *((ptr + PC_HEIGHT_OFF) as *const f32);
            let angle = *((ptr + PC_ANGLE_OFF) as *const f32);
            let fov = *((ptr + PC_FOV_OFF) as *const f32);
            assert!((zoom - 99.0).abs() < 0.0001, "native absolute zoom must be 99.0, got {}", zoom);
            assert!((height - 125.0).abs() < 0.0001, "native absolute height must be 125.0, got {}", height);
            assert!((angle - 28.5).abs() < 0.0001, "native absolute angle must be 28.5, got {}", angle);
            assert!((fov - 3.0).abs() < 0.0001, "native FOV must be 3.0, got {}", fov);
        }

        // 2. Out-of-bounds native values clamping
        let mut cfg_clamp = CameraConfig::default();
        cfg_clamp.mode = CameraMode::Apply;
        cfg_clamp.zoom = 350.0;  // clamps to 300.0
        cfg_clamp.height = 500.0; // clamps to 400.0
        cfg_clamp.angle = 200.0;  // clamps to 180.0
        cfg_clamp.fov = 0.1;      // clamps to 0.5
        set_test_cfg(cfg_clamp);

        unsafe {
            sider_pes_camera_detour(ptr);
            let zoom = *((ptr + PC_ZOOM_OFF) as *const f32);
            let height = *((ptr + PC_HEIGHT_OFF) as *const f32);
            let angle = *((ptr + PC_ANGLE_OFF) as *const f32);
            let fov = *((ptr + PC_FOV_OFF) as *const f32);
            assert!((zoom - 300.0).abs() < 0.0001, "zoom must clamp to 300.0, got {}", zoom);
            assert!((height - 400.0).abs() < 0.0001, "height must clamp to 400.0, got {}", height);
            assert!((angle - 180.0).abs() < 0.0001, "angle must clamp to 180.0, got {}", angle);
            assert!((fov - 0.5).abs() < 0.0001, "fov must clamp to 0.5, got {}", fov);
        }

        // 3. Relative multiplier and offset scaling on game native units
        unsafe {
            *((ptr + PC_ZOOM_OFF) as *mut f32) = 60.0;
            *((ptr + PC_HEIGHT_OFF) as *mut f32) = 80.0;
            *((ptr + PC_ANGLE_OFF) as *mut f32) = 28.0;
            *((ptr + PC_FOV_OFF) as *mut f32) = 3.0;
        }

        let mut cfg_rel = CameraConfig::default();
        cfg_rel.mode = CameraMode::Apply;
        cfg_rel.zoom = 0.5;   // < 10.0, on cur_zoom 60.0 >= 10.0 -> 60.0 * 0.5 = 30.0
        cfg_rel.height = 1.25; // < 10.0, on cur_height 80.0 >= 10.0 -> 80.0 * 1.25 = 100.0
        cfg_rel.angle = -0.5;  // in -1.0..=1.0, on cur_angle 28.0 >= 10.0 -> 28.0 + (-0.5) = 27.5
        cfg_rel.fov = 3.0;
        set_test_cfg(cfg_rel);

        unsafe {
            sider_pes_camera_detour(ptr);
            let zoom = *((ptr + PC_ZOOM_OFF) as *const f32);
            let height = *((ptr + PC_HEIGHT_OFF) as *const f32);
            let angle = *((ptr + PC_ANGLE_OFF) as *const f32);
            let fov = *((ptr + PC_FOV_OFF) as *const f32);
            assert!((zoom - 30.0).abs() < 0.0001, "relative zoom must be 30.0, got {}", zoom);
            assert!((height - 100.0).abs() < 0.0001, "relative height must be 100.0, got {}", height);
            assert!((angle - 27.5).abs() < 0.0001, "relative angle offset must be 27.5, got {}", angle);
            assert!((fov - 3.0).abs() < 0.0001, "fov must be 3.0, got {}", fov);
        }

        // 4. Clamping when cur_zoom < 10.0 and cfg.zoom < 10.0
        unsafe {
            *((ptr + PC_ZOOM_OFF) as *mut f32) = 1.0;
            *((ptr + PC_HEIGHT_OFF) as *mut f32) = 1.0;
            *((ptr + PC_ANGLE_OFF) as *mut f32) = 0.0;
            *((ptr + PC_FOV_OFF) as *mut f32) = 1.0;
        }
        let mut cfg_low = CameraConfig::default();
        cfg_low.mode = CameraMode::Apply;
        cfg_low.zoom = 0.05;   // clamps to 0.1
        cfg_low.height = 0.05; // clamps to 0.1
        cfg_low.angle = -0.25; // within -1.0..=1.0
        cfg_low.fov = 65.0;    // within 0.5..=120.0
        set_test_cfg(cfg_low);

        unsafe {
            sider_pes_camera_detour(ptr);
            let zoom = *((ptr + PC_ZOOM_OFF) as *const f32);
            let height = *((ptr + PC_HEIGHT_OFF) as *const f32);
            let angle = *((ptr + PC_ANGLE_OFF) as *const f32);
            let fov = *((ptr + PC_FOV_OFF) as *const f32);
            assert!((zoom - 0.1).abs() < 0.0001, "zoom must clamp to 0.1, got {}", zoom);
            assert!((height - 0.1).abs() < 0.0001, "height must clamp to 0.1, got {}", height);
            assert!((angle - (-0.25)).abs() < 0.0001, "angle must be -0.25, got {}", angle);
            assert!((fov - 65.0).abs() < 0.0001, "fov must be 65.0, got {}", fov);
        }

        // 5. Verification that detour writes to DATA_ADDR (Plan B) as well
        let mut data_buffer = vec![0u8; 0x100];
        let data_ptr = data_buffer.as_mut_ptr() as usize;
        DATA_ADDR.store(data_ptr, Ordering::SeqCst);

        unsafe {
            sider_pes_camera_detour(ptr);
            let d_zoom = *((data_ptr + 0x14) as *const f32);
            let d_height = *((data_ptr + 0x18) as *const f32);
            let d_angle = *((data_ptr + 0x1C) as *const f32);
            let d_fov = *((data_ptr + 0x20) as *const f32);
            assert!((d_zoom - 0.1).abs() < 0.0001);
            assert!((d_height - 0.1).abs() < 0.0001);
            assert!((d_angle - (-0.25)).abs() < 0.0001);
            assert!((d_fov - 65.0).abs() < 0.0001);
        }
        DATA_ADDR.store(0, Ordering::SeqCst);

        set_test_cfg(CameraConfig::default());
    }

    #[test]
    fn test_pes_camera_detour_rejects_invalid_pointer() {
        // Must not crash on null/low pointers.
        unsafe {
            sider_pes_camera_detour(0);
            sider_pes_camera_detour(0x10);
        }
    }

    #[test]
    fn test_ini_parses_mode_and_legacy_hooks() {
        let _guard = TEST_LOCK.lock().unwrap_or_else(|e| e.into_inner());
        let dir = std::env::temp_dir();
        let ini_path = dir.join("sider_camera_test.ini");
        std::fs::write(
            &ini_path,
            "[camera]\nenabled = 1\nzoom = 1.10\nmode = apply\nlegacy_hooks = 1\n",
        )
        .unwrap();
        load_camera_config_from_ini(&ini_path);
        if let Ok(cfg) = CAMERA_STATE.read() {
            assert_eq!(cfg.mode, CameraMode::Apply);
            assert!(cfg.legacy_hooks);
            assert!((cfg.zoom - 1.10).abs() < 0.001);
        } else {
            panic!("camera state poisoned");
        }
        let _ = std::fs::remove_file(&ini_path);
        set_test_cfg(CameraConfig::default());
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
