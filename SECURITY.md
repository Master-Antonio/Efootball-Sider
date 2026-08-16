# Security & Fair-Play Policy

## 1. Supported Versions

| Mod Studio Version | Supported | Notes |
| :--- | :---: | :--- |
| 0.5.x (Current) | :white_check_mark: | Native Rust DXGI proxy & PySide6 Studio |
| < 0.5.0 | :x: | Legacy / Deprecated builds |

---

## 2. Fair-Play & Anti-Cheat Compliance

eFootball Mod Studio is developed strictly as an **offline modding studio, visual enhancement engine, and educational reverse-engineering framework**.

### Core Fair-Play Principles:
- **Zero Competitive Exploits**: Mod Studio contains no aimbots, no network lag-switchers, no gameplay assistance, and no micro-transaction / coin bypasses.
- **Offline / Local Matchmaking Only**: Mod Studio must **NOT** be used in competitive online matchmaking (such as eFootball League, ranked PvP events, or official tournament modes).
- **Anti-Cheat Warning**: eFootball uses client/server integrity monitoring and anti-cheat components (such as Easy Anti-Cheat - EAC). Executing memory detours or DLL injection during online sessions directly violates Konami's Terms of Service and will trigger anti-cheat counter-measures, resulting in **permanent account bans**.
- **No Crack / No Bypass**: Mod Studio does not bypass game DRM, anti-tamper, or ownership verifications. A legitimate game installation on Steam is strictly required.

---

## 3. Binary Safety & Native Hooking Guarantees

Because Mod Studio runs inside the game process via a native `dxgi.dll` proxy, we enforce strict user-mode safety standards:

1. **Ring 3 Only**: Mod Studio operates entirely in user-mode space. It installs no kernel drivers, no rootkits, and requests no elevated administrator privileges during gameplay.
2. **x64 ABI Register Preservation**: All native inline detours in `rust_sider/src/camera.rs` strictly preserve:
   - 16-byte stack alignment (`RSP & -16`)
   - General-purpose registers (`RAX` through `R15`)
   - CPU status flags (`pushfq` / `popfq`)
   - Floating-point / SIMD vector registers (`XMM0` through `XMM5` via `movups`)
3. **Fail-Safe Trampolines**: If a game patch alters memory signatures, Mod Studio detours fail closed safely: hooks stay uninstalled and log diagnostic details without crashing the host process.
4. **Isolated File Operations**: Database extractions and repacking operate only on local working copies under `.workspace/` and generate explicit `.cpk.bak` backups before modifying game files.

---

## 4. Reporting a Vulnerability

If you discover a memory safety defect, buffer overflow, arbitrary code execution vector, or security issue in Mod Studio:

1. **Do not create a public GitHub Issue.**
2. Send a responsible disclosure report directly to the repository maintainer (`@Master-Antonio`) via private GitHub security advisory or email.
3. Please include:
   - Operating system and Windows build number.
   - Mod Studio commit hash and version.
   - Exact steps to reproduce the issue, with crash logs or memory dump (F10) if applicable.
4. Maintainers will review the submission within 48 hours and work with you on a patch and disclosure schedule.
