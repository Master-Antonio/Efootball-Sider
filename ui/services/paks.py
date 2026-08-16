from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .zen_builder import ZenBuilderService, ZenBuildResult

DISABLED_SUFFIX = ".disabled"
CONTAINER_EXTS = {".pak", ".utoc", ".ucas"}


@dataclass(frozen=True)
class PakModInfo:
    """A compiled IoStore container triplet living in PesConsole/Content/Paks/~mods."""

    base: str
    files: tuple[Path, ...]
    enabled: bool
    size_bytes: int
    mtime: float = 0.0
    sync_status: str = ""


class PakModService:
    """Manages compiled ~mods containers.

    The game mounts every *.pak/*.utoc/*.ucas inside PesConsole/Content/Paks/~mods
    automatically (UE4 patch-pak behaviour), so installing a mod means putting its
    triplet there and disabling means renaming the files with a .disabled suffix,
    which UE4 ignores.
    """

    def __init__(self, mods_dir: Path | str) -> None:
        self.mods_dir = Path(mods_dir)

    def _scan_files(self) -> dict[tuple[str, bool], list[Path]]:
        groups: dict[tuple[str, bool], list[Path]] = {}
        if not self.mods_dir.is_dir():
            return groups
        for entry in sorted(self.mods_dir.iterdir()):
            if not entry.is_file():
                continue
            name = entry.name
            enabled = True
            if name.endswith(DISABLED_SUFFIX):
                enabled = False
                name = name[: -len(DISABLED_SUFFIX)]
            stem_ext = Path(name).suffix.lower()
            if stem_ext not in CONTAINER_EXTS:
                continue
            base = name[: -len(stem_ext)]
            groups.setdefault((base, enabled), []).append(entry)
        # merge same base across states is unnecessary: a base exists in one state only
        return groups

    def list_pak_mods(self) -> list[PakModInfo]:
        infos: list[PakModInfo] = []
        for (base, enabled), files in self._scan_files().items():
            mtime = min((f.stat().st_mtime for f in files), default=0.0)
            infos.append(
                PakModInfo(
                    base=base,
                    files=tuple(files),
                    enabled=enabled,
                    size_bytes=sum(f.stat().st_size for f in files),
                    mtime=mtime,
                )
            )
        return sorted(infos, key=lambda info: info.base.lower())

    def get_container_files(self, base: str) -> list[Path]:
        """Return all files (.pak, .utoc, .ucas) matching container base."""
        for (group_base, _enabled), files in self._scan_files().items():
            if group_base == base:
                return files
        return []

    def get_container_mtime(self, base: str) -> float | None:
        """Return the oldest file timestamp of the container triplet, or None if incomplete."""
        files = self.get_container_files(base)
        if not files or len(files) < 3:
            return None
        return min(f.stat().st_mtime for f in files)

    def is_container_outdated(self, base: str, source_dir: Path | str) -> bool:
        """Return True if source mod directory is newer than compiled container or container is missing."""
        source_path = Path(source_dir)
        if not source_path.exists():
            return False
        container_mtime = self.get_container_mtime(base)
        if container_mtime is None:
            return True
        from .zen_builder import get_directory_mtime

        source_mtime = get_directory_mtime(source_path)
        return source_mtime > container_mtime

    def is_compatible_package(self, path: Path | str) -> bool:
        """Return True if path contains cooked Unreal assets (PesConsole/Content/...)."""
        from .zen_builder import is_cooked_mod_dir

        return is_cooked_mod_dir(Path(path))

    def check_sync_status(self, content_dir: Path | str) -> dict[str, str]:
        """Return a mapping of mod folder names to their synchronization status."""
        from .zen_builder import ZenBuilderService

        builder = ZenBuilderService()
        packages = builder.get_content_packages(Path(content_dir), self.mods_dir)
        return {pkg.folder_name: pkg.status for pkg in packages}

    def build_all_content_packages(
        self,
        content_dir: Path | str,
        zen_builder: ZenBuilderService | None = None,
        only_outdated: bool = False,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> list[ZenBuildResult]:
        """Compile and sync loose mod packages from content_dir to this mods_dir."""
        from .zen_builder import ZenBuilderService

        builder = zen_builder or ZenBuilderService()
        return builder.build_all_content_packages(
            content_dir=Path(content_dir),
            output_mods_dir=self.mods_dir,
            only_outdated=only_outdated,
            progress_callback=progress_callback,
        )

    def sync_loose_mods_to_paks(
        self,
        content_dir: Path | str,
        zen_builder: ZenBuilderService | None = None,
        only_outdated: bool = False,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> list[ZenBuildResult]:
        """One-click auto-sync loose mods into ~mods IoStore containers."""
        return self.build_all_content_packages(
            content_dir=content_dir,
            zen_builder=zen_builder,
            only_outdated=only_outdated,
            progress_callback=progress_callback,
        )

    def set_enabled(self, base: str, enabled: bool) -> None:
        target = None
        for (group_base, group_enabled), files in self._scan_files().items():
            if group_base == base:
                target = (group_enabled, files)
                break
        if target is None:
            raise FileNotFoundError(f"Container not found: {base}")
        current_enabled, files = target
        if current_enabled == enabled:
            return
        for path in files:
            if enabled:
                new_path = path.with_name(path.name[: -len(DISABLED_SUFFIX)])
            else:
                new_path = path.with_name(path.name + DISABLED_SUFFIX)
            os.replace(path, new_path)

    def delete(self, base: str) -> None:
        target = None
        for (group_base, _enabled), files in self._scan_files().items():
            if group_base == base:
                target = files
                break
        if target is None:
            raise FileNotFoundError(f"Container not found: {base}")
        for path in target:
            path.unlink()

    def open_folder(self) -> None:
        os.startfile(self.mods_dir)  # type: ignore[attr-defined]
