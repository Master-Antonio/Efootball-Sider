"""Compatibility launcher for the modular Qt Sider Studio.

New integrations should import from ``ui`` directly. The re-exports below keep
older scripts working while the public project transitions away from the former
single-file Tkinter application.
"""

from pathlib import Path

from ui.app import main
from ui.core.pesdb import (
    ASSIGNMENT_COLUMNS,
    ASSIGNMENT_RECORD_SIZE,
    PLAYER_COLUMNS,
    PLAYER_LAYOUTS,
    TEAM_COLUMNS,
    TEAM_RECORD_SIZE,
    collect_player_ids,
    detect_assignment_layout,
    detect_player_layout,
    parse_player_assignment_bin,
    parse_player_bin,
    parse_team_bin,
    parse_team_color_bin,
    replace_team_squad,
    validate_player_assignment_bin,
)
from ui.core.wesys import (
    CURRENT_WESYS_KEYS,
    LEGACY_WESYS_KEYS,
    WesysError,
    crypt_current_payload,
    is_wesys_container,
    pack_wesys_container,
    unpack_wesys_fast,
    unpack_wesys_payload,
)
from ui.services.database import DatabaseService
from ui.services.paths import WorkspacePaths


def native_rust_unpack_wesys(data: bytes) -> bytes:
    paths = WorkspacePaths.discover()
    return unpack_wesys_fast(data, paths.native_decoder_candidates)


def extract_pesdb_from_cpk(cpk_path, output_dir) -> dict:
    paths = WorkspacePaths.discover()
    bundle = DatabaseService(paths).extract_bundle(Path(cpk_path), Path(output_dir))
    return bundle.manifest


__all__ = [
    "ASSIGNMENT_COLUMNS",
    "ASSIGNMENT_RECORD_SIZE",
    "CURRENT_WESYS_KEYS",
    "DatabaseService",
    "LEGACY_WESYS_KEYS",
    "PLAYER_COLUMNS",
    "PLAYER_LAYOUTS",
    "TEAM_COLUMNS",
    "TEAM_RECORD_SIZE",
    "WesysError",
    "WorkspacePaths",
    "collect_player_ids",
    "crypt_current_payload",
    "detect_assignment_layout",
    "detect_player_layout",
    "extract_pesdb_from_cpk",
    "is_wesys_container",
    "main",
    "native_rust_unpack_wesys",
    "pack_wesys_container",
    "parse_player_assignment_bin",
    "parse_player_bin",
    "parse_team_bin",
    "parse_team_color_bin",
    "replace_team_squad",
    "unpack_wesys_fast",
    "unpack_wesys_payload",
    "validate_player_assignment_bin",
]


if __name__ == "__main__":
    raise SystemExit(main())
