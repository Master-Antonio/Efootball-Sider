# ⚽ eFootball Sider by Toriga

<p align="center">
  <img src="https://img.shields.io/badge/Status-Active%20Production%20Ready-success?style=for-the-badge" alt="Status">
  <img src="https://img.shields.io/badge/eFootball-2024%20%7C%202025%20%7C%202026%20%7C%202027-0284c7?style=for-the-badge&logo=unrealengine&logoColor=white" alt="Game Support">
  <img src="https://img.shields.io/badge/Platform-Windows%20x64%20(Steam)-0078d7?style=for-the-badge&logo=windows&logoColor=white" alt="Platform">
  <img src="https://img.shields.io/badge/Language-Rust%20%7C%20Python%20%7C%20C%2B%2B-3776ab?style=for-the-badge" alt="Languages">
  <img src="https://img.shields.io/badge/License-GPL--3.0-emerald?style=for-the-badge" alt="License">
</p>

<p align="center">
  <b>The open-source, high-performance modding engine, live memory framework, and Broadcast Camera Suite for modern eFootball on PC.</b>
</p>

---

## 🌟 Overview

**eFootball Sider by Toriga** is a next-generation open-source modding engine and real-time research framework engineered specifically for **eFootball** on Windows (Steam / Microsoft Store).

Built as a lightweight, zero-latency DirectX 64-bit proxy DLL in **Rust** (`dxgi.dll`) and paired with an interactive 6-tab **Python Studio GUI**, Sider provides modders and players with a comprehensive suite of tools:
* **LiveCPK Engine**: Dynamically load loose files (textures, kits, stadiums, databases) without modifying original `.pak` archives, featuring 3-level VFS resolution (exact, suffix, and basename matching) with automatic `content/` fallback root indexing.
* **Broadcast Camera & FOV Master**: Real-time camera matrix manipulation (Zoom, Height, Lens Tilt, FOV, 3D Freecam) with in-game hot-reloading, inline AOB detour hooks, and automatic float-pair live RAM fallback scanning.
* **Native Rust & Python WESYS Crypto Engine**: Full symmetric XorShift128 32-bit stream cipher with Zlib compression for Konami WESYS containers and database records (`Player.bin`, `PlayerAssignment.bin`, `Team.bin`, `TeamColor.bin`).
* **Batch Database & CSV Studio**: Multi-threaded database folder extractor, structured CSV exporter, and interactive record visualizer.
* **Live Memory Sniffer & Hex Studio**: Zero-lag virtual pagination sniffer to inspect loaded game assets and memory addresses in real time.

---

