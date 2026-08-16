from __future__ import annotations

import configparser
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .paths import WorkspacePaths


@dataclass(frozen=True)
class CameraSettings:
    enabled: bool = True
    zoom: float = 0.82
    height: float = 1.32
    angle: float = -0.12
    fov: float = 50.0
    freecam_speed: float = 2.5


@dataclass(frozen=True)
class ModInfo:
    folder: str
    name: str
    category: str
    author: str
    version: str
    enabled: bool
    file_count: int
    size_bytes: int
    path: Path


MAX_ZIP_ENTRIES = 10_000
MAX_ZIP_FILE_SIZE = 1024 * 1024 * 1024  # 1 GiB
MAX_ZIP_TOTAL_SIZE = 4 * 1024 * 1024 * 1024  # 4 GiB


def _normalize_root(value: str) -> str:
    return value.strip().strip('"').strip("'").replace("/", "\\").lower().rstrip("\\")


def _read_section(path: Path, section_name: str) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    current = ""
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        if not line or line.startswith((";", "#")):
            continue
        if line.startswith("[") and line.endswith("]"):
            current = line[1:-1].strip().lower()
            continue
        if current == section_name.lower() and "=" in line:
            key, value = line.split("=", 1)
            values[key.strip().lower()] = value.strip().strip('"').strip("'")
    return values


