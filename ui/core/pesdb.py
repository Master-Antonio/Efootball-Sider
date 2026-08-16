from __future__ import annotations

import struct
from collections.abc import Iterable

TEAM_RECORD_SIZE = 1600
ASSIGNMENT_RECORD_SIZE = 24
PLAYER_LAYOUTS = ((392, 84), (400, 88))


def _strictly_increasing(values: Iterable[int]) -> bool:
    iterator = iter(values)
    try:
        previous = next(iterator)
    except StopIteration:
        return True
    for current in iterator:
        if current <= previous:
            return False
        previous = current
    return True


def _get_bits(value: int, bit_offset: int, width: int) -> int:
    return (value >> bit_offset) & ((1 << width) - 1)


def detect_player_layout(data: bytes) -> tuple[int, int]:
    if not data:
        return 400, 88
    matches = []
    for stride, name_offset in PLAYER_LAYOUTS:
        if len(data) % stride:
            continue
        player_ids = (struct.unpack_from("<Q", data, offset + 8)[0] for offset in range(0, len(data), stride))
        if _strictly_increasing(player_ids):
            matches.append((stride, name_offset))
    if len(matches) != 1:
        names = ", ".join(str(stride) for stride, _ in matches) or "none"
        raise ValueError(f"Player.bin layout is ambiguous (candidates: {names})")
    return matches[0]


def parse_player_bin(data: bytes) -> list[dict]:
    stride, name_offset = detect_player_layout(data)
    records = []
    for index, offset in enumerate(range(0, len(data), stride)):
        chunk = data[offset : offset + stride]
        packed = int.from_bytes(chunk, "little")

        names = []
        for name_index in range(5):
            start = name_offset + name_index * 61
            raw_name = chunk[start : start + 61].split(b"\x00", 1)[0]
            names.append(raw_name.decode("utf-8", errors="replace").strip())

        player_id = struct.unpack_from("<Q", chunk, 8)[0]
        raw_height = _get_bits(packed, 248, 8)
        raw_weight = _get_bits(packed, 280, 7)
        attacking_style_raw = _get_bits(packed, 372, 8)
        records.append(
            {
                "row": index + 1,
                "index": index,
                "offset": f"0x{offset:06X}",
                "record_size": stride,
                "layout": f"eFootball Player/{stride}",
                "native_player_id": struct.unpack_from("<Q", chunk, 0)[0],
                "player_id": player_id,
                "nationality_id": struct.unpack_from("<H", chunk, 41)[0] & 0x03FF,
                "height_cm": raw_height + 100 if stride == 392 else raw_height,
                "weight_kg": raw_weight + 30 if stride == 392 else raw_weight,
                "attacking_style": None if stride == 392 else attacking_style_raw,
                "attacking_style_raw": attacking_style_raw,
                "position_id": _get_bits(packed, 556, 4),
                "display_name": next((name for name in names if name), f"Player #{player_id}"),
                "name_1": names[0],
                "name_2": names[1],
                "name_3": names[2],
                "name_4": names[3],
                "name_5": names[4],
                "hex": chunk[:16].hex(" "),
            }
        )
    return records


def update_player_record(
    player_data: bytes,
    player_id: int,
    *,
    display_name: str | None = None,
    height_cm: int | None = None,
    weight_kg: int | None = None,
) -> bytes:
    stride, name_offset = detect_player_layout(player_data)
    records = parse_player_bin(player_data)
    match_index = next((i for i, r in enumerate(records) if r["player_id"] == player_id), None)
    if match_index is None:
        raise ValueError(f"Player ID {player_id} non trovato in Player.bin")

    out = bytearray(player_data)
    offset = match_index * stride

    if display_name is not None:
        name_bytes = display_name.strip().encode("utf-8")[:60] + b"\x00"
        for name_index in range(5):
            pos = offset + name_offset + name_index * 61
            out[pos : pos + 61] = name_bytes.ljust(61, b"\x00")

    if height_cm is not None or weight_kg is not None:
        chunk = out[offset : offset + stride]
        packed = int.from_bytes(chunk, "little")
        if height_cm is not None:
            raw_h = (height_cm - 100 if stride == 392 else height_cm) & 0xFF
            packed = (packed & ~(0xFF << 248)) | (raw_h << 248)
        if weight_kg is not None:
            raw_w = (weight_kg - 30 if stride == 392 else weight_kg) & 0x7F
            packed = (packed & ~(0x7F << 280)) | (raw_w << 280)
        out[offset : offset + stride] = packed.to_bytes(stride, "little")

    return bytes(out)


