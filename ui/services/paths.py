from __future__ import annotations

import json
import os
import winreg
from dataclasses import dataclass
from pathlib import Path


def auto_detect_game_root() -> Path | None:
    libraries: list[Path] = []
    steam_path: Path | None = None

    # 1. Check Windows Registry for Steam
    for hkey, subkey in [
        (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
    ]:
        try:
            with winreg.OpenKey(hkey, subkey) as key:
                val, _ = winreg.QueryValueEx(key, "SteamPath")
                if val and Path(val).is_dir():
                    steam_path = Path(val)
                    libraries.append(steam_path)
                    break
        except Exception:
            pass

    # 2. Parse libraryfolders.vdf
    if steam_path:
        vdf = steam_path / "steamapps" / "libraryfolders.vdf"
        if vdf.is_file():
            try:
                text = vdf.read_text(encoding="utf-8", errors="ignore")
                for line in text.splitlines():
                    if "path" in line.lower():
                        parts = [p.strip('"\t ') for p in line.split('"') if p.strip('"\t ')]
                        for part in parts:
                            if part.lower() != "path":
                                p = Path(part)
                                if p.is_dir() and p not in libraries:
                                    libraries.append(p)
            except Exception:
                pass

    # 3. Check standard drive patterns
    for drive in "CDEFGHIJKLMNOPQRSTUVWXYZAB":
        for pattern in [
            f"{drive}:\\SteamLibrary",
            f"{drive}:\\Program Files (x86)\\Steam",
            f"{drive}:\\Program Files\\Steam",
            f"{drive}:\\Games\\Steam",
        ]:
            d = Path(pattern)
            if d.is_dir() and d not in libraries:
                libraries.append(d)

    # Search for eFootball within all discovered libraries
    for lib in libraries:
        candidates = [
            lib / "steamapps" / "common" / "eFootball",
            lib / "common" / "eFootball",
            lib / "eFootball",
        ]
        for candidate in candidates:
            if candidate.is_dir():
                exe = candidate / "eFootball" / "Binaries" / "Win64" / "eFootball.exe"
                if exe.is_file():
                    return candidate

    return None


@dataclass
class WorkspacePaths:
    repository: Path
    game_root: Path
    custom_content: Path | None = None

    @classmethod
    def discover(cls) -> WorkspacePaths:
        repository = Path(__file__).resolve().parents[2]
        settings_file = repository / ".workspace" / "settings.json"
        
        saved_game_root = None
        saved_content = None
        if settings_file.is_file():
            try:
                data = json.loads(settings_file.read_text(encoding="utf-8"))
                if data.get("game_root"):
                    p = Path(data["game_root"])
                    if p.is_dir():
                        saved_game_root = p
                if data.get("content_root"):
                    p = Path(data["content_root"])
                    saved_content = p
            except Exception:
                pass

        if not saved_game_root:
            configured = os.environ.get("EFOOTBALL_GAME_DIR")
            if configured and Path(configured).is_dir():
                saved_game_root = Path(configured)
            else:
                saved_game_root = auto_detect_game_root() or Path(r"A:\SteamLibrary\steamapps\common\eFootball")

        return cls(
            repository=repository,
            game_root=saved_game_root,
            custom_content=saved_content,
        )

    def save_settings(self, game_root: Path | None = None, content_root: Path | None = None) -> None:
        settings_file = self.repository / ".workspace" / "settings.json"
        settings_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = {
            "game_root": str(game_root or self.game_root),
            "content_root": str(content_root or self.content),
        }
        settings_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    @property
    def game_bin(self) -> Path:
        return self.game_root / "eFootball" / "Binaries" / "Win64"

    @property
    def game_exe(self) -> Path:
        return self.game_bin / "eFootball.exe"

    @property
    def game_cpk(self) -> Path:
        return self.game_root / "cpk"

    @property
    def game_mods_paks(self) -> Path:
        return self.game_root / "PesConsole" / "Content" / "Paks" / "~mods"

    @property
    def base_database_cpk(self) -> Path:
        return self.game_cpk / "dt200_console_all.cpk"

    @property
    def live_database_cpk(self) -> Path:
        return self.game_cpk / "dt870_console_win.cpk"

    @property
    def content(self) -> Path:
        if self.custom_content:
            return self.custom_content
        return self.game_root / "content"

    @property
    def game_content(self) -> Path:
        return self.game_root / "content"

    @property
    def sider_ini(self) -> Path:
        return self.repository / "sider.ini"

    @property
    def game_sider_ini(self) -> Path:
        return self.game_bin / "sider.ini"

    @property
    def root_dll(self) -> Path:
        return self.repository / "dxgi.dll"

    @property
    def built_dll(self) -> Path:
        return self.repository / "rust_sider" / "target" / "release" / "dxgi.dll"

    @property
    def game_dll(self) -> Path:
        return self.game_bin / "dxgi.dll"

    @property
    def database_workspace(self) -> Path:
        return self.repository / ".workspace" / "pesdb"

    @property
    def ui_artifacts(self) -> Path:
        return self.repository / ".workspace" / "ui"

    @property
    def rust_log(self) -> Path:
        candidates = (self.game_bin / "sider_rust.log", self.repository / "sider_rust.log")
        return next((path for path in candidates if path.exists()), candidates[0])

    @property
    def native_decoder_candidates(self) -> tuple[Path, ...]:
        return self.root_dll, self.built_dll, self.game_dll

    def is_game_valid(self) -> bool:
        return self.game_exe.is_file() and self.game_cpk.is_dir()

    def is_dll_installed(self) -> bool:
        return self.game_dll.is_file()

    def ensure_workspace(self) -> None:
        self.content.mkdir(parents=True, exist_ok=True)
        self.database_workspace.mkdir(parents=True, exist_ok=True)
        self.ui_artifacts.mkdir(parents=True, exist_ok=True)
