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

### Rejected candidates (why the old hooks did nothing in-match)

Two generic UE4 `FMinimalViewInfo`-style signatures were previously hooked
(`SIG1` `F3 0F 11 49 2C ...` at RVA `0x330B5CD`, `SIG2` `F3 0F 11 6B 18 ...`
at RVA `0x3313EF0`, both in `.xcode`). Static disassembly of the current build
shows they sit in the wrong code:

- `SIG1` is mid-way through a bulk float-copy loop (ten `movss` stores from
  stack slots into `[rcx+8..0x30]`) — a generic struct serialization, not a
  per-frame camera update.
- `SIG2` is the tail of a function (float stores into `[rbx+0x18..0x2C]` right
  before the `mov rsp,r11; pop; ret` epilogue).

Runtime telemetry confirmed it: the detour fired exactly **3 times per session**
(during scene init) with a deterministic bogus pointer (`0xF7C730`) and a read
FOV of `0.0`, then never again. So those sites never run per-frame during a
match, and writing through them only touched unknown memory. Both hooks are now
disabled by default (`[camera] legacy_hooks = 0`).

### Active candidate: PesCameraComponent parameter loads

The 34-byte SIMD parameter-load sequence below was re-verified in the current
Steam build (`.xcode` section). It is **unique** in the whole 94 MB section:

```x86asm
; RVA 0x17E3597 in eFootball.exe (.xcode)
F3 0F 10 B6 5C 10 00 00    ; movss xmm6, dword ptr [rsi+0x105C]  -> Zoom Multiplier
F3 0F 10 BE 60 10 00 00    ; movss xmm7, dword ptr [rsi+0x1060]  -> Height Multiplier
F3 44 0F 10 86 64 10 00 00 ; movss xmm8, dword ptr [rsi+0x1064]  -> Angle / Tilt Multiplier
F3 44 0F 10 8E 68 10 00 00 ; movss xmm9, dword ptr [rsi+0x1068]  -> Field of View (FOV)
```

The site is inside a camera-mode dispatch (comparisons on a mode byte, guarded
by the flag at `[rsi+0x1048]`), and the four instructions are relocation-safe
(no RIP-relative addressing), which makes it a clean inline-hook target.

1. **Memory Allocation**: Sider allocates an executable page with `VirtualAlloc(PAGE_EXECUTE_READWRITE)`.
2. **Register Capture**: The trampoline saves flags/GPRs/xmm0-5, aligns RSP to 16
   (Windows x64 ABI), then `mov rcx, rsi` passes the live `PesCameraComponent`
   pointer to the Rust detour.
3. **Two modes** (`[camera] mode` in `sider.ini`):
   - `telemetry` (default): read + log the four floats and the mode flag only.
     Never writes into game memory.
   - `apply`: writes the configured values so the original (hooked) loads pick
     them up, using intelligent dual-range scaling (relative multiplier if < 10.0, or game-native coordinates if >= 10.0):
     * `[rsi + 0x105C]` = Zoom (< 10.0: relative `cur * zoom`; >= 10.0: clamped `10.0` - `300.0`)
     * `[rsi + 0x1060]` = Height (< 10.0: relative `cur * height`; >= 10.0: clamped `10.0` - `400.0`)
     * `[rsi + 0x1064]` = Pitch / Angle (`-180.0°` - `180.0°`)
     * `[rsi + 0x1068]` = FOV (`0.5°` - `120.0°`)
4. **Execution Resumption**: The original 34 bytes execute inside the trampoline,
   followed by an absolute 64-bit jump (`jmp qword ptr [rip+0]`) back to
   `hook_addr + 34`.

### Acceptance gate

The build is not considered to have a working match camera until the native log
(`sider_rust.log`, written next to `dxgi.dll`) records continuous in-match
`[CAMERA DETOUR] PesCamera call #...` lines with plausible values while a match
is being played. Only then should `mode = apply` be enabled.

### Verified runtime behaviour (2026-08-23 telemetry session)

- The hook installs at the expected RVA and receives real heap component
  pointers — plumbing works end to end.
- The hooked function runs **only on camera transitions** (~20 calls per
  session: scene init, replay/cutscene switches), never per-frame during play.
- Observed native values were identical across calls and components:
  `zoom=61.0 height=89.2 angle=28.0 fov=3.0 mode_flag=0x01`. These are
  **game-native units**, not the 0.1–5 ranges listed above for `sider.ini`.
- Static cross-reference of all four displacements in `.xcode` confirms the
  only LOAD instructions for these fields are the four inside the hooked
  signature; the main WRITER sits just above it (RVA `0x17E2AFA–0x17E2B12`,
  config persist path).

Consequences:

1. Writing via the hook **does reach the consumers** (no other code reads these
   fields), but changes take effect on the next camera transition — kickoff,
   replay, or a camera switch — not live during play.
2. Before `apply` is usable, sider.ini values must be mapped to game units:
   change the in-game camera sliders while `mode = telemetry` is active and diff
   the logged values. Until that mapping exists, keep telemetry mode.

### Mapping session protocol

Instruments shipped for this session: OSD second line (live game values),
**F9** marker key, and native telemetry log `sider_rust.log`.

