## Description
<!-- Provide a concise summary of the changes and the rationale behind them. -->

## Type of Change
- [ ] `feat`: A new feature (e.g. new database table parser, new camera hook mode)
- [ ] `fix`: A bug fix or crash resolution
- [ ] `docs`: Documentation updates or corrections
- [ ] `refactor`: Code reorganization with no behavioral change
- [ ] `perf`: Performance improvement (e.g. scanner speedup, memory reduction)
- [ ] `test`: Adding or updating test cases
- [ ] `ci`: GitHub Actions or release script changes

## Verification & QA Checklist
- [ ] **Rust Core**: Ran `cargo test` in `rust_sider/` and all 15 tests passed.
- [ ] **Python Core**: Ran `python -m unittest discover -s tests -v` and all tests passed (43+ tests).
- [ ] **Linting & Style**: Code passes `ruff check ui tests scripts` and `ruff format --check ui tests scripts`.
- [ ] **UI Integrity**: If modifying PySide6 UI, verified offscreen screenshot rendering via `python -m ui --screenshot .workspace/ui/pr-smoke.png --page <affected_page>`.
- [ ] **Thread Safety**: Verified that no blocking I/O or heavy memory scans run on the Qt GUI main thread.
- [ ] **Reverse Engineering Evidence**: If adding or altering offsets, provided game version, memory address/RVA, and telemetry log confirmation.

## Related Issues
Fixes #