## 🚀 Architecture & Subsystems

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                         eFootball Sider Architecture                         │
├──────────────────────────────────────┬───────────────────────────────────────┤
│          rust_sider (dxgi.dll)       │        efootball_sider_gui.py         │
│         (Native High-Perf Core)      │        (6-Tab Modder Studio GUI)      │
├──────────────────────────────────────┼───────────────────────────────────────┤
│ • DirectX Proxy Forwarding (DXGI)    │ 🛰️ 1. Live Asset Sniffer             │
│ • Pelite AOB Detour + RAM Fallback   │ 🔬 2. Visual Asset & Hex Inspector    │
│ • 3-Level LiveCPK VFS File Detour    │ 🔍 3. Memory Search & Smart Inject    │
│ • Native WESYS & XorShift128 Crypto  │ 📦 4. Mod Manager & LiveCPK Diag      │
│ • In-Game OSD HUD & Hotkeys Listener │ 💉 5. Database Studio & Batch Decrypt │
│ • KitServer & StadiumServer Modules  │ 🎬 6. Camera Studio & Broadcast Master│
└──────────────────────────────────────┴───────────────────────────────────────┘
```

### 1. `rust_sider/` (Native Proxy Core — `dxgi.dll`)
* **DirectX Proxy Hook**: Intercepts `CreateDXGIFactory`, `CreateDXGIFactory1`, and `CreateDXGIFactory2` and cleanly forwards them to `C:\Windows\System32\dxgi.dll`.
* **In-Process Camera Hook (`camera.rs`)**: 
  - **Primary Mode**: Scans eFootball's `.text` section using Pelite AOB signatures to install a 64-bit executable detour trampoline on `PesCameraComponent` (updating Zoom at `0x105C`, Height at `0x1060`, Angle at `0x1064`, and FOV at `0x1068`).
  - **Fallback Mode**: Automatically engages dynamic `PAGE_READWRITE` float-pair memory scanning if game updates alter the AOB signature.
  - **Zero Redundancy**: Golden-ratio hash comparison (`LAST_CAMERA_HASH`) eliminates redundant memory writes.
* **Native Crypto Engine (`crypto.rs`)**: Implements 32-bit XorShift128 keystream PRNG and container decompressor in pure Rust, exported via C-ABI (`wesys_unpack_native`).
* **LiveCPK VFS (`livecpk.rs`)**: 
  - 3-level path resolution: (1) Exact key, (2) Subpath suffix, (3) Basename fallback matching.
  - Automatically indexes loose files inside `content/` as a low-priority fallback root after active registered mods.
  - Thread-safe `kernel32!CreateFileW` detour with throttled override logging.
* **OSD & Input Overlay (`overlay.rs`)**: In-game keyboard listener for quick adjustments during gameplay.

### 2. `efootball_sider_gui.py` (Modder Studio Suite)
* **Tab 1: Live Asset Sniffer**: Intercepts game asset paths, textures, and models in memory with virtual treeview pagination.
* **Tab 2: Visual Asset & Hex Inspector**: Real-time memory dumper, color palette renderer, and UTF-8/ASCII string extractor.
* **Tab 3: Search & Smart Inject**: Fast multi-threaded RAM string search with 1-click text injection and robust exception logging.
* **Tab 4: Mod Manager & LiveCPK Diag**: 1-click ZIP mod installer, package prioritization, automatic `sider.ini` registration, and full VFS simulation diagnostics.
* **Tab 5: Database Studio**: 
  - **Batch Extraction**: "📂 DECODIFICA CARTELLA PESDB" decrypts all `.bin` files and generates matching `.csv` spreadsheets.
  - **Format Parsers**: Structured parsing for `Team.bin` (stride 64), `TeamColor.bin` (stride 64), `Player.bin` (stride 400), and `PlayerAssignment.bin` (stride 24).
  - **WESYS Re-Pack**: Compresses and encrypts raw database files into 100% game-compatible WESYS containers with XorShift128 (0x20).
* **Tab 6: Camera Studio & Broadcast Master**: Dynamic sliders for Zoom, Height, Lens Angle, and FOV with instant live RAM injection and `sider.ini` syncing.

---

## 🎬 Camera Studio & In-Game Controls

Sider includes pre-calibrated, television-style camera presets inspired by Premier League, UEFA Champions League, and Serie A broadcasts:

| Preset | Zoom | Height | Angle / Tilt | FOV | Best For |
|---|---|---|---|---|---|
| **⭐ Broadcast Ultimate TV** | `0.82` | `1.32` | `-0.12` | `50.0°` | Realistic TV broadcast view with perfect depth and pitch overview |
| **🏟️ Sky Sports Tactical Wide** | `0.72` | `1.45` | `-0.15` | `54.0°` | Full-pitch tactical vision for passing lanes and defensive lines |
| **⚽ EA Sports Dynamic TV** | `1.05` | `1.15` | `0.00` | `46.0°` | Close-up action view highlighting player dribbling and animations |
| **🎮 Curva Fan Cam** | `1.20` | `0.95` | `0.10` | `42.0°` | High stadium panorama view from the top tier |
| **🔄 Default Konami** | `1.00` | `1.00` | `0.00` | `50.0°` | Standard unmodded game view |

### In-Game Hotkeys

| Hotkey | Action |
|---|---|
| **`[F1]`** | Toggle **3D Freecam** (Free stadium flight for replays/screenshots) |
| **`[Numpad +]` / `[Numpad -]`** | Real-time **Zoom** in / out |
| **`[Numpad 8]` / `[Numpad 2]`** | Real-time **Camera Height** up / down |
| **`[Numpad 4]` / `[Numpad 6]`** | Real-time **Lens Angle / Tilt** adjustment |
| **`[Space]`** | Show / Hide **In-Game Sider OSD HUD** |

---

## ⚙️ Master Configuration (`sider.ini`)

`sider.ini` is the single master configuration file located in the root directory:

```ini
; ==============================================================================
; Efootball Sider by Toriga - Master Configuration (sider.ini)
; ==============================================================================

