from __future__ import annotations

import csv
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from cricodecs import cpk

from ..core.pesdb import (
    ASSIGNMENT_COLUMNS,
    PLAYER_COLUMNS,
    TEAM_COLUMNS,
    collect_player_ids,
    parse_player_assignment_bin,
    parse_player_bin,
    parse_team_bin,
    validate_player_assignment_bin,
)
from ..core.wesys import pack_wesys_container, unpack_wesys_fast
from .paths import WorkspacePaths

PESDB_TARGETS = (
    "common/etc/pesdb/Player.bin",
    "common/etc/pesdb/PlayerAssignment.bin",
    "common/etc/pesdb/Team.bin",
)


@dataclass(frozen=True)
class DatabaseBundle:
    root: Path
    manifest: dict

    @property
    def decoded_root(self) -> Path:
        return self.root / "decoded" / "common" / "etc" / "pesdb"

    def decoded_path(self, filename: str) -> Path:
        return self.decoded_root / filename


ProgressCallback = Callable[[int, int, str], None]


class DatabaseService:
    def __init__(self, paths: WorkspacePaths) -> None:
        self.paths = paths

    def extract_live_bundle(
        self,
        output_dir: Path | None = None,
        progress: ProgressCallback | None = None,
    ) -> DatabaseBundle:
        return self.extract_bundle(
            self.paths.live_database_cpk,
            output_dir or self.paths.database_workspace / "live",
            progress,
        )

    def extract_bundle(
        self,
        cpk_path: Path,
        output_dir: Path,
        progress: ProgressCallback | None = None,
    ) -> DatabaseBundle:
        if not cpk_path.is_file():
            raise FileNotFoundError(f"CPK archive not found: {cpk_path}")

        archive = cpk.load(str(cpk_path))
        entries = {
            entry.full_path.replace("\\", "/").lower(): (index, entry)
            for index, entry in enumerate(archive.files)
        }
        missing = [path for path in PESDB_TARGETS if path.lower() not in entries]
        if missing:
            raise ValueError(f"CPK is missing required database entries: {', '.join(missing)}")

        output_dir = output_dir.resolve()
        decoded_files: dict[str, bytes] = {}
        file_manifest: dict[str, dict] = {}
        for step, archive_path in enumerate(PESDB_TARGETS, start=1):
            index, entry = entries[archive_path.lower()]
            if progress:
                progress(step - 1, len(PESDB_TARGETS), entry.filename)
            packed = bytes(archive.file_bytes(index))
            decoded = unpack_wesys_fast(packed, self.paths.native_decoder_candidates)
            decoded_files[entry.filename] = decoded

            relative = Path(*archive_path.split("/"))
            packed_path = output_dir / "packed" / relative
            decoded_path = output_dir / "decoded" / relative
            vanilla_path = output_dir / "vanilla" / relative
            packed_path.parent.mkdir(parents=True, exist_ok=True)
            decoded_path.parent.mkdir(parents=True, exist_ok=True)
            vanilla_path.parent.mkdir(parents=True, exist_ok=True)
            packed_path.write_bytes(packed)
            decoded_path.write_bytes(decoded)
            if not vanilla_path.exists():
                vanilla_path.write_bytes(decoded)

            file_manifest[entry.filename] = {
                "archive_index": index,
                "archive_path": archive_path,
                "packed_size": len(packed),
                "decoded_size": len(decoded),
                "packed_sha256": hashlib.sha256(packed).hexdigest(),
                "decoded_sha256": hashlib.sha256(decoded).hexdigest(),
            }

        players = parse_player_bin(decoded_files["Player.bin"])
        valid_player_ids = collect_player_ids(decoded_files["Player.bin"])
        teams = parse_team_bin(decoded_files["Team.bin"])
        team_ids = [record["team_id"] for record in teams]
        if any(current >= following for current, following in zip(team_ids, team_ids[1:], strict=False)):
            raise ValueError("Team.bin is not strictly ordered by team ID")
        valid_team_ids = set(team_ids)
        assignments = validate_player_assignment_bin(
            decoded_files["PlayerAssignment.bin"],
            valid_player_ids=valid_player_ids,
            valid_team_ids=valid_team_ids,
        )

        manifest = {
            "source_cpk": str(cpk_path.resolve()),
            "files": file_manifest,
            "player": {
                "layout": players[0]["layout"] if players else None,
                "record_size": players[0]["record_size"] if players else None,
                "record_count": len(players),
                "unique_player_count": len(valid_player_ids),
            },
            "assignment": assignments,
            "team": {
                "record_count": len(teams),
                "first_team_id": team_ids[0] if team_ids else None,
                "last_team_id": team_ids[-1] if team_ids else None,
            },
        }
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        if progress:
            progress(len(PESDB_TARGETS), len(PESDB_TARGETS), "Validated")
        return DatabaseBundle(root=output_dir, manifest=manifest)

    def load_bundle(self, root: Path | None = None) -> DatabaseBundle | None:
        root = root or self.paths.database_workspace / "live"
        manifest_path = root / "manifest.json"
        if not manifest_path.is_file():
            return None
        return DatabaseBundle(
            root=root,
            manifest=json.loads(manifest_path.read_text(encoding="utf-8")),
        )

    def load_records(self, bundle: DatabaseBundle, kind: str) -> tuple[list[dict], tuple[str, ...]]:
        normalized = kind.lower()
        if normalized == "players":
            return parse_player_bin(bundle.decoded_path("Player.bin").read_bytes()), PLAYER_COLUMNS
        if normalized == "assignments":
            return (
                parse_player_assignment_bin(bundle.decoded_path("PlayerAssignment.bin").read_bytes()),
                ASSIGNMENT_COLUMNS,
            )
        if normalized == "teams":
            return parse_team_bin(bundle.decoded_path("Team.bin").read_bytes()), TEAM_COLUMNS
        raise ValueError(f"Unknown database table: {kind}")

    def export_csv(self, records: list[dict], columns: tuple[str, ...], output_path: Path) -> None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", newline="", encoding="utf-8-sig") as stream:
            writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(records)

    def repack_and_deploy(
        self,
        bundle: DatabaseBundle,
        target_cpk: Path | None = None,
    ) -> int:
        import shutil

        targets = [target_cpk] if target_cpk else [
            self.paths.game_cpk / "dt870_console_win.cpk",
            self.paths.game_cpk / "dt200_console_all.cpk",
        ]

        total_replaced = 0
        for cpk_path in targets:
            if not cpk_path.is_file():
                continue

            bak_path = cpk_path.with_suffix(".cpk.bak")
            if not bak_path.exists():
                try:
                    shutil.copy2(cpk_path, bak_path)
                except Exception:
                    pass

            src_to_load = bak_path if bak_path.exists() else cpk_path
            try:
                archive = cpk.load(str(src_to_load))
                has_updates = False
                for idx, entry in enumerate(archive.files):
                    decoded_file = bundle.decoded_path(entry.filename)
                    if decoded_file.is_file():
                        raw_data = decoded_file.read_bytes()
                        packed_wesys = pack_wesys_container(raw_data, key_nibble=2, compression_level=1)
                        archive.replace_bytes(idx, packed_wesys)
                        total_replaced += 1
                        has_updates = True

                if has_updates:
                    temp_cpk = cpk_path.with_suffix(".cpk.tmp")
                    archive.save(str(temp_cpk))
                    try:
                        shutil.move(temp_cpk, cpk_path)
                    except Exception:
                        shutil.copy2(temp_cpk, cpk_path)
                        temp_cpk.unlink(missing_ok=True)
            except Exception as e:
                pass

        return total_replaced
