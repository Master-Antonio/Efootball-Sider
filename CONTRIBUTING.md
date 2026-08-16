# Contributing to eFootball Mod Studio

Thank you for your interest in contributing to **eFootball Mod Studio**! We welcome bug reports, feature suggestions, reverse-engineering discoveries, and pull requests from the community.

Please take a few moments to review this guide before submitting code or research.

---

## 1. Development Setup

### Prerequisites
- **OS**: Windows 10 or Windows 11 (x64)
- **Rust Toolchain**: 1.75 or newer (`rustup default stable`)
- **Python**: 3.11 or 3.12 (64-bit)
- **Git**: configured with line ending handling (`core.autocrlf=true` recommended on Windows)

### Step-by-Step Environment Setup

1. **Fork and clone the repository**:
   ```powershell
   git clone https://github.com/<your-username>/Efootball-Sider.git
   Set-Location Efootball-Sider
   ```

2. **Configure Python virtual environment**:
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   python -m pip install --upgrade pip
   python -m pip install -r requirements.txt
   python -m pip install ruff
   ```

3. **Build the native Rust proxy DLL (`dxgi.dll`)**:
   ```powershell
   Set-Location rust_sider
   cargo test
   cargo build --release
   Set-Location ..
   ```

4. **Launch the Studio GUI**:
   ```powershell
   python -m ui
   ```

---

## 2. Git Branching & Workflow

We follow standard GitHub flow:

1. Always branch off `main`:
   ```powershell
   git checkout main
   git pull origin main
   git checkout -b <type>/<short-description>
   ```

2. Branch naming conventions:
   - `feat/<feature-name>`: New functionality (e.g. `feat/player-appearance-parser`)
   - `fix/<bug-name>`: Bug fixes (e.g. `fix/vfs-case-sensitivity`)
   - `docs/<topic>`: Documentation enhancements (e.g. `docs/camera-mapping-protocol`)
   - `re/<topic>`: Reverse engineering findings (e.g. `re/dt870-assignment-v3`)
   - `refactor/<target>`: Code structure refactoring

---

## 3. Commit Message Standards (Conventional Commits)

Commit messages must adhere to the [Conventional Commits](https://www.conventionalcommits.org/) specification:

```text
<type>(<scope>): <short imperative summary>

[optional detailed body]
```

### Recognized Types:
- `feat`: A new feature (e.g. `feat(camera): add Plan B memory scanner`)
- `fix`: A bug fix (e.g. `fix(scripts): guard content folder copy in build_release`)
- `docs`: Documentation updates (e.g. `docs: update architecture reference for camera detours`)
- `refactor`: Code reorganization with no behavioral change
- `test`: Adding or modifying automated unit tests
- `perf`: Performance optimizations
- `ci`: GitHub Actions workflows or build automation scripts

---

## 4. Verification & Testing Checklist

Before opening a pull request, run the full automated test and linting suite:

### 1. Rust Native Core Tests
```powershell
Set-Location rust_sider
cargo test
cargo clippy -- -D warnings
Set-Location ..
```

### 2. Python Automated Unit Tests
```powershell
python -m unittest discover -s tests -v
```

### 3. Code Style & Linting
```powershell
ruff check ui tests scripts
ruff format --check ui tests scripts
```

### 4. Headless UI Screenshot Verification
When altering Qt UI components or pages, verify that offscreen rendering produces clean frames without crashing:
```powershell
$env:QT_QPA_PLATFORM="offscreen"
python -m ui --screenshot .workspace\ui\ci-smoke.png --page <affected_page> --width 1280 --height 800
Remove-Item env:QT_QPA_PLATFORM
```

---

## 5. Reverse Engineering & Database Research Guidelines

Contributions uncovering new game memory layouts, AOB signatures, or file encryption structures must include:

1. **Game Version & Executable Build**: Specify exact patch version (e.g., eFootball v6.1.0 Steam x64).
2. **Reproducible Offsets & Signatures**: Document RVA offsets, memory protection attributes, and disassembly context.
3. **Telemetry & Dump Proof**: Attach F9 telemetry logs (`sider_rust.log`) or F10 component memory snapshots (`camera_dumps/`).
4. **Non-Breaking Invariants**: Database parser updates must preserve round-trip parity (`unpack → pack → unpack` byte matching).

---

## 6. Architecture & Code Design Rules

- **Strict UI Decoupling**: Keep UI widgets (`ui/widgets/`) completely decoupled from binary logic (`ui/core/`) and filesystem services (`ui/services/`).
- **Non-Blocking GUI**: All file extractions, memory scans, and long operations must be encapsulated within `TaskWorker` running in Qt's thread pool. Never perform blocking I/O on the main GUI thread.
- **Memory Safety in Rust**: Native detours must preserve x64 register state (GPRs, XMM registers, flags) and 16-byte stack alignment. Avoid unbounded pointers and wrap risky Win32 calls in structured validation guards.

---

## 7. Community & Code of Conduct

Participation in this project is governed by our [Code of Conduct](CODE_OF_CONDUCT.md). Please treat all contributors with respect and collaborate positively.
