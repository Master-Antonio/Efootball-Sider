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
          ├── Live update layer (`cpk/dt870_console_win.cpk`)
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
* **`cpk/dt870_console_win.cpk`**: Current live update layer. On the inspected Steam installation it contains 50 entries, including the active pesdb tables.

---

## 3. Fox Engine Fixed-Stride Binary Database Structures (`pesdb/`)

The internal tables located within the legacy archives (`common/etc/pesdb/`) adhere to Fox Engine's binary layout:

### Key Table Schemas
1. **`Team.bin` (Team Database)**:
   * Fixed 1,600-byte records; Team ID is `u32 LE` at record offset 12.
   * The file itself starts with the 16-byte WESYS wrapper; the decoded stream has no additional WESYS header.
2. **`Player.bin` (Player Database)**:
   * `dt200` uses 400-byte records; the inspected `dt870` uses 392-byte records. External PID remains `u64 LE` at offset 8.
3. **`PlayerAssignment.bin` (Roster & Squad Mappings)**:
   * The current v2 layout maps PID at offset 0, Team ID at 8, Record ID at 12, shirt/sort at 16/17 and role flags at 18.

---

## 4. Cryptographic Keystream & Container Parsing

Unlike standard open-source archives, the Fox Engine legacy files inside eFootball utilize a dual-stage encryption pipeline:

1. **Header Identification**:
   * Sider checks the file header for the `"WESYS"` signature at offset `0x03`.
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
| **Live Redirection** | Loose-file `CreateFileW` hook; IoStore mounting remains separate | CPK extraction and validated WESYS repacking |
