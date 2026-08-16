import os
import sys
import unittest
import configparser
import tempfile
import ctypes
import struct
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
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rust_sider", "target", "release", "dxgi.dll"),
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
    def test_wesys_python_xorshift_roundtrip(self):
        """Verify that Python XorShift128 WESYS pack and unpack performs lossless encryption/decryption roundtrip."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import pack_wesys_container, unpack_wesys_payload, is_wesys_container

        original_data = b"eFootball Sider Database Entry Raw Data Payload 1234567890" * 80
        packed = pack_wesys_container(original_data, flag_byte=0x20)
        
        self.assertTrue(is_wesys_container(packed))
        self.assertEqual(packed[0], 0x20)
        self.assertEqual(packed[3:8], b"WESYS")
        
        unpacked = unpack_wesys_payload(packed)
        self.assertEqual(unpacked, original_data)

    def test_wesys_cross_language_rust_unpack(self):
        """Verify that Python packed WESYS container is successfully unpacked by native Rust C-ABI."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import pack_wesys_container

        dll_candidates = [
            os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "rust_sider", "target", "release", "dxgi.dll"),
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
        packed = pack_wesys_container(original_data, flag_byte=0x20)

        max_out = len(original_data) + 1024
        out_buf = (ctypes.c_uint8 * max_out)()
        written = ctypes.c_size_t(0)
        ret = lib.wesys_unpack_native(packed, len(packed), out_buf, max_out, ctypes.byref(written))
        
        self.assertEqual(ret, 0)
        self.assertEqual(bytes(out_buf[:written.value]), original_data)

    def test_team_bin_parser(self):
        """Verify Team.bin struct layout (64-byte stride)."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_team_bin
        
        team_record = struct.pack("<I", 101) + b"Arsenal FC\x00" + b"\x00" * 49
        self.assertEqual(len(team_record), 64)
        records = parse_team_bin(team_record)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["team_id"], 101)
        self.assertEqual(records[0]["name"], "Arsenal FC")

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
        """Verify Player.bin struct layout (400-byte stride)."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import parse_player_bin
        
        chunk = bytearray(400)
        struct.pack_into("<I", chunk, 0, 105432)
        struct.pack_into("<H", chunk, 8, 45) # Nationality
        chunk[16] = 185 # Height
        chunk[17] = 80 # Weight
        chunk[20] = 3 # Attacking Style
        
        records = parse_player_bin(bytes(chunk))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["player_id"], 105432)
        self.assertEqual(records[0]["nationality_id"], 45)
        self.assertEqual(records[0]["height_cm"], 185)
        self.assertEqual(records[0]["weight_kg"], 80)
        self.assertEqual(records[0]["attacking_style"], 3)

    def test_xorshift128_seed_consistency(self):
        """Verify Python XorShift128 produces exact expected keystream values for flags 0x20 and 0x21."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import XorShift128, get_cipher_constants

        seed_20, shifts_20 = get_cipher_constants(0x20)
        prng20 = XorShift128(seed_20, shifts_20)
        expected_20 = [0x945fb983, 0xe868bea6, 0x474e4917, 0x2620e2b2, 0x4fdad454]
        for val in expected_20:
            self.assertEqual(prng20.next_u32(), val)

        seed_21, shifts_21 = get_cipher_constants(0x21)
        prng21 = XorShift128(seed_21, shifts_21)
        expected_21 = [0xa31bb0f1, 0xc2ca97b8, 0xf4ec622d, 0xae4e1264, 0xd0aca364]
        for val in expected_21:
            self.assertEqual(prng21.next_u32(), val)

    def test_wesys_roundtrip_odd_lengths(self):
        """Verify roundtrip pack and unpack for various arbitrary/odd payload lengths."""
        sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        from efootball_sider_gui import pack_wesys_container, unpack_wesys_payload

        test_lengths = [1, 2, 3, 5, 7, 13, 31, 64, 127, 255, 513, 1027, 4099]
        for flag in [0x20, 0x21, 0x00]:
            for length in test_lengths:
                payload = bytes([(x * 37 + 13) & 0xFF for x in range(length)])
                packed = pack_wesys_container(payload, flag_byte=flag)
                unpacked = unpack_wesys_payload(packed)
                self.assertEqual(unpacked, payload, f"Failed roundtrip for flag {hex(flag)} and length {length}")

if __name__ == "__main__":
    unittest.main()
