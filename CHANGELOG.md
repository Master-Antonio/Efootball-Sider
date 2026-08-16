# Changelog

All notable changes to the **eFootball Mod Studio** project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.0] - 2026-09-26

### Added
- **Project Rebranding to eFootball Mod Studio**: Transitioned identity from "eFootball Sider" to "eFootball Mod Studio" to accurately reflect modern Unreal Engine 4.26 IoStore package compilation, WESYS cryptography, and desktop workflow as distinct from classic Fox Engine memory-injection Sider. Backward-compatible aliases for `sider.ini` and legacy batch scripts preserved.
- **Dual-Range Camera Scaling Engine**: Smart adaptive scaling in `rust_sider/src/camera.rs` (`apply_camera_scaling`, `resolve_baseline`) that seamlessly supports both legacy relative multipliers (< 10.0) and game-native absolute coordinates (10.0..300.0 zoom, 10.0..400.0 height, -180.0..180.0 angle, 0.5..120.0 FOV) without clamping distortions.
- **Continuous Live Memory Injection**: The Plan B background scanner now forces and maintains configured camera values at 250ms polling intervals directly on `DATA_ADDR`, eliminating the need to wait for scene transitions.
- **One-Click Auto-Sync for IoStore Packages**: Integrated background compilation pipeline in `ZenBuilderService` and `PakModService` with UI buttons (`Sync All to ~mods`, `Auto-Build All Triplets`) and automatic staleness detection (*Needs Rebuild*, *Up to date*, *Not Built*).

### Fixed
- Eliminated restrictive 0.1..5.0 float clamp that previously crushed game-native camera units in `mode = apply`.
- Fixed hotkey step increments to proportionally scale according to active unit range.

### Removed
- **Obsolete Scratch & Legacy Scripts**: Removed redundant development scripts (`verify_gui.py`, `camera_diff.py`, `camera_dump_diff.py`), legacy `efootball_sider_gui.py` compatibility facade, and duplicate legacy batch scripts (`*Sider*.bat`) to maintain a clean, professional public repository structure.

---

## [1.1.0] - 2026-08-25

### Added
- **Plan B Memory Scanner**: Dynamic background worker in `rust_sider/src/camera.rs` scanning up to 900MB committed memory with two-pass verification to acquire the live `PesCameraComponent` config object independently of code detour invocation.
- **Self-Healing Watchdog**: Sentinel thread polling every 5 seconds to detect and re-apply the 34-byte trampoline hook if restored by game integrity routines.
- **Compact OSD HUD**: Streamlined single-row GDI overlay featuring double-buffered flicker-free rendering, rounded DWM corners, active status chip (`LIVE` / `ACTIVE` / `WAITING` / `OFFLINE`), live game-native float pairs with cyan/yellow flash animation (`COL_FLASH`) on change, and keyboard shortcuts (`Space`, `F1`, `+`, `-`, Numpad).
- **~mods IoStore Management**: Full support for UE4 cooked package deployment via Zen Triplets (`.pak`/`.utoc`/`.ucas`) and automated container enable/disable/delete management via `PakModService`.
- **F9 & F10 Telemetry**: In-game hotkey F9 to record timestamped telemetry markers and F10 to capture 0x1200 bytes raw component memory dumps for differential analysis.
- **Differential Analysis Tools**: Added `scripts/camera_diff.py` and `scripts/camera_dump_diff.py` for interactive camera mapping.

### Fixed
- Fixed race condition in `rust_sider/src/livecpk.rs` unit tests by introducing static test mutex synchronization.
- Fixed `FileNotFoundError` crash in `scripts/build_release.py` when optional `content/` folder is not present.
- Fixed deadlock in `MemoryDiscoveryService` by transitioning to re-entrant `threading.RLock`.
- Eliminated noise in memory asset discovery with token lookbehind filtering.

---

## [1.0.0] - 2026-08-20

### Added
- Initial modular PySide6 Sider Studio desktop interface with eight focused operational pages.
- Native DXGI proxy runtime (`dxgi.dll`) with thread-safe export forwarding outside loader lock.
- Dual-engine WESYS decryption/encryption in pure Python and native Rust C-ABI with XorShift128 keystream and dynamic size-derived seed.
- High-performance `dt870` live CPK extraction and validation for 392-byte and 400-byte `pesdb` database records.
- In-memory team replacement with case-insensitivity and null-padding.
- Win32 `CreateFileW` loose-file virtual file system (VFS).
- Automated CI workflow with multi-platform testing, Ruff linting, and deterministic release packaging.