def _update_section(path: Path, section_name: str, values: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines() if path.is_file() else []
    section_header = f"[{section_name}]"
    section_start = next(
        (index for index, line in enumerate(lines) if line.strip().lower() == section_header.lower()),
        None,
    )
    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append(section_header)
        lines.extend(f"{key} = {value}" for key, value in values.items())
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return

    section_end = next(
        (
            index
            for index in range(section_start + 1, len(lines))
            if lines[index].strip().startswith("[") and lines[index].strip().endswith("]")
        ),
        len(lines),
    )
    remaining = {key.lower(): (key, value) for key, value in values.items()}
    for index in range(section_start + 1, section_end):
        stripped = lines[index].strip()
        if not stripped or stripped.startswith((";", "#")) or "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip().lower()
        if key in remaining:
            display_key, value = remaining.pop(key)
            lines[index] = f"{display_key} = {value}"
    for display_key, value in remaining.values():
        lines.insert(section_end, f"{display_key} = {value}")
        section_end += 1
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class ConfigurationService:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def read_camera(self) -> CameraSettings:
        values = _read_section(self.paths.sider_ini, "camera")

        def number(key: str, default: float) -> float:
            try:
                return float(values.get(key, default))
            except (TypeError, ValueError):
                return default

        enabled = values.get("enabled", "1").lower() in {"1", "true", "yes", "on"}
        return CameraSettings(
            enabled=enabled,
            zoom=number("zoom", 0.82),
            height=number("height", 1.32),
            angle=number("angle", -0.12),
            fov=number("fov", 50.0),
            freecam_speed=number("freecam_speed", 2.5),
        )

    def save_camera(self, settings: CameraSettings) -> None:
        values = {
            "enabled": "1" if settings.enabled else "0",
            "zoom": f"{settings.zoom:.2f}",
            "height": f"{settings.height:.2f}",
            "angle": f"{settings.angle:.2f}",
            "fov": f"{settings.fov:.1f}",
            "freecam_speed": f"{settings.freecam_speed:.1f}",
        }
        _update_section(self.paths.sider_ini, "camera", values)
        game_ini = self.paths.game_bin / "sider.ini"
        if game_ini.is_file() and game_ini.resolve() != self.paths.sider_ini.resolve():
            _update_section(game_ini, "camera", values)

    def active_roots(self) -> set[str]:
        if not self.paths.sider_ini.is_file():
            return set()
        roots = set()
        for raw_line in self.paths.sider_ini.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if line.startswith((";", "#")) or "=" not in line:
                continue
            key, value = line.split("=", 1)
            if key.strip().lower() == "cpk.root":
                roots.add(_normalize_root(value))
        return roots

    def list_mods(self) -> list[ModInfo]:
        self.paths.content.mkdir(parents=True, exist_ok=True)
        active_roots = self.active_roots()
        mods = []
        for directory in sorted(
            (path for path in self.paths.content.iterdir() if path.is_dir()), key=lambda p: p.name.lower()
        ):
            metadata = self._read_mod_metadata(directory)
            files = [path for path in directory.rglob("*") if path.is_file()]
            relative_root = _normalize_root(f"content\\{directory.name}")
            catch_all_enabled = "content" in active_roots
            mods.append(
                ModInfo(
                    folder=directory.name,
                    name=metadata.get("name", directory.name.replace("_", " ")),
                    category=metadata.get("category", "General"),
                    author=metadata.get("author", "Unknown"),
                    version=metadata.get("version", "1.0"),
                    enabled=catch_all_enabled or relative_root in active_roots,
                    file_count=len(files),
                    size_bytes=sum(path.stat().st_size for path in files),
                    path=directory,
                )
            )
        return mods

    def set_mod_enabled(self, folder: str, enabled: bool) -> None:
        mod_path = (self.paths.content / folder).resolve()
        if self.paths.content.resolve() not in mod_path.parents or not mod_path.is_dir():
            raise ValueError(f"Invalid mod folder: {folder}")
        root_value = f"content\\{folder}"
        normalized = _normalize_root(root_value)
        if "content" in self.active_roots():
            if enabled:
                return
            raise ValueError(
                "The legacy catch-all cpk.root=content is active. Comment it out before disabling individual mods."
            )
        lines = self.paths.sider_ini.read_text(encoding="utf-8", errors="replace").splitlines()
        matched = False
        for index, raw_line in enumerate(lines):
            stripped = raw_line.strip()
            uncommented = stripped.lstrip(";#").strip()
            if "=" not in uncommented:
                continue
            key, value = uncommented.split("=", 1)
            if key.strip().lower() != "cpk.root" or _normalize_root(value) != normalized:
                continue
            lines[index] = f'cpk.root = "{root_value}"' if enabled else f'; cpk.root = "{root_value}"'
            matched = True
        if enabled and not matched:
            lines.extend(("", f'cpk.root = "{root_value}"'))
        self.paths.sider_ini.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def install_zip(self, archive_path: Path) -> ModInfo:
        if not archive_path.is_file():
            raise FileNotFoundError(archive_path)
        with tempfile.TemporaryDirectory(prefix="sider-mod-") as temp_name:
            temp_root = Path(temp_name).resolve()
            with zipfile.ZipFile(archive_path) as archive:
                infolist = archive.infolist()
                if len(infolist) > MAX_ZIP_ENTRIES:
                    raise ValueError(
                        f"Mod archive contains too many entries ({len(infolist)} > {MAX_ZIP_ENTRIES})"
                    )
                total_uncompressed = 0
                for info in infolist:
                    mode = (info.external_attr >> 16) & 0o170000
                    if mode == 0o120000:
                        raise ValueError("Mod archives may not contain symbolic links")
                    if info.file_size > MAX_ZIP_FILE_SIZE:
                        raise ValueError(
                            f"File exceeds maximum allowed size ({info.file_size} bytes): {info.filename}"
                        )
                    total_uncompressed += info.file_size
                    if total_uncompressed > MAX_ZIP_TOTAL_SIZE:
                        raise ValueError(f"Archive exceeds maximum total size quota: {info.filename}")
                    target = (temp_root / info.filename).resolve()
                    if temp_root != target and temp_root not in target.parents:
                        raise ValueError(f"Unsafe ZIP path: {info.filename}")
                archive.extractall(temp_root)

            children = [path for path in temp_root.iterdir() if path.name != "__MACOSX"]
            if len(children) == 1 and children[0].is_dir():
                source = children[0]
                folder = source.name
            else:
                folder = re.sub(r"[^A-Za-z0-9_.-]+", "_", archive_path.stem).strip("._") or "Imported_Mod"
                source = temp_root
            destination = self.paths.content / folder
            if destination.exists():
                raise FileExistsError(f"A mod named '{folder}' already exists")
            if source == temp_root:
                destination.mkdir(parents=True)
                for child in children:
                    shutil.move(str(child), destination / child.name)
            else:
                shutil.move(str(source), destination)

        return next(mod for mod in self.list_mods() if mod.folder == folder)

    def delete_mod(self, folder: str) -> None:
        mod_path = (self.paths.content / folder).resolve()
        if self.paths.content.resolve() not in mod_path.parents or not mod_path.is_dir():
            raise ValueError(f"Invalid mod folder: {folder}")
        self.set_mod_enabled(folder, False)
        shutil.rmtree(mod_path)

    @staticmethod
    def _read_mod_metadata(directory: Path) -> dict[str, str]:
        path = directory / "mod.ini"
        if not path.is_file():
            return {}
        parser = configparser.ConfigParser(strict=False)
        parser.read(path, encoding="utf-8")
        if parser.has_section("MOD"):
            return {key.lower(): value for key, value in parser.items("MOD")}
        return {}
