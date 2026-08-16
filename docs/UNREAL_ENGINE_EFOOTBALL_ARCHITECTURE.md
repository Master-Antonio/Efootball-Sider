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
   │      ├── [Fallback Redirection -> content/] (Loose Assets)
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
| `0x00` | 1 byte | `u8` | Flag byte / Seed Mode (`0x20`, `0x21`, etc.) |
| `0x01` | 2 bytes | `u16` | Format version / Padding |
| `0x03` | 5 bytes | `ASCII` | Magic identifier `"WESYS"` (`0x57 0x45 0x53 0x59 0x53`) |
| `0x08` | 4 bytes | `u32 LE` | Uncompressed payload size |
| `0x0C` | 4 bytes | `u32 LE` | Compressed payload size |

### 32-bit XorShift128 Keystream Decryption / Encryption
When `flag_byte >= 0x20`, the payload starting at offset 16 is ciphered 32 bits at a time using a symmetric pseudo-random number generator (PRNG) state machine:

```
t = x ^ (x << s1)
x = y; y = z; z = w;
w = (w ^ (w >> s3)) ^ (t ^ (t >> s2))
keystream_u32 = w & 0xFFFFFFFF
ciphered_u32 = raw_u32 ^ keystream_u32
```

#### Seed Constants by Flag:
- **`0x20`**: `seed=(0x12345678, 0x9ABCDEF0, 0x13579BDF, 0x2468ACE0)`, `shifts=(11, 8, 19)`
- **`0x21`**: `seed=(0x87654321, 0x0FEDCBA9, 0xFDB97531, 0x0ECA8642)`, `shifts=(11, 8, 19)`
- **Default**: `seed=(0x6C8E9CF5, 0x3B2F7E41, 0x9D4C1A8B, 0x5E6A7D2C)`, `shifts=(11, 8, 19)`

Following 32-bit decryption, the payload is decompressed via **Zlib (RFC 1950 inflate)** to produce the final fixed-stride binary database tables.

---

## 3. Real-Time Camera Hooking: Dual-Mode Architecture

eFootball evaluates match camera parameters inside the `PesCameraComponent` class within the Unreal Engine scene graph.

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

### Mode 2: Dynamic RAM Float-Pair Fallback Scanner
If game executable updates change the `.text` pattern, Sider automatically shifts to fallback mode:
- Periodically scans committed `PAGE_READWRITE` regions for consecutive float quadruplets/pairs (`fov` in `20.0..120.0`, `zoom` in `0.1..5.0`).
- Writes are guarded by the golden-ratio 32-bit hash (`compute_camera_values_hash`) to avoid redundant memory writes.

---

## 4. LiveCPK Virtual File System Redirection (`CreateFileW`)

To load custom textures and assets without rebuilding `.pak` containers:

1. **Hierarchical Indexing**:
   - High Priority: Registered active mod roots (`content/<ModName>/`).
   - Low Priority: Fallback base `content/` root (auto-discovered).
2. **3-Level Resolution Engine**:
   - **Level 1 (Exact Match)**: Direct $O(1)$ HashMap lookup on normalized path.
   - **Level 2 (Suffix Subpath Match)**: Suffix slice lookup for absolute/relative game paths.
   - **Level 3 (Basename Fallback Match)**: Matches loose filenames directly (with log throttling).
3. **Win32 API Detour**: Intercepts `kernel32!CreateFileW` via `retour::GenericDetour`, substituting game requests with disk-resident mod assets.
