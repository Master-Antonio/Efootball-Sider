from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

DEFAULT_GAME_ROOTS = (
    Path(r"A:\SteamLibrary\steamapps\common\eFootball"),
    Path(r"C:\Program Files (x86)\Steam\steamapps\common\eFootball"),
    Path(r"C:\Program Files\Steam\steamapps\common\eFootball"),
)


@dataclass(frozen=True)
class WorkspacePaths:
    repository: Path
    game_root: Path

    @classmethod
    def discover(cls) -> WorkspacePaths:
        repository = Path(__file__).resolve().parents[2]
        configured = os.environ.get("EFOOTBALL_GAME_DIR")
        candidates = (Path(configured),) if configured else DEFAULT_GAME_ROOTS
        game_root = next((path for path in candidates if path.is_dir()), candidates[0])
        return cls(repository=repository, game_root=game_root)

    @property
    def game_bin(self) -> Path:
        return self.game_root / "eFootball" / "Binaries" / "Win64"

    @property
    def game_cpk(self) -> Path:
        return self.game_root / "cpk"

    @property
    def live_database_cpk(self) -> Path:
        return self.game_cpk / "dt870_console_win.cpk"

    @property
    def content(self) -> Path:
        return self.repository / "content"

    @property
    def sider_ini(self) -> Path:
        return self.repository / "sider.ini"

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

    def ensure_workspace(self) -> None:
        self.content.mkdir(parents=True, exist_ok=True)
        self.database_workspace.mkdir(parents=True, exist_ok=True)
        self.ui_artifacts.mkdir(parents=True, exist_ok=True)
