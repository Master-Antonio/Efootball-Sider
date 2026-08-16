# Contributing to eFootball Sider Studio

Thank you for your interest in contributing to **eFootball Sider by Toriga**! We welcome bug reports, feature suggestions, database research contributions, and pull requests.

---

## Development setup

1. **Clone the repository**:
   ```bash
   git clone https://github.com/Master-Antonio/Efootball-Sider.git
   cd Efootball-Sider
   ```

2. **Set up a Python virtual environment** (recommended):
   ```bash
   python -m venv venv
   # Windows PowerShell
   .\venv\Scripts\Activate.ps1
   # Windows CMD
   .\venv\Scripts\activate.bat
   ```

3. **Install dependencies**:
   ```bash
   python -m pip install -r requirements.txt
   ```

4. **Launch the Studio GUI**:
   ```bash
   python -m ui
   ```

---

## Database and cipher research

If you discover new file headers, record structures, or cipher constants for updated eFootball game patches (e.g. v6.x+):
1. Document the record byte stride, checksum / seed location, and bit offsets.
2. Provide test samples or reproducible offsets.
3. Update `ui/core/wesys.py` or `ui/core/pesdb.py` with corresponding test assertions.

---

## Pull request guidelines

- Ensure your code adheres to standard PEP 8 naming and formatting conventions.
- Keep UI operations decoupled from game and file services. Long operations must use `TaskWorker`.
- Keep pages under `ui/pages`, reusable widgets under `ui/widgets`, and binary logic under `ui/core`.
- Run `python -m unittest discover -s tests` and `cargo test` in `rust_sider`.
- Render at least one affected page with `python -m ui --screenshot <path> --page <name>`.
- Add clear and concise descriptions of the changes in your commit messages.

---

## Code of conduct

Be respectful, open to constructive feedback, and collaborate positively with the PES/eFootball modding community.