def collect_player_ids(player_data: bytes) -> set[int]:
    records = parse_player_bin(player_data)
    player_ids = [record["player_id"] for record in records]
    if not _strictly_increasing(player_ids):
        raise ValueError("Player.bin is not ordered by external player ID")
    return set(player_ids)


def detect_assignment_layout(data: bytes) -> str:
    if len(data) % ASSIGNMENT_RECORD_SIZE:
        raise ValueError("PlayerAssignment.bin is not aligned to 24-byte records")
    if not data:
        return "eFootball PlayerAssignment/v1"
    chunks = (
        data[offset : offset + ASSIGNMENT_RECORD_SIZE]
        for offset in range(0, len(data), ASSIGNMENT_RECORD_SIZE)
    )
    chunks = tuple(chunks)
    if all(chunk[20:24] == b"\x00" * 4 for chunk in chunks):
        return "eFootball PlayerAssignment/v2"
    if all(chunk[4:8] == b"\x00" * 4 and chunk[23] == 0 for chunk in chunks):
        return "eFootball PlayerAssignment/v1"
    raise ValueError("PlayerAssignment.bin layout is not recognized")


def parse_player_assignment_bin(data: bytes) -> list[dict]:
    layout = detect_assignment_layout(data)
    records = []
    for index, offset in enumerate(range(0, len(data), ASSIGNMENT_RECORD_SIZE)):
        chunk = data[offset : offset + ASSIGNMENT_RECORD_SIZE]
        if layout.endswith("/v2"):
            player_id_offset = 0
            player_id = struct.unpack_from("<Q", chunk, 0)[0]
            team_id = struct.unpack_from("<I", chunk, 8)[0]
            record_id = struct.unpack_from("<I", chunk, 12)[0]
            shirt_number_raw = chunk[16]
            sort_key = chunk[17]
            role_flags = struct.unpack_from("<H", chunk, 18)[0]
            role_mask = (role_flags >> 4) & 0x7F
            is_captain = bool(role_flags & (1 << 9))
        else:
            player_id_offset = 8
            record_id = struct.unpack_from("<I", chunk, 0)[0]
            player_id = struct.unpack_from("<Q", chunk, 8)[0]
            team_id = struct.unpack_from("<I", chunk, 16)[0]
            shirt_number_raw = chunk[20]
            sort_key = chunk[21]
            role_flags = chunk[22] & 0x3F
            role_mask = role_flags
            is_captain = bool(role_mask & 0x20)
        records.append(
            {
                "row": index + 1,
                "index": index,
                "offset": f"0x{offset:06X}",
                "layout": layout,
                "record_id": record_id,
                "player_id": player_id,
                "player_id_offset": player_id_offset,
                "player_id_hex": chunk[player_id_offset : player_id_offset + 8].hex(" "),
                "team_id": team_id,
                "shirt_number": shirt_number_raw + 1,
                "shirt_number_raw": shirt_number_raw,
                "sort_key": sort_key,
                "role_flags": role_flags,
                "role_mask": role_mask,
                "is_captain": is_captain,
            }
        )
    return records


