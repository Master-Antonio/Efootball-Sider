import configparser
import ctypes
import os
import struct
import sys
import tempfile
import unittest
import zlib


def set_packed_bits(buffer, bit_offset, bit_width, value):
    packed = int.from_bytes(buffer, "little")
    mask = ((1 << bit_width) - 1) << bit_offset
    packed = (packed & ~mask) | ((value << bit_offset) & mask)
    buffer[:] = packed.to_bytes(len(buffer), "little")


def unpack_current_wesys_reference(container):
    compressed_size, original_size = struct.unpack_from("<II", container, 8)
    encrypted = bytearray(container[16:])
    key_nibble = container[1] & 0x0F
    constants = {
        1: (0x168EA000, 0x2E2AA6F2, 0x0CC8DCD3),
        2: (0xED5B2960, 0x4A523B4E, 0xF3A31BAD),
    }
    x, y, z = constants[key_nibble]
    w = ((original_size << 16) | compressed_size) & 0xFFFFFFFF
    for offset in range(0, len(encrypted) - len(encrypted) % 4, 4):
        t = (x ^ (x << 11)) & 0xFFFFFFFF
        x, y, z = y, z, w
        w = (w ^ (((w >> 11) ^ t) >> 8) ^ t) & 0xFFFFFFFF
        struct.pack_into("<I", encrypted, offset, struct.unpack_from("<I", encrypted, offset)[0] ^ w)
    decoded = zlib.decompress(encrypted)
    if len(decoded) != original_size:
        raise AssertionError("reference decoder produced the wrong payload length")
    return decoded


def make_assignment_table(team_id, player_ids):
    table = bytearray()
    for index, player_id in enumerate(player_ids):
        record = bytearray(24)
        struct.pack_into("<I", record, 0, 50000 + index * 7)
        struct.pack_into("<Q", record, 8, player_id)
        struct.pack_into("<I", record, 16, team_id)
        record[20] = index
        record[21] = index * 4
        record[22] = 1 << index if index < 6 else 0
        table.extend(record)
    return bytes(table)


def make_assignment_table_v2(team_id, player_ids):
    table = bytearray()
    for index, player_id in enumerate(player_ids):
        record = bytearray(24)
        struct.pack_into("<Q", record, 0, player_id)
        struct.pack_into("<I", record, 8, team_id)
        struct.pack_into("<I", record, 12, 90000 + index * 7)
        record[16] = index
        record[17] = index * 4
        if index < 7:
            struct.pack_into("<H", record, 18, 1 << (index + 4))
        table.extend(record)
    return bytes(table)


def make_player_table(player_ids):
    table = bytearray()
    for index, player_id in enumerate(sorted(player_ids)):
        record = bytearray(400)
        struct.pack_into("<Q", record, 0, index + 1)
        struct.pack_into("<Q", record, 8, player_id)
        table.extend(record)
    return bytes(table)


