from __future__ import annotations

import shutil
import subprocess
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


class ZenBuilderService:
    def __init__(self, retoc_exe: Path | None = None, stub_pak: Path | None = None) -> None:
        base_dir = Path(__file__).resolve().parent.parent.parent
        self.retoc_exe = retoc_exe or (base_dir / "bin" / "retoc.exe")
        self.stub_pak = stub_pak or (base_dir / "bin" / "stub_template.pak")

    def is_available(self) -> bool:
        return self.retoc_exe.is_file() and self.stub_pak.is_file()

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
        container_base = f"{mod_name}_P"
        out_utoc = output_mods_dir / f"{container_base}.utoc"
        out_ucas = output_mods_dir / f"{container_base}.ucas"
        out_pak = output_mods_dir / f"{container_base}.pak"

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