def validate_player_assignment_bin(
    data: bytes,
    valid_player_ids: set[int] | None = None,
    valid_team_ids: set[int] | None = None,
) -> dict:
    records = parse_player_assignment_bin(data)
    layout = detect_assignment_layout(data)
    if not records:
        return {
            "layout": layout,
            "record_count": 0,
            "team_count": 0,
            "unique_player_count": 0,
            "warning_count": 0,
            "warnings": [],
        }

    for index in range(len(records)):
        chunk = data[index * 24 : (index + 1) * 24]
        invalid = (
            chunk[20:24] != b"\x00" * 4
            if layout.endswith("/v2")
            else chunk[4:8] != b"\x00" * 4 or chunk[23] != 0
        )
        if invalid:
            raise ValueError(f"Reserved assignment bytes are non-zero at record {index}")

    record_ids = [record["record_id"] for record in records]
    if len(record_ids) != len(set(record_ids)):
        raise ValueError("PlayerAssignment.bin contains duplicate record IDs")
    team_ids = [record["team_id"] for record in records]
    if any(current > following for current, following in zip(team_ids, team_ids[1:], strict=False)):
        raise ValueError("PlayerAssignment.bin is not ordered by team ID")

    teams: dict[int, list[dict]] = {}
    for record in records:
        teams.setdefault(record["team_id"], []).append(record)

    warnings = []
    role_count = 7 if layout.endswith("/v2") else 6
    for team_id, squad in teams.items():
        if not 11 <= len(squad) <= 40:
            raise ValueError(f"Team {team_id} has {len(squad)} slots; expected 11..40")
        shirts = [record["shirt_number"] for record in squad]
        if len(shirts) != len(set(shirts)):
            warnings.append(f"Team {team_id} contains duplicate shirt numbers")
        sort_keys = [record["sort_key"] for record in squad]
        if any(current >= following for current, following in zip(sort_keys, sort_keys[1:], strict=False)):
            raise ValueError(f"Team {team_id} sort keys are not strictly increasing")
        for role_bit in range(role_count):
            holders = sum(bool(record["role_mask"] & (1 << role_bit)) for record in squad)
            if holders != 1:
                raise ValueError(f"Team {team_id} role bit {role_bit} has {holders} holders")

    player_ids = {record["player_id"] for record in records}
    if valid_player_ids is not None:
        missing = sorted(player_ids - valid_player_ids)
        if missing:
            preview = ", ".join(str(player_id) for player_id in missing[:5])
            raise ValueError(f"Assignments reference missing Player.bin IDs: {preview}")

    if valid_team_ids is not None:
        missing_teams = sorted(set(teams.keys()) - valid_team_ids)
        if missing_teams:
            preview = ", ".join(str(team_id) for team_id in missing_teams[:5])
            raise ValueError(f"Assignments reference missing Team.bin IDs: {preview}")

    return {
        "layout": layout,
        "record_count": len(records),
        "team_count": len(teams),
        "unique_player_count": len(player_ids),
        "warning_count": len(warnings),
        "warnings": warnings,
    }


def replace_team_squad(
    assignment_data: bytes,
    team_id: int,
    replacement_player_ids: Iterable[int],
    valid_player_ids: set[int],
) -> bytes:
    validate_player_assignment_bin(assignment_data, valid_player_ids)
    records = parse_player_assignment_bin(assignment_data)
    target_indexes = [record["index"] for record in records if record["team_id"] == team_id]
    if not target_indexes:
        raise ValueError(f"Team {team_id} is not present in PlayerAssignment.bin")

    replacements = list(replacement_player_ids)
    if len(replacements) != len(target_indexes):
        raise ValueError(f"Team {team_id}: servono esattamente {len(target_indexes)} PID")
    if len(replacements) != len(set(replacements)):
        raise ValueError(f"Team {team_id} replacement contains duplicate player IDs")
    missing = sorted(set(replacements) - valid_player_ids)
    if missing:
        raise ValueError(f"Team {team_id}: PID inesistenti in Player.bin: {missing[:5]}")

    output = bytearray(assignment_data)
    player_id_offset = records[target_indexes[0]]["player_id_offset"]
    for record_index, player_id in zip(target_indexes, replacements, strict=True):
        struct.pack_into("<Q", output, record_index * 24 + player_id_offset, player_id)
    result = bytes(output)
    validate_player_assignment_bin(result, valid_player_ids)
    return result


