from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERSION_MATCH = re.search(
    r'^__version__\s*=\s*["\']([^"\']+)["\']',
    (ROOT / "ui" / "__init__.py").read_text(encoding="utf-8"),
    re.MULTILINE,
)
if VERSION_MATCH is None:
    raise RuntimeError("Could not read the UI version")
VERSION = VERSION_MATCH.group(1)

WORK = ROOT / ".workspace" / "release"
DIST = ROOT / "dist"
ARCHIVE = DIST / "eFootball_Sider_Studio.zip"


def copy_tree(source: Path, destination: Path) -> None:
    shutil.copytree(
        source,
        destination,
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def stage_release() -> Path:
    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    built_dll = ROOT / "rust_sider" / "target" / "release" / "dxgi.dll"
    source_dll = built_dll if built_dll.is_file() else ROOT / "dxgi.dll"
    if not source_dll.is_file():
        raise FileNotFoundError("Build rust_sider before creating a release")

    for filename in (
        "Avvia_Sider_GUI.bat",
        "CONTRIBUTING.md",
        "Disinstalla_Sider.bat",
        "Installa_Sider_in_eFootball.bat",
        "LICENSE",
        "README.md",
        "Riavvia_eFootball_con_Sider.bat",
        "efootball_sider_gui.py",
        "pyproject.toml",
        "requirements.txt",
        "sider.ini",
    ):
        shutil.copy2(ROOT / filename, WORK / filename)
    shutil.copy2(source_dll, WORK / "dxgi.dll")
    copy_tree(ROOT / "ui", WORK / "ui")
    copy_tree(ROOT / "content", WORK / "content")
    copy_tree(ROOT / "docs", WORK / "docs")
    copy_tree(ROOT / "scripts", WORK / "scripts")

    manifest = {
        "name": "eFootball Sider Studio",
        "version": VERSION,
        "native_core": {"file": "dxgi.dll", "sha256": sha256(WORK / "dxgi.dll")},
    }
    (WORK / "release-manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return WORK


def write_archive(staged: Path) -> Path:
    DIST.mkdir(parents=True, exist_ok=True)
    if ARCHIVE.exists():
        ARCHIVE.unlink()
    with zipfile.ZipFile(ARCHIVE, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted(item for item in staged.rglob("*") if item.is_file()):
            relative = path.relative_to(staged).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return ARCHIVE


def main() -> int:
    archive = write_archive(stage_release())
    print(f"Created {archive} ({archive.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
