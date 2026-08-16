# eFootball Sider Studio

An open-source Windows modding studio and native runtime for current eFootball builds.

The project combines a Rust `dxgi.dll` proxy with a modular PySide6 desktop app. Its current strengths are database research, safe mod-package management, runtime diagnostics, and read-only asset discovery. Package-level Unreal IoStore replacement and the current camera signature are active research areas, not completed features.

## Status

| Area | State | Notes |
|---|---|---|
| Native DXGI proxy | Working | Rust proxy forwards required DXGI exports and initializes outside loader lock. |
| WESYS codec | Working | Current `FF 22 83` format, per-file seed, trailing-byte behavior, Python/Rust parity. |
| CPK extraction | Working | Selective `dt870` extraction through CriCodecs. |
| Player database | Working | Auto-detects 392-byte live and 400-byte base records. |
| Assignment database | Working | Supports v1 and current v2 layouts with cross-table validation. |
| Squad replacement core | Working | Changes PID fields only; rejects missing players and headcount changes. |
| Mod manager | Working | Safe ZIP import, path-traversal rejection, explicit `cpk.root` activation. |
| Asset discovery | Working, read-only | Incremental scan of asset references in eFootball memory. |
| Loose Unreal asset override | Research | `CreateFileW` alone does not replace packages stored inside IoStore containers. |
| Camera controller | Research | Configuration works; the current in-match AOB detour still needs verified telemetry. |

## Desktop app

The Qt app is organized around the actual modding workflow:

- **Overview**: installation, native-core hash, database and package readiness.
- **Assets**: read-only discovery of loaded paths and mod-package scaffolding.
- **Database**: extract, decrypt, validate, filter and export live pesdb tables.
- **Mods**: install packages, inspect size and contents, manage active roots.
- **Camera**: edit profiles in `sider.ini` and inspect hook verification state.
- **Diagnostics**: ground-truth file checks and native log tail.

All long-running file and memory operations use Qt workers. Tables use `QAbstractTableModel`, so tens of thousands of records are not copied into individual widgets.

## Architecture

```text
ui/
  app.py                 application entrypoint and screenshot mode
  main_window.py         navigation shell
  core/
    wesys.py             current and legacy WESYS codecs
    pesdb.py             record layouts, validation and squad edits
  services/
    database.py          CPK extraction and CSV export
    config.py            camera settings and mod roots
    game.py              install status, hashes, sync and logs
    memory.py            read-only process discovery
    paths.py             portable workspace/game path discovery
  pages/                 six focused application pages
  widgets/               shared visual primitives

rust_sider/
  src/lib.rs             DXGI proxy and lifecycle
  src/crypto.rs          native WESYS decoder C ABI
  src/livecpk.rs         experimental Win32 file-open interception
  src/camera.rs          experimental camera signature and detour
```

`efootball_sider_gui.py` remains as a small compatibility launcher and API facade. New code should import from `ui`.

## Requirements

- Windows 10 or 11, x64
- Python 3.11 or newer
- Rust stable toolchain when building `dxgi.dll`
- Steam eFootball installation

The game path is discovered from common Steam locations. Set `EFOOTBALL_GAME_DIR` to the eFootball root when it is installed elsewhere.

## Setup

```powershell
git clone https://github.com/Master-Antonio/Efootball-Sider.git
cd Efootball-Sider
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m ui
```

You can also run `Avvia_Sider_GUI.bat`.

## Build the native core

```powershell
Set-Location rust_sider
cargo test
cargo build --release
Set-Location ..
```

Use the **Sync Sider** action in the app, or run `Installa_Sider_in_eFootball.bat` while the game is closed. Release archives include the compiled DLL; source checkouts build it locally and do not track compiler output.

## Database workflow

The Database page defaults to:

```text
<game-root>/cpk/dt870_console_win.cpk
```

Extraction writes only local workspace data under `.workspace/pesdb/`:

```text
live/
  packed/common/etc/pesdb/     original WESYS files
  decoded/common/etc/pesdb/    validated raw tables
  manifest.json                counts, layouts, warnings and SHA-256 hashes
```

On the Steam build inspected on 2026-08-17, validation produced:

- 34,303 Player records, 392 bytes each
- 23,163 PlayerAssignment v2 records
- 787 populated squads
- 975 Team records
- 100% assignment PID resolution against Player.bin

These values are evidence for that build, not constants. The parsers validate each new extraction instead of trusting the counts.

## Mod package layout

```text
content/
  My_Mod/
    mod.ini
    PesConsole/Content/...     cooked files at their virtual paths
```

Example metadata:

```ini
[MOD]
name = My Stadium
category = Stadium
author = Modder
version = 1.0
```

Enabling a package adds an explicit root such as:

```ini
cpk.root = "content\My_Mod"
```

This controls loose-file lookup. It does not yet mount a replacement IoStore container.
The runtime no longer auto-indexes every child under `content/`; this makes package disable and load order deterministic. A legacy `cpk.root = "content"` still enables the entire tree intentionally.

## Tests

```powershell
python -m unittest discover -s tests -v

Set-Location rust_sider
cargo test
```

Render a deterministic UI screenshot:

```powershell
python -m ui --screenshot .workspace\ui\database.png --page database --width 1440 --height 900
```

Build the release archive:

```powershell
python scripts\build_release.py
```

The output is `dist/eFootball_Sider_Studio.zip`.

## Safety and scope

- Keep backups of original game files.
- Do not patch the executable or bypass platform/anti-cheat controls with this project.
- eFootball is always online; use mods only where permitted and accept account risk.
- Memory discovery is read-only. Database writes are performed on extracted copies.
- A successful path match is not proof that Unreal loaded an override from inside IoStore.

## Contributing

See `CONTRIBUTING.md`. Reverse-engineering claims must include a reproducible file/build, offsets or record layout, and a regression test. UI changes must include an offscreen screenshot and keep blocking work outside the GUI thread.

## License

GPL-3.0. eFootball and KONAMI are trademarks of their respective owners. This project is independent and is not endorsed by KONAMI.