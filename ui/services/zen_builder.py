from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

EFOOTBALL_AES_KEY = "0x4552D45005DFE94964893F4925EC747D3D591401E060ED8B3D58BE5721C81295"


@dataclass(frozen=True)
class ZenBuildResult:
    success: bool
    mod_name: str
    pak_path: Path | None
    utoc_path: Path | None
    ucas_path: Path | None
    log_output: str


@dataclass(frozen=True)
class ContentPackageSyncInfo:
    folder_name: str
    container_base: str
    source_dir: Path
    is_compatible: bool
    needs_rebuild: bool
    status: str  # "Needs Rebuild", "Up to date", "Not Built", "Incompatible"
    source_mtime: float
    container_mtime: float | None


def get_container_base_name(folder_name: str) -> str:
    """Return the container base name for a given mod folder (e.g. MyMod -> MyMod_P)."""
    return folder_name if folder_name.endswith("_P") else f"{folder_name}_P"


def is_cooked_mod_dir(dir_path: Path) -> bool:
    """Return True if dir_path contains cooked Unreal assets (PesConsole/Content/...)."""
    if not dir_path.is_dir():
        return False
    pes_console = dir_path / "PesConsole"
    if pes_console.is_dir() and (pes_console / "Content").is_dir():
        return True
    try:
        for p in dir_path.iterdir():
            if p.is_dir() and p.name.lower() == "pesconsole":
                for c in p.iterdir():
                    if c.is_dir() and c.name.lower() == "content":
                        return True
    except OSError:
        pass
    return False


def get_directory_mtime(dir_path: Path) -> float:
    """Return the latest mtime among all files and directories in dir_path."""
    if not dir_path.exists():
        return 0.0
    latest = dir_path.stat().st_mtime
    try:
        for p in dir_path.rglob("*"):
            try:
                m = p.stat().st_mtime
                if m > latest:
                    latest = m
            except OSError:
                pass
    except OSError:
        pass
    return latest


def get_container_files(output_mods_dir: Path, container_base: str) -> list[Path]:
    """Find all existing container files (.pak, .utoc, .ucas, or .disabled) for base."""
    if not output_mods_dir.is_dir():
        return []
    files: list[Path] = []
    for ext in (".pak", ".utoc", ".ucas"):
        regular = output_mods_dir / f"{container_base}{ext}"
        disabled = output_mods_dir / f"{container_base}{ext}.disabled"
        if regular.is_file():
            files.append(regular)
        elif disabled.is_file():
            files.append(disabled)
    return files


def check_package_sync_info(
    source_dir: Path,
    output_mods_dir: Path,
) -> ContentPackageSyncInfo:
    """Determine alignment between loose content folder and compiled ~mods container."""
    folder_name = source_dir.name
    container_base = get_container_base_name(folder_name)
    compatible = is_cooked_mod_dir(source_dir)
    source_mtime = get_directory_mtime(source_dir)
    files = get_container_files(output_mods_dir, container_base)
    container_mtime = min((f.stat().st_mtime for f in files), default=None) if len(files) == 3 else None

    if not compatible:
        return ContentPackageSyncInfo(
            folder_name=folder_name,
            container_base=container_base,
            source_dir=source_dir,
            is_compatible=False,
            needs_rebuild=False,
            status="Incompatible",
            source_mtime=source_mtime,
            container_mtime=container_mtime,
        )

    if not files:
        return ContentPackageSyncInfo(
            folder_name=folder_name,
            container_base=container_base,
            source_dir=source_dir,
            is_compatible=True,
            needs_rebuild=True,
            status="Not Built",
            source_mtime=source_mtime,
            container_mtime=None,
        )

    if len(files) < 3:
        return ContentPackageSyncInfo(
            folder_name=folder_name,
            container_base=container_base,
            source_dir=source_dir,
            is_compatible=True,
            needs_rebuild=True,
            status="Needs Rebuild",
            source_mtime=source_mtime,
            container_mtime=None,
        )

    assert container_mtime is not None
    if source_mtime > container_mtime:
        return ContentPackageSyncInfo(
            folder_name=folder_name,
            container_base=container_base,
            source_dir=source_dir,
            is_compatible=True,
            needs_rebuild=True,
            status="Needs Rebuild",
            source_mtime=source_mtime,
            container_mtime=container_mtime,
        )

    return ContentPackageSyncInfo(
        folder_name=folder_name,
        container_base=container_base,
        source_dir=source_dir,
        is_compatible=True,
        needs_rebuild=False,
        status="Up to date",
        source_mtime=source_mtime,
        container_mtime=container_mtime,
    )


