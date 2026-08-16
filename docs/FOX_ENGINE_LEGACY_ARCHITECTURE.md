# Technical Architecture: Fox Engine Legacy Subsystems in eFootball

This document provides a technical specification of the **Fox Engine legacy subsystems and data structures** that Konami retained and adapted for **eFootball**'s database, string localization, and archive hierarchy.

---

## 1. The Fox Engine Legacy in eFootball

When Konami transitioned eFootball to Unreal Engine 4 for gameplay and rendering, they preserved the battle-tested database and asset packaging subsystems derived from the Fox Engine architecture:

```
[eFootball Data Pipeline]
   │
   ├── [Unreal Engine 4 Subsystem]
   │      └── Rendering, Physics, Shaders & PesCameraComponent
   │
   └── [Fox Engine Legacy Subsystem]
          ├── Criware File System (CPK Archives: dt000_console_all.cpk, etc.)
          ├── ProgramData DLC Cache (dt870_console_all.cpk)
          ├── Fixed-Stride pesdb Binary Tables (Team.bin, Player.bin)
          └── String Localization Tables (dt261_ita_console_win.cpk)
```

---

## 2. Criware CPK Archive Architecture

eFootball continues to load game database tables, commentary tracks, and language assets from **CRI Middleware (Criware CRI File System)** archives (`.cpk` format):

### Archive Distribution
* **`cpk/dt000_console_all.cpk`**: Common game database tables and core configuration parameters.
* **`cpk/dt200_console_all.cpk`**: Shared competition and tournament rulesets.
* **`cpk/dt261_*_console_win.cpk`**: Language-specific localization dictionaries (e.g. `str_ita.bin`, `str_eng.bin`).
* **`ProgramData/Konami/eFootball/dt870_console_all.cpk`**: Live updates, roster data, and real-time event patches pushed by Konami servers.

---

## 3. Fox Engine Fixed-Stride Binary Database Structures (`pesdb/`)

The internal tables located within the legacy archives (`common/etc/pesdb/`) adhere to Fox Engine's binary layout:

### Key Table Schemas
1. **`Team.bin` (Team Database)**:
   * Fixed binary stride per team record (storing Team ID, Stadium ID, licensed badge index, kit style flags, and color palettes).
   * Encapsulated inside a `WESYS` header starting at offset `2051` (`0x803`) in the decrypted stream.
2. **`Player.bin` (Player Database)**:
   * Fixed binary stride per player record (storing Player ID, age, nationality, physical attributes, stats, and special skill flags).
3. **`PlayerAssignment.bin` (Roster & Squad Mappings)**:
   * Maps Player IDs to Team IDs, specifying squad numbers, formation positions, and captaincy flags.

---

## 4. Cryptographic Keystream & Container Parsing

Unlike standard open-source archives, the Fox Engine legacy files inside eFootball utilize a dual-stage encryption pipeline:

1. **Header Identification**:
   * Sider inspects the binary header for the `"WESYS"` signature at offset `0x03` or offset `2051`.
2. **XorShift128 Keystream Unpacking**:
   * The 16-byte header specifies the flag byte, compressed size, and uncompressed size.
   * A 32-bit linear keystream generates XOR keys to decode the payload.
3. **Zlib Inflation**:
   * The decrypted payload is inflated into raw binary tables, enabling direct inspection, hex editing, and real-time memory overrides.

---

## 5. Summary: How Modern Sider Bridges Both Engines

| Feature | Unreal Engine Subsystem | Fox Engine Legacy Subsystem |
| :--- | :--- | :--- |
| **Primary Domain** | 3D Rendering, Shaders, Camera, Match Engine | Data Tables, Roster DB, Text Localization |
| **Container Format** | Cooked `.pak` (`pakchunk*.pak`) | Criware `.cpk` (`dt*.cpk`) |
| **Asset Formats** | `.uasset`, `.uexp`, `.ubulk` | Fixed-stride `.bin` (`pesdb/`), `.str` tables |
| **Sider Hooking Method** | Pelite AOB Detour on `PesCameraComponent` | In-memory parsing & VFS file redirection |
| **Live Redirection** | Win32 `CreateFileW` hook (`retour`) | Win32 `CreateFileW` hook (`retour`) |
