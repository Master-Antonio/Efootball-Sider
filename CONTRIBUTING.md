# Contributing to eFootball Sider by Toriga

Thank you for your interest in contributing to **eFootball Sider by Toriga**! We welcome bug reports, feature suggestions, database research contributions, and pull requests.

---

## 🛠️ Development Setup

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
   pip install -r requirements.txt
   ```

4. **Launch the Studio GUI**:
   ```bash
   python efootball_sider_gui.py
   ```

---

## 🔬 Submitting Database & Cipher Research

If you discover new file headers, record structures, or cipher constants for updated eFootball game patches (e.g. v6.x+):
1. Document the record byte stride, checksum / seed location, and bit offsets.
2. Provide test samples or reproducible offsets.
3. Update `wesys_cipher.py` with corresponding test assertions.

---

## 📜 Pull Request Guidelines

- Ensure your code adheres to standard PEP 8 naming and formatting conventions.
- Keep UI operations decoupled from memory scanning (use daemon threads with `root.after()` callbacks).
- Test all sorting, pagination, and file export operations before submitting a PR.
- Add clear and concise descriptions of the changes in your commit messages.

---

## ⚖️ Code of Conduct

Be respectful, open to constructive feedback, and collaborate positively with the PES/eFootball modding community.