class ZenBuilderService:
    def __init__(self, retoc_exe: Path | None = None, stub_pak: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.retoc_exe = retoc_exe or (base_dir / "bin" / "retoc.exe")
        self.stub_pak = stub_pak or (base_dir / "bin" / "stub_template.pak")

    def is_available(self) -> bool:
        return self.retoc_exe.is_file() and self.stub_pak.is_file()

    def find_compatible_content_packages(self, content_dir: Path | str) -> list[Path]:
        """Return list of mod directories in content_dir containing cooked assets."""
        c_path = Path(content_dir)
        if not c_path.is_dir():
            return []
        return [
            entry
            for entry in sorted(c_path.iterdir(), key=lambda p: p.name.lower())
            if entry.is_dir() and is_cooked_mod_dir(entry)
        ]

    def get_content_packages(
        self,
        content_dir: Path | str,
        output_mods_dir: Path | str,
    ) -> list[ContentPackageSyncInfo]:
        """Scan content_dir and return synchronization metadata for every folder."""
        c_path = Path(content_dir)
        out_path = Path(output_mods_dir)
        if not c_path.is_dir():
            return []
        infos = []
        for entry in sorted(c_path.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir():
                infos.append(check_package_sync_info(entry, out_path))
        return infos

    def build_triplet(
        self,
        source_dir: Path,
        mod_name: str,
        output_mods_dir: Path,
    ) -> ZenBuildResult:
        if not self.retoc_exe.is_file():
            return ZenBuildResult(
                success=False,
                mod_name=mod_name,
                pak_path=None,
                utoc_path=None,
                ucas_path=None,
                log_output=f"retoc.exe non trovato in {self.retoc_exe}",
            )

        output_mods_dir.mkdir(parents=True, exist_ok=True)
        container_base = get_container_base_name(mod_name)
        out_utoc = output_mods_dir / f"{container_base}.utoc"
        out_ucas = output_mods_dir / f"{container_base}.ucas"
        out_pak = output_mods_dir / f"{container_base}.pak"

        # Remove previous .disabled triplet files if any exist to prevent duplicate states
        for ext in (".pak", ".utoc", ".ucas"):
            disabled_f = output_mods_dir / f"{container_base}{ext}.disabled"
            if disabled_f.exists():
                try:
                    disabled_f.unlink()
                except OSError:
                    pass

        cmd = [
            str(self.retoc_exe),
            "-a",
            EFOOTBALL_AES_KEY,
            "--override-container-header-version",
            "PreInitial",
            "to-zen",
            "-c",
            "Zlib",
            "--version",
            "UE4_26",
            str(source_dir),
            str(out_utoc),
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            output_log = f"STDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"

            if res.returncode != 0 or not out_utoc.exists():
                return ZenBuildResult(
                    success=False,
                    mod_name=mod_name,
                    pak_path=None,
                    utoc_path=None,
                    ucas_path=None,
                    log_output=f"Errore durante l'esecuzione di retoc:\n{output_log}",
                )

            # Copy companion .pak mount stub
            if self.stub_pak.exists():
                shutil.copyfile(self.stub_pak, out_pak)
            else:
                # Fallback: minimal stub pak
                out_pak.write_bytes(b"\x00" * 347)

            return ZenBuildResult(
                success=True,
                mod_name=mod_name,
                pak_path=out_pak if out_pak.exists() else None,
                utoc_path=out_utoc if out_utoc.exists() else None,
                ucas_path=out_ucas if out_ucas.exists() else None,
                log_output=output_log,
            )

        except Exception as exc:
            return ZenBuildResult(
                success=False,
                mod_name=mod_name,
                pak_path=None,
                utoc_path=None,
                ucas_path=None,
                log_output=f"Eccezione: {exc}",
            )

    def build_all_content_packages(
        self,
        content_dir: Path | str,
        output_mods_dir: Path | str,
        only_outdated: bool = False,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> list[ZenBuildResult]:
        """Compile compatible loose mods in content_dir into IoStore triplets in ~mods.

        If only_outdated is True, only packages that are missing or have been modified
        after the container triplet was compiled will be built.
        """
        c_path = Path(content_dir)
        out_path = Path(output_mods_dir)
        packages = self.get_content_packages(c_path, out_path)
        to_build = [pkg for pkg in packages if pkg.is_compatible and (not only_outdated or pkg.needs_rebuild)]

        results: list[ZenBuildResult] = []
        total = len(to_build)
        for idx, pkg in enumerate(to_build):
            if progress_callback:
                progress_callback(pkg.folder_name, idx + 1, total)
            res = self.build_triplet(pkg.source_dir, pkg.folder_name, out_path)
            results.append(res)
        return results

    def sync_loose_mods_to_paks(
        self,
        content_dir: Path | str,
        output_mods_dir: Path | str,
        only_outdated: bool = False,
        progress_callback: Callable[[str, int, int], None] | None = None,
    ) -> list[ZenBuildResult]:
        """One-click auto-sync loose cooked mods to ~mods containers."""
        return self.build_all_content_packages(
            content_dir=content_dir,
            output_mods_dir=output_mods_dir,
            only_outdated=only_outdated,
            progress_callback=progress_callback,
        )

    def extract_triplet(self, utoc_path: Path, output_dir: Path) -> tuple[bool, str]:
        if not self.retoc_exe.is_file():
            return False, f"retoc.exe non trovato in {self.retoc_exe}"

        cmd = [
            str(self.retoc_exe),
            "-a",
            EFOOTBALL_AES_KEY,
            "--override-container-header-version",
            "PreInitial",
            "to-legacy",
            str(utoc_path.parent),
            str(output_dir),
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=180,
            )
            return res.returncode == 0, f"{res.stdout}\n{res.stderr}"
        except Exception as exc:
            return False, str(exc)