class TestSiderCore(unittest.TestCase):
    def test_sider_ini_configparser_roundtrip(self):
        """Verify that sider.ini camera and livecpk configurations parse and write cleanly without corruption."""
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".ini", encoding="utf-8") as f:
            f.write("""[sider]
debug = 1
freecam = 0
[livecpk]
cpk.root = "content\\BroadcastCamera"
cpk.root = "content\\RealNames"
[camera]
enabled = 1
zoom = 0.82
height = 1.32
angle = -0.12
fov = 50.0
freecam_speed = 2.5
""")
            tmp_path = f.name
        try:
            cfg = configparser.ConfigParser(strict=False)
            cfg.read(tmp_path, encoding="utf-8")
            self.assertTrue(cfg.has_section("camera"))
            self.assertEqual(cfg.getfloat("camera", "zoom"), 0.82)
            self.assertEqual(cfg.getfloat("camera", "height"), 1.32)
            self.assertEqual(cfg.getfloat("camera", "fov"), 50.0)
            self.assertEqual(cfg.getboolean("camera", "enabled"), True)
            cfg.set("camera", "zoom", "0.95")
            cfg.set("camera", "fov", "62.5")
            with open(tmp_path, "w", encoding="utf-8") as out_f:
                cfg.write(out_f)
            cfg2 = configparser.ConfigParser()
            cfg2.read(tmp_path, encoding="utf-8")
            self.assertEqual(cfg2.getfloat("camera", "zoom"), 0.95)
            self.assertEqual(cfg2.getfloat("camera", "fov"), 62.5)
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)

    def test_native_rust_crypto_c_abi(self):
        """Verify the C-ABI export 'wesys_unpack_native' from compiled dxgi.dll."""
        dll_candidates = [
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "rust_sider",
                "target",
                "release",
                "dxgi.dll",
            ),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dxgi.dll"),
        ]
        found_dll = None
        for cand in dll_candidates:
            if os.path.isfile(cand):
                found_dll = cand
                break
        if not found_dll:
            self.skipTest("dxgi.dll not found in target/release, compile with cargo first.")
        lib = ctypes.CDLL(os.path.abspath(found_dll))
        self.assertTrue(hasattr(lib, "wesys_unpack_native"))

    def test_wesys_python_xorshift_roundtrip(self):
        """Verify current eFootball WESYS packing against an independent decoder."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import is_wesys_container, pack_wesys_container, unpack_wesys_payload

        original_data = b"eFootball Sider Database Entry Raw Data Payload 1234567890" * 80
        packed = pack_wesys_container(original_data, key_nibble=2, compression_level=1)

        self.assertTrue(is_wesys_container(packed))
        self.assertEqual(packed[:3], b"\xff\x22\x83")
        self.assertEqual(packed[3:8], b"WESYS")
        self.assertEqual(struct.unpack_from("<I", packed, 8)[0], len(packed) - 16)
        self.assertEqual(struct.unpack_from("<I", packed, 12)[0], len(original_data))
        self.assertEqual(unpack_current_wesys_reference(packed), original_data)

        unpacked = unpack_wesys_payload(packed)
        self.assertEqual(unpacked, original_data)

    def test_wesys_cross_language_rust_unpack(self):
        """Verify that Python packed WESYS container is successfully unpacked by native Rust C-ABI."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import pack_wesys_container

        dll_candidates = [
            os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "..",
                "rust_sider",
                "target",
                "release",
                "dxgi.dll",
            ),
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "dxgi.dll"),
        ]
        found_dll = None
        for cand in dll_candidates:
            if os.path.isfile(cand):
                found_dll = cand
                break
        if not found_dll:
            self.skipTest("dxgi.dll not found in target/release, compile with cargo first.")

        lib = ctypes.CDLL(os.path.abspath(found_dll))
        original_data = b"Team.bin database raw records cross-language validation payload" * 60
        packed = pack_wesys_container(original_data, key_nibble=2)

        max_out = len(original_data) + 1024
        out_buf = (ctypes.c_uint8 * max_out)()
        written = ctypes.c_size_t(0)
        ret = lib.wesys_unpack_native(packed, len(packed), out_buf, max_out, ctypes.byref(written))

        self.assertEqual(ret, 0)
        self.assertEqual(bytes(out_buf[: written.value]), original_data)

    def test_team_bin_parser(self):
        """Verify current Team.bin 1,600-byte records and ID at offset 12."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_team_bin

        team_record = bytearray(1600)
        struct.pack_into("<I", team_record, 12, 101)
        records = parse_team_bin(bytes(team_record))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["team_id"], 101)
        self.assertEqual(records[0]["offset"], "0x000000")

    def test_player_assignment_bin_parser(self):
        """Verify current assignment IDs, 64-bit PID, team, shirt, sort, and roles."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_player_assignment_bin

        record = bytearray(24)
        struct.pack_into("<I", record, 0, 70001)
        struct.pack_into("<Q", record, 8, 0x0123456789ABCDEF)
        struct.pack_into("<I", record, 16, 81952)
        record[20] = 9
        record[21] = 12
        record[22] = 0x20

        parsed = parse_player_assignment_bin(bytes(record))[0]
        self.assertEqual(parsed["record_id"], 70001)
        self.assertEqual(parsed["player_id"], 0x0123456789ABCDEF)
        self.assertEqual(parsed["team_id"], 81952)
        self.assertEqual(parsed["shirt_number"], 10)
        self.assertEqual(parsed["sort_key"], 12)
        self.assertEqual(parsed["role_mask"], 0x20)
        self.assertTrue(parsed["is_captain"])

    def test_player_assignment_bin_parser_v2(self):
        """Verify the current assignment field order used by dt870."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_player_assignment_bin

        record = bytearray(24)
        struct.pack_into("<Q", record, 0, 0x0123456789ABCDEF)
        struct.pack_into("<I", record, 8, 81952)
        struct.pack_into("<I", record, 12, 70001)
        record[16] = 9
        record[17] = 12
        struct.pack_into("<H", record, 18, 0x0200)

        parsed = parse_player_assignment_bin(bytes(record))[0]
        self.assertEqual(parsed["layout"], "eFootball PlayerAssignment/v2")
        self.assertEqual(parsed["record_id"], 70001)
        self.assertEqual(parsed["player_id"], 0x0123456789ABCDEF)
        self.assertEqual(parsed["team_id"], 81952)
        self.assertEqual(parsed["shirt_number"], 10)
        self.assertEqual(parsed["sort_key"], 12)
        self.assertEqual(parsed["role_flags"], 0x0200)
        self.assertEqual(parsed["role_mask"], 0x20)
        self.assertTrue(parsed["is_captain"])

    def test_replace_team_squad_changes_only_player_ids(self):
        """A whole-squad edit must preserve every slot-owned byte."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import (
            collect_player_ids,
            parse_player_assignment_bin,
            replace_team_squad,
            validate_player_assignment_bin,
        )

        original_ids = list(range(100, 111))
        replacement_ids = list(range(200, 211))
        assignments = make_assignment_table(101, original_ids)
        players = make_player_table(original_ids + replacement_ids)
        valid_player_ids = collect_player_ids(players)

        summary = validate_player_assignment_bin(assignments, valid_player_ids)
        self.assertEqual(summary["record_count"], 11)
        self.assertEqual(summary["team_count"], 1)

        replaced = replace_team_squad(assignments, 101, replacement_ids, valid_player_ids)
        parsed = parse_player_assignment_bin(replaced)
        self.assertEqual([record["player_id"] for record in parsed], replacement_ids)
        self.assertEqual(len(replaced), len(assignments))

        allowed_offsets = {
            record_index * 24 + byte_index for record_index in range(11) for byte_index in range(8, 16)
        }
        changed_offsets = {
            index
            for index, (before, after) in enumerate(zip(assignments, replaced, strict=True))
            if before != after
        }
        self.assertTrue(changed_offsets)
        self.assertTrue(changed_offsets <= allowed_offsets)
        validate_player_assignment_bin(replaced, valid_player_ids)

    def test_replace_team_squad_v2_changes_only_player_ids(self):
        """The current layout stores replaceable PIDs only at bytes 0..7."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import (
            parse_player_assignment_bin,
            replace_team_squad,
            validate_player_assignment_bin,
        )

        original_ids = list(range(100, 111))
        replacement_ids = list(range(200, 211))
        assignments = make_assignment_table_v2(101, original_ids)
        valid_player_ids = set(original_ids + replacement_ids)

        summary = validate_player_assignment_bin(assignments, valid_player_ids)
        self.assertEqual(summary["layout"], "eFootball PlayerAssignment/v2")
        replaced = replace_team_squad(assignments, 101, replacement_ids, valid_player_ids)
        self.assertEqual(
            [record["player_id"] for record in parse_player_assignment_bin(replaced)],
            replacement_ids,
        )

        allowed_offsets = {
            record_index * 24 + byte_index for record_index in range(11) for byte_index in range(0, 8)
        }
        changed_offsets = {
            index
            for index, (before, after) in enumerate(zip(assignments, replaced, strict=True))
            if before != after
        }
        self.assertTrue(changed_offsets)
        self.assertTrue(changed_offsets <= allowed_offsets)

    def test_replace_team_squad_rejects_dangling_player(self):
        """A replacement PID absent from Player.bin must be a hard error."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import replace_team_squad

        assignments = make_assignment_table(101, list(range(100, 111)))
        with self.assertRaisesRegex(ValueError, "inesistenti"):
            replace_team_squad(assignments, 101, list(range(200, 210)) + [9999], set(range(100, 211)))

    def test_replace_team_squad_rejects_headcount_change(self):
        """Changing squad headcount requires restructuring and is not an in-place edit."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import replace_team_squad

        assignments = make_assignment_table(101, list(range(100, 111)))
        with self.assertRaisesRegex(ValueError, "11 PID"):
            replace_team_squad(assignments, 101, list(range(200, 210)), set(range(100, 211)))

    def test_team_color_bin_parser(self):
        """Verify TeamColor.bin struct layout (64-byte stride with RGB primary/secondary)."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_team_color_bin

        color_record = struct.pack("<IBBBxBBBx", 101, 255, 0, 0, 255, 255, 255) + b"\x00" * 52
        self.assertEqual(len(color_record), 64)
        records = parse_team_color_bin(color_record)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["team_id"], 101)
        self.assertEqual(records[0]["color_primary"], "#FF0000")
        self.assertEqual(records[0]["color_secondary"], "#FFFFFF")

    def test_player_bin_parser(self):
        """Verify current Player.bin IDs, packed fields, and five-name region."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_player_bin

        chunk = bytearray(400)
        struct.pack_into("<Q", chunk, 0, 105432)
        struct.pack_into("<Q", chunk, 8, 0x0100000000019BD8)
        struct.pack_into("<H", chunk, 41, 45)
        set_packed_bits(chunk, 248, 8, 185)
        set_packed_bits(chunk, 280, 7, 80)
        set_packed_bits(chunk, 372, 8, 3)
        set_packed_bits(chunk, 556, 4, 9)
        for index, value in enumerate((b"Mario Rossi", b"M. Rossi", b"Rossi", b"Mario", b"")):
            start = 88 + index * 61
            chunk[start : start + len(value)] = value

        records = parse_player_bin(bytes(chunk))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["native_player_id"], 105432)
        self.assertEqual(records[0]["player_id"], 0x0100000000019BD8)
        self.assertEqual(records[0]["nationality_id"], 45)
        self.assertEqual(records[0]["height_cm"], 185)
        self.assertEqual(records[0]["weight_kg"], 80)
        self.assertEqual(records[0]["attacking_style"], 3)
        self.assertEqual(records[0]["position_id"], 9)
        self.assertEqual(records[0]["display_name"], "Mario Rossi")

    def test_player_bin_parser_live_392_layout(self):
        """Verify the live-update 392-byte layout observed in dt870."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_player_bin

        chunk = bytearray(392)
        struct.pack_into("<Q", chunk, 0, 155)
        struct.pack_into("<Q", chunk, 8, 2489)
        struct.pack_into("<H", chunk, 41, 26)
        set_packed_bits(chunk, 248, 8, 85)
        set_packed_bits(chunk, 280, 7, 52)
        set_packed_bits(chunk, 556, 4, 4)
        for index, value in enumerate(
            (b"Eiji Kawashima", b"KAWASHIMA", b"", b"KAWASHIMA", b"Eiji Kawashima")
        ):
            start = 84 + index * 61
            chunk[start : start + len(value)] = value

        record = parse_player_bin(bytes(chunk))[0]
        self.assertEqual(record["record_size"], 392)
        self.assertEqual(record["player_id"], 2489)
        self.assertEqual(record["display_name"], "Eiji Kawashima")
        self.assertEqual(record["nationality_id"], 26)
        self.assertEqual(record["height_cm"], 185)
        self.assertEqual(record["weight_kg"], 82)
        self.assertEqual(record["position_id"], 4)
        self.assertIsNone(record["attacking_style"])

    def test_wesys_empty_table_is_header_only(self):
        """Verify shipped-style empty tables remain exactly 16 bytes."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import pack_wesys_container, unpack_wesys_payload

        packed = pack_wesys_container(b"", key_nibble=2)
        self.assertEqual(packed, b"\xff\x22\x02WESYS" + b"\x00" * 8)
        self.assertEqual(unpack_wesys_payload(packed), b"")

    def test_wesys_roundtrip_odd_lengths(self):
        """Verify word encryption leaves trailing compressed bytes valid."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import pack_wesys_container, unpack_wesys_payload

        test_lengths = [1, 2, 3, 5, 7, 13, 31, 64, 127, 255, 513, 1027, 4099]
        for key_nibble in [1, 2]:
            for length in test_lengths:
                payload = bytes([(x * 37 + 13) & 0xFF for x in range(length)])
                packed = pack_wesys_container(payload, key_nibble=key_nibble)
                unpacked = unpack_wesys_payload(packed)
                self.assertEqual(
                    unpacked, payload, f"Failed roundtrip for key {key_nibble} and length {length}"
                )

    def test_extract_pesdb_from_cpk_end_to_end(self):
        """Extract selected databases, decode WESYS, validate, and write a manifest."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from cricodecs import cpk

        from efootball_sider_gui import extract_pesdb_from_cpk, pack_wesys_container

        player_ids = list(range(100, 111))
        player_raw = make_player_table(player_ids)
        assignment_raw = make_assignment_table_v2(101, player_ids)
        team_raw = bytearray(1600)
        struct.pack_into("<I", team_raw, 12, 101)

        archive = cpk.create(cpk.CpkPreset.FILENAME)
        archive.add_bytes(pack_wesys_container(player_raw), "common/etc/pesdb/Player.bin")
        archive.add_bytes(pack_wesys_container(assignment_raw), "common/etc/pesdb/PlayerAssignment.bin")
        archive.add_bytes(pack_wesys_container(bytes(team_raw)), "common/etc/pesdb/Team.bin")
        archive.add_bytes(b"ignored", "common/etc/pesdb/Other.bin")

        with tempfile.TemporaryDirectory() as tmp_dir:
            cpk_path = os.path.join(tmp_dir, "dt870_console_win.cpk")
            output_dir = os.path.join(tmp_dir, "output")
            with open(cpk_path, "wb") as stream:
                stream.write(bytes(archive.save_bytes()))

            manifest = extract_pesdb_from_cpk(cpk_path, output_dir)

            self.assertEqual(manifest["player"]["record_count"], 11)
            self.assertEqual(manifest["player"]["record_size"], 400)
            self.assertEqual(manifest["assignment"]["layout"], "eFootball PlayerAssignment/v2")
            self.assertEqual(manifest["assignment"]["team_count"], 1)
            self.assertEqual(manifest["team"]["record_count"], 1)
            self.assertTrue(os.path.isfile(os.path.join(output_dir, "manifest.json")))
            for name, expected in (
                ("Player.bin", player_raw),
                ("PlayerAssignment.bin", assignment_raw),
                ("Team.bin", bytes(team_raw)),
            ):
                decoded_path = os.path.join(output_dir, "decoded", "common", "etc", "pesdb", name)
                packed_path = os.path.join(output_dir, "packed", "common", "etc", "pesdb", name)
                self.assertTrue(os.path.isfile(packed_path))
                with open(decoded_path, "rb") as stream:
                    self.assertEqual(stream.read(), expected)

    def test_db_injection_config_parsing_and_case_preservation(self):
        """Verify reading db_injection settings and preserving casing for team/player rules."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from pathlib import Path

        from ui.services.config import ConfigurationService
        from ui.services.paths import WorkspacePaths

        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_root = Path(tmp_dir)
            sider_ini = tmp_root / "sider.ini"
            sider_ini.write_text(
                """[db_injection]
enabled = 1
xor_mask = 0x6B

[teams]
; Comment line
London FC = Arsenal
MD White = Real Madrid

[players]
Silva = David Silva
""",
                encoding="utf-8",
            )
            paths = WorkspacePaths(tmp_root, tmp_root)
            config_svc = ConfigurationService(paths)
            db_cfg = config_svc.read_db_injection()

            self.assertTrue(db_cfg.enabled)
            self.assertEqual(db_cfg.xor_mask, 0x6B)
            self.assertIn("London FC", db_cfg.teams)
            self.assertEqual(db_cfg.teams["London FC"], "Arsenal")
            self.assertIn("MD White", db_cfg.teams)
            self.assertEqual(db_cfg.teams["MD White"], "Real Madrid")
            self.assertIn("Silva", db_cfg.players)
            self.assertEqual(db_cfg.players["Silva"], "David Silva")


if __name__ == "__main__":
    unittest.main()
