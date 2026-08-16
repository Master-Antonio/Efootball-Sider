from __future__ import annotations

import hashlib
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import psutil

from .paths import WorkspacePaths


@dataclass(frozen=True)
class GameStatus:
    installed: bool
    running: bool
    pid: int | None
    dll_installed: bool
    dll_current: bool
    config_installed: bool
    live_cpk_found: bool
    mod_count: int


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class GameService:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    @staticmethod
    def process() -> psutil.Process | None:
        for process in psutil.process_iter(("pid", "name")):
            try:
                if process.info["name"] and process.info["name"].lower() == "efootball.exe":
                    return process
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                continue
        return None

    def status(self) -> GameStatus:
        process = self.process()
        source_dll = self.paths.built_dll if self.paths.built_dll.is_file() else self.paths.root_dll
        mods = (
            [path for path in self.paths.content.iterdir() if path.is_dir()]
            if self.paths.content.is_dir()
            else []
        )
        return GameStatus(
            installed=self.paths.game_bin.is_dir(),
            running=process is not None,
            pid=process.pid if process else None,
            dll_installed=self.paths.game_dll.is_file(),
            dll_current=_sha256(source_dll) is not None
            and _sha256(source_dll) == _sha256(self.paths.game_dll),
            config_installed=(self.paths.game_bin / "sider.ini").is_file(),
            live_cpk_found=self.paths.live_database_cpk.is_file(),
            mod_count=len(mods),
        )

    def sync(self) -> GameStatus:
        if self.process() is not None:
            raise RuntimeError("Close eFootball before syncing the proxy DLL")
        if not self.paths.game_bin.is_dir():
            raise FileNotFoundError(f"Game directory not found: {self.paths.game_bin}")
        source_dll = self.paths.built_dll if self.paths.built_dll.is_file() else self.paths.root_dll
        if not source_dll.is_file():
            raise FileNotFoundError("Build rust_sider before syncing")
        if source_dll.resolve() != self.paths.game_dll.resolve():
            shutil.copy2(source_dll, self.paths.game_dll)
        dest_ini = self.paths.game_bin / "sider.ini"
        if self.paths.sider_ini.resolve() != dest_ini.resolve():
            shutil.copy2(self.paths.sider_ini, dest_ini)
        return self.status()

    @staticmethod
    def open_path(path: Path) -> None:
        if not path.exists():
            raise FileNotFoundError(path)
        os.startfile(path)  # type: ignore[attr-defined]

    @staticmethod
    def launch() -> None:
        os.startfile("steam://rungameid/1665460")  # type: ignore[attr-defined]

    def read_log_tail(self, line_count: int = 300) -> str:
        path = self.paths.rust_log
        if not path.is_file():
            return "No native log has been written yet."
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-line_count:])