def parse_team_bin(data: bytes) -> list[dict]:
    if len(data) % TEAM_RECORD_SIZE:
        raise ValueError("Team.bin is not aligned to 1,600-byte records")
    records = []
    for index, offset in enumerate(range(0, len(data), TEAM_RECORD_SIZE)):
        chunk = data[offset : offset + TEAM_RECORD_SIZE]
        team_id = struct.unpack_from("<I", chunk, 12)[0]
        name = chunk[396 : 396 + 70].split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        short_name = chunk[886 : 886 + 10].split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()
        records.append(
            {
                "row": index + 1,
                "index": index,
                "offset": f"0x{offset:06X}",
                "team_id": team_id,
                "name": name if name else f"Team #{team_id}",
                "short_name": short_name if short_name else f"T{team_id}",
                "hex": chunk[:16].hex(" "),
            }
        )
    return records


def update_team_record(
    team_data: bytes,
    team_id: int,
    *,
    name: str | None = None,
    short_name: str | None = None,
) -> bytes:
    if len(team_data) % TEAM_RECORD_SIZE:
        raise ValueError("Team.bin non è allineato a record da 1.600 byte")
    records = parse_team_bin(team_data)
    match_index = next((i for i, r in enumerate(records) if r["team_id"] == team_id), None)
    if match_index is None:
        raise ValueError(f"Team ID {team_id} non trovato in Team.bin")

    out = bytearray(team_data)
    offset = match_index * TEAM_RECORD_SIZE

    if name is not None:
        name_clean = name.strip()
        name_bytes = name_clean.encode("utf-8")[:69] + b"\x00"
        # Zero-fill and write to all localized and international name slots
        for name_pos in (116, 186, 396, 536, 746, 816, 1036):
            out[offset + name_pos : offset + name_pos + 70] = b"\x00" * 70
            out[offset + name_pos : offset + name_pos + len(name_bytes)] = name_bytes

    if short_name is not None:
        short_clean = short_name.strip().upper()
        short_bytes = short_clean.encode("utf-8")[:9] + b"\x00"
        out[offset + 886 : offset + 886 + 10] = b"\x00" * 10
        out[offset + 886 : offset + 886 + len(short_bytes)] = short_bytes

    return bytes(out)


def extract_team_diffs(vanilla_data: bytes, modded_data: bytes) -> list[tuple[str, str]]:
    van_teams = {t["team_id"]: t for t in parse_team_bin(vanilla_data)}
    mod_teams = {t["team_id"]: t for t in parse_team_bin(modded_data)}
    diffs = []
    for tid, mod_t in mod_teams.items():
        if tid in van_teams:
            van_t = van_teams[tid]
            if mod_t["name"] != van_t["name"] and van_t["name"]:
                diffs.append((van_t["name"], mod_t["name"]))
            if mod_t["short_name"] != van_t["short_name"] and van_t["short_name"]:
                diffs.append((van_t["short_name"], mod_t["short_name"]))
    return diffs


def parse_team_color_bin(data: bytes) -> list[dict]:
    stride = 64
    if len(data) % stride:
        raise ValueError("TeamColor.bin is not aligned to 64-byte records")
    records = []
    for index, offset in enumerate(range(0, len(data), stride)):
        chunk = data[offset : offset + stride]
        team_id = struct.unpack_from("<I", chunk, 0)[0]
        primary = tuple(chunk[4:7])
        secondary = tuple(chunk[8:11])
        records.append(
            {
                "row": index + 1,
                "index": index,
                "offset": f"0x{offset:06X}",
                "team_id": team_id,
                "color_primary": "#{:02X}{:02X}{:02X}".format(*primary),
                "color_secondary": "#{:02X}{:02X}{:02X}".format(*secondary),
                "rgb_primary": f"RGB{primary}",
                "rgb_secondary": f"RGB{secondary}",
                "hex": chunk[:16].hex(" "),
            }
        )
    return records


TEAM_COLUMNS = ("row", "offset", "team_id", "hex")
ASSIGNMENT_COLUMNS = (
    "row",
    "offset",
    "record_id",
    "player_id",
    "team_id",
    "shirt_number",
    "sort_key",
    "role_flags",
    "is_captain",
)
PLAYER_COLUMNS = (
    "row",
    "player_id",
    "display_name",
    "nationality_id",
    "height_cm",
    "weight_kg",
    "position_id",
    "layout",
)