1. Launch the game with `[camera] mode = telemetry`.
2. Reach a screen where camera transitions fire (menus, replay, match start).
3. Change ONE in-game camera slider at a time; press **F9** immediately after
   each change.
4. Inspect `sider_rust.log`: every distinct value tuple appears in
   order with `[MARK #n]` lines inline — each marker brackets what changed.
5. Once every configuration field has a verified game-unit counterpart, switch to
   `mode = apply`, write values in GAME units and confirm on the next camera
   transition or live tick.

### Plan B: Autonomous Data Scanner & Self-Healing Watchdog (Implemented in v1.1)

In addition to the 34-byte inline detour, Sider implements a two-stage dynamic memory scanner (`spawn_data_scanner`) and an integrity watchdog (`spawn_patch_watchdog`) in `rust_sider/src/camera.rs` to guarantee telemetry and configuration resilience even across patch updates or integrity checks:

#### 1. Plan B Global Config Data Scanner
If the game does not execute the instruction detour (e.g. during specific menus or altered camera execution graphs), the background scanner dynamically identifies the active `PesCameraComponent` config block in memory:
- **Heuristic Signature**: Scans committed `PAGE_READWRITE` memory for regions structured as:
  `[0x00: u8 flag == 0x01] ... [0x14: f32 zoom, 0x18: f32 height, 0x1C: f32 angle, 0x20: f32 fov]`.
- **Plausibility Envelope**: Validates values against game-native ranges: `zoom` ∈ [10.0, 300.0], `height` ∈ [10.0, 400.0], `angle` ∈ [-180.0, 180.0], `fov` ∈ [0.0, 89.0].
- **Two-Pass Verification**: Executes Pass A and Pass B spaced by 2,000ms. Only addresses whose 17-byte layout remains invariant across both passes are retained as stable candidates.
- **Dynamic Lock-on**: The background thread polls all stable candidates every 250ms. As soon as the player adjusts any camera slider in the in-game settings, the scanner detects the changed float, identifies the live memory object with 100% precision, sets the OSD status chip to `LIVE`, and feeds real-time telemetry to the OSD HUD and F9 logger.
- **Continuous Live Apply (v1.2)**: When `mode == CameraMode::Apply`, the scanner thread continuously writes the scaled camera parameters to `DATA_ADDR + 0x14..0x24` every 250ms tick. This forces camera parameters to stay active in real-time during match play without requiring cutscenes or camera resets.

#### 2. Self-Healing Integrity Watchdog
eFootball occasionally executes code integrity checks that restore original opcode bytes. Sider protects its hooks via a 5-second polling watchdog:
- Keeps a snapshot of the original 34 bytes in `PATCH_ORIGINAL`.
- Every 5 seconds, inspects `TARGET_ADDR`. If the detour opcode `jmp qword ptr [rip+0]` has been overwritten by original code, the watchdog logs `[CAMERA WATCHDOG] patch lost at 0x...; re-installing detour` and atomically rebuilds and re-injects the trampoline.

---

## 4. Win32 Loose-File Redirection (`CreateFileW`)

The hook can redirect a file request only when the game opens that path through the intercepted Win32 API:

1. **Explicit root indexing**: only active `cpk.root` entries are indexed. This makes enable/disable and priority deterministic.
2. **3-Level Resolution Engine**:
   - **Level 1 (Exact Match)**: Direct $O(1)$ HashMap lookup on normalized path.
   - **Level 2 (Suffix Subpath Match)**: Suffix slice lookup for absolute/relative game paths.
   - **Level 3 (Basename Fallback Match)**: Matches loose filenames directly. Disabled by default because it can hijack any file that merely shares a name; observed traffic so far was only self-redirects. Enable with `[LIVE_CPK] basename_fallback = 1`.
3. **Win32 API Detour**: Intercepts `kernel32!CreateFileW` via `retour::GenericDetour`, substituting game requests with disk-resident mod assets.

### IoStore limitation

Most UE4.26 assets are read as package chunks from `.utoc/.ucas`, not opened as loose `.uasset/.uexp/.ubulk` files. Seeing a virtual asset path in memory or installing the Win32 hook does not prove an override. Package replacement requires a valid cooked IoStore container and a mount/deploy mechanism; that work remains separate from this loose-file VFS.

### IoStore deploy conventions (verified on disk)

The supported deployment route bypasses this limitation entirely: UE4 mounts every
container found in `PesConsole/Content/Paks/~mods` at launch. Two naming regimes
apply, one per folder:

| Folder | Naming | Owner |
|---|---|---|
| `PesConsole/Content/Paks/` | strict `pcNNNN_console_win_P.pak` numbering | game patches only |
| `PesConsole/Content/Paks/~mods/` | free custom names with `_P` patch suffix | mod containers |

Real-world triplets already present in `~mods` (`EvoMod_BASE_P`,
`RealGrade_Toriga_P`, ...) each consist of a tiny mount-stub `.pak`, a `.utoc`
table and the bulk `.ucas`. Sider's **Build Zen Triplet** reproduces exactly
this shape via `retoc to-zen --version UE4_26` + `stub_template.pak`, and the
Mods-page `~mods` table manages them (disable = rename with a `.disabled`
suffix, which the pak scanner ignores).