[SETTINGS]
mods_directory = "content"
live_asset_loader = 1
live_texture_override = 1
live_mesh_override = 1
live_database_override = 1

[sider]
debug = 1
freecam = 0

[camera]
enabled = 1
zoom = 0.82
height = 1.32
angle = -0.12
fov = 50.0
freecam_speed = 2.5

[OVERLAY]
enabled = 1
hotkey_toggle = "Space"
hotkey_freecam = "F1"

[SERVERS]
kitserver_enabled = 1
stadiumserver_enabled = 1
ballserver_enabled = 1

[LIVE_CPK]
cpk.root = "content"
; cpk.root = "content\My_Custom_Mod"
; cpk.root = "content\RealFaces"
```

---

## 🛠️ How to Build & Test

### Prerequisites
* Windows 10 / 11 (64-bit)
* [Rust Toolchain (cargo & rustc)](https://rustup.rs/)
* [Python 3.10+](https://www.python.org/downloads/)

### 1. Build & Test Native Rust Core (`dxgi.dll`)
```bash
cd rust_sider
cargo test
cargo build --release
copy target\release\dxgi.dll ..\dxgi.dll
cd ..
```

### 2. Run Python Validation Suite
```bash
python -m unittest tests/test_sider_suite.py
```

### 3. Launch the Studio GUI
```bash
pip install -r requirements.txt
python efootball_sider_gui.py
```

---

## 📁 Repository Structure

```text
Efootball-Sider/
│
├── Avvia_Sider_GUI.bat                 # 1-Click GUI Studio Launcher
├── Installa_Sider_in_eFootball.bat     # 1-Click Sider Installer into Game Binaries
├── Disinstalla_Sider.bat               # 1-Click Sider Clean Uninstaller
├── Riavvia_eFootball_con_Sider.bat     # 1-Click Restart & Sync Game Launcher
│
├── dxgi.dll                            # Compiled Native 64-bit Proxy DLL
├── sider.ini                           # Master Configuration File
├── efootball_sider_gui.py              # Main 6-Tab Modder Studio Application
│
├── rust_sider/                         # Rust Core Source Code
│   ├── Cargo.toml                      # Crate configuration (cdylib)
│   └── src/
│       ├── lib.rs                      # DllMain & DirectX export forwarding
│       ├── camera.rs                   # Pelite AOB detour & RAM fallback scanner
│       ├── crypto.rs                   # Native WESYS & XorShift128 crypto engine
│       ├── livecpk.rs                  # 3-level LiveCPK virtual filesystem
│       ├── overlay.rs                  # OSD overlay & keyboard input listener
│       └── server.rs                   # KitServer / StadiumServer modules
│
├── content/                            # Mod Packages Directory (LiveCPK)
├── docs/                               # Architecture Specifications
│   ├── UNREAL_ENGINE_EFOOTBALL_ARCHITECTURE.md
│   └── FOX_ENGINE_LEGACY_ARCHITECTURE.md
│
├── tests/                              # Comprehensive Python & Cross-Language Tests
│   └── test_sider_suite.py
│
├── requirements.txt                    # Python dependencies
├── README.md                           # Project documentation
├── CONTRIBUTING.md                     # Modder contribution guidelines
└── LICENSE                             # GNU General Public License v3.0
```

---

## 🤝 Contributing

We welcome contributions from modders, reverse engineers, and developers!
* Reverse engineering findings for eFootball memory offsets, data structures, and container formats.
* Community camera presets, UI enhancements, and server modules.
* Check [CONTRIBUTING.md](CONTRIBUTING.md) and feel free to open a Pull Request or Issue.

---

## ⚖️ Disclaimer & License

* **eFootball Sider by Toriga** is an independent, open-source modding platform and research framework developed for educational and community enhancement purposes.
* *eFootball* and *PES* are registered trademarks of **KONAMI Digital Entertainment Co., Ltd.**. This project is not affiliated with, endorsed by, or associated with Konami.
* This project is licensed under the **GNU General Public License v3.0** (GPL-3.0). See [LICENSE](LICENSE) for details.
