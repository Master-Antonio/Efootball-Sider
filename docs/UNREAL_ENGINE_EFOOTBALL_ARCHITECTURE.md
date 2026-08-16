# Technical Architecture: Unreal Engine in eFootball

This document provides a comprehensive technical specification of the **Unreal Engine** architecture in **eFootball** (`eFootball.exe` / `eFootball-Win64-Shipping.exe`), detailing its container systems, crypto layers, in-memory camera components, and live virtual file system interception.

---

## 1. Engine Pipeline & Asset Container Structure

eFootball utilizes a customized build of **Unreal Engine** combined with a legacy binary compatibility layer:

```
[eFootball.exe / Win64 Shipping Process]
   │
   ├── [Win32 VFS Detour: CreateFileW Hook (LiveCPK)]
   │      │
   │      ├── [Virtual Redirection -> content/<ModName>/] (Active Mods)
   │      └── [Original Game Storage]
   │             ├── Cooked Unreal Pak Archives (pak/pakchunk*.pak)
   │             │      ├── .uasset (UObject Metadata & Types)
   │             │      ├── .uexp (Export Data, Meshes & Materials)
   │             │      └── .ubulk (Bulk Streaming Data, Textures & Audio)
   │             │
   │             └── Hybrid Legacy Containers (cpk/dt*.cpk & ProgramData/dt870)
   │                    └── Encrypted Database & String Tables (Team.bin, Player.bin, str_*.bin)
```

### Unreal Engine Cooked Asset Formats
* **`.uasset` (UObject Asset Header)**: Stores serialized class references, export/import tables, property schemas, and material node definitions.
* **`.uexp` (Export Binary Payload)**: Contains geometry vertex buffers, index arrays, skeletal rigs, and cooked shader maps.
* **`.ubulk` (Bulk Stream Segment)**: High-resolution texture data (BC1/BC3/BC7 DirectX Tex formats) and audio stream samples loaded dynamically on demand.

---

## 2. Cryptographic Engine: WESYS Container & XorShift128 PRNG

Core game database files (`Team.bin`, `TeamColor.bin`, `Player.bin`, `PlayerAssignment.bin`) and string localization packages (`dt261_*_console_win.cpk` / `dt870`) are wrapped inside Konami's proprietary **`WESYS`** container.

### WESYS Header Layout (16 Bytes)
| Offset | Size | Type | Description |
| :--- | :--- | :--- | :--- |
| `0x00` | 1 byte | `u8` | `0xFF` on current shipped tables |
| `0x01` | 1 byte | `u8` | Low nibble selects key constants (`0x22` -> key 2) |
| `0x02` | 1 byte | `u8` | `0x83` normal table, `0x02` empty table |
| `0x03` | 5 bytes | `ASCII` | Magic identifier `"WESYS"` (`0x57 0x45 0x53 0x59 0x53`) |
| `0x08` | 4 bytes | `u32 LE` | Compressed payload size |
| `0x0C` | 4 bytes | `u32 LE` | Uncompressed payload size |

### 32-bit XorShift128 Keystream Decryption / Encryption
The current payload starts at byte 16 and is XORed 32 bits at a time. The size fields seed `w`, so the seed is different for every recompressed file:

```
w = ((orig_size << 16) | comp_size) & 0xFFFFFFFF
t = (x ^ (x << 11)) & 0xFFFFFFFF
x, y, z, previous = y, z, w, w
w = (previous ^ (((previous >> 11) ^ t) >> 8) ^ t) & 0xFFFFFFFF
payload_u32 ^= w
```

#### Key constants by nibble

- **1**: `(0x168EA000, 0x2E2AA6F2, 0x0CC8DCD3)`
- **2**: `(0xED5B2960, 0x4A523B4E, 0xF3A31BAD)`

Trailing 1-3 bytes remain plaintext. Following decryption, Zlib produces the fixed-stride table. `ui/core/wesys.py` and `rust_sider/src/crypto.rs` implement this layout and are cross-language tested against extracted `dt870` files.

---

## 3. Camera Hook Research Status

The following signature and offsets are a historical candidate. The controller configuration and trampoline implementation exist, but the current Steam build is not considered supported until the native log records in-match `[CAMERA DETOUR]` calls with sane values.

### Mode 1: In-Game AOB Byte Signature & Trampoline Detour
The 34-byte SIMD SSE parameter loading sequence in `eFootball.exe` (`.text` section) is identified by Pelite:

```x86asm
; RVA 0x17E2997 in eFootball.exe (.text)
F3 0F 10 B6 5C 10 00 00    ; movss xmm6, dword ptr [rsi+0x105C]  -> Zoom Multiplier
F3 0F 10 BE 60 10 00 00    ; movss xmm7, dword ptr [rsi+0x1060]  -> Height Multiplier
F3 44 0F 10 86 64 10 00 00 ; movss xmm8, dword ptr [rsi+0x1064]  -> Angle / Tilt Multiplier
F3 44 0F 10 8E 68 10 00 00 ; movss xmm9, dword ptr [rsi+0x1068]  -> Field of View (FOV)
```

1. **Memory Allocation**: Sider allocates an executable page with `VirtualAlloc(PAGE_EXECUTE_READWRITE)`.
2. **Register Capture**: In the trampoline shellcode, `mov rcx, rsi` captures the live pointer of `PesCameraComponent`.
3. **Atomic Parameter Write**: The detour function directly updates the live component fields:
   * `[rsi + 0x105C]` = Zoom (`0.10` - `5.00`)
   * `[rsi + 0x1060]` = Height (`0.10` - `5.00`)
   * `[rsi + 0x1064]` = Pitch / Angle (`-1.00` - `1.00`)
   * `[rsi + 0x1068]` = FOV (`15.0°` - `120.0°`)
4. **Execution Resumption**: The original 4 SSE instructions execute within the trampoline, followed by an absolute 64-bit jump (`jmp qword ptr [rip+0]`) back to `hook_addr + 34`.

### Experimental fallback scanner
If game executable updates change the `.text` pattern, Sider automatically shifts to fallback mode:
- Periodically scans committed `PAGE_READWRITE` regions for consecutive float quadruplets/pairs (`fov` in `20.0..120.0`, `zoom` in `0.1..5.0`).
- Candidate float matching is not proof of object identity. It must not be presented as a verified camera target without pointer/lifecycle evidence.

---

## 4. Win32 Loose-File Redirection (`CreateFileW`)

The hook can redirect a file request only when the game opens that path through the intercepted Win32 API:

1. **Explicit root indexing**: only active `cpk.root` entries are indexed. This makes enable/disable and priority deterministic.
2. **3-Level Resolution Engine**:
   - **Level 1 (Exact Match)**: Direct $O(1)$ HashMap lookup on normalized path.
   - **Level 2 (Suffix Subpath Match)**: Suffix slice lookup for absolute/relative game paths.
   - **Level 3 (Basename Fallback Match)**: Matches loose filenames directly (with log throttling).
3. **Win32 API Detour**: Intercepts `kernel32!CreateFileW` via `retour::GenericDetour`, substituting game requests with disk-resident mod assets.

### IoStore limitation

Most UE4.26 assets are read as package chunks from `.utoc/.ucas`, not opened as loose `.uasset/.uexp/.ubulk` files. Seeing a virtual asset path in memory or installing the Win32 hook does not prove an override. Package replacement requires a valid cooked IoStore container and a mount/deploy mechanism; that work remains separate from this loose-file VFS.
