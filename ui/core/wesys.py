from __future__ import annotations

import ctypes
import struct
import zlib
from pathlib import Path


class WesysError(ValueError):
    """Raised when a WESYS container is malformed or unsupported."""


CURRENT_WESYS_KEYS = {
    1: (0x168EA000, 0x2E2AA6F2, 0x0CC8DCD3),
    2: (0xED5B2960, 0x4A523B4E, 0xF3A31BAD),
}

LEGACY_WESYS_KEYS = {
    0x20: ((0x12345678, 0x9ABCDEF0, 0x13579BDF, 0x2468ACE0), (11, 8, 19)),
    0x21: ((0x87654321, 0x0FEDCBA9, 0xFDB97531, 0x0ECA8642), (11, 8, 19)),
}


def is_wesys_container(data: bytes) -> bool:
    return len(data) >= 16 and data[3:8] == b"WESYS"


def crypt_current_payload(
    payload: bytes,
    key_nibble: int,
    compressed_size: int,
    original_size: int,
) -> bytes:
    try:
        x, y, z = CURRENT_WESYS_KEYS[key_nibble]
    except KeyError as exc:
        raise WesysError(f"Unsupported WESYS key nibble: {key_nibble}") from exc
    if len(payload) != compressed_size:
        raise WesysError(f"WESYS payload size mismatch: {len(payload)} != {compressed_size}")

    output = bytearray(payload)
    w = ((original_size << 16) | compressed_size) & 0xFFFFFFFF
    encrypted_length = len(output) - len(output) % 4
    for offset in range(0, encrypted_length, 4):
        t = (x ^ (x << 11)) & 0xFFFFFFFF
        x, y, z = y, z, w
        w = (w ^ (((w >> 11) ^ t) >> 8) ^ t) & 0xFFFFFFFF
        word = struct.unpack_from("<I", output, offset)[0] ^ w
        struct.pack_into("<I", output, offset, word)
    return bytes(output)


def _crypt_legacy_payload(payload: bytes, flag_byte: int) -> bytes:
    seed, shifts = LEGACY_WESYS_KEYS.get(
        flag_byte,
        ((0x6C8E9CF5, 0x3B2F7E41, 0x9D4C1A8B, 0x5E6A7D2C), (11, 8, 19)),
    )
    x, y, z, w = seed
    s1, s2, s3 = shifts
    output = bytearray(payload)
    for offset in range(0, len(output) - len(output) % 4, 4):
        t = (x ^ (x << s1)) & 0xFFFFFFFF
        x, y, z = y, z, w
        w = ((w ^ (w >> s3)) ^ (t ^ (t >> s2))) & 0xFFFFFFFF
        word = struct.unpack_from("<I", output, offset)[0] ^ w
        struct.pack_into("<I", output, offset, word)
    return bytes(output)


def pack_wesys_container(
    data: bytes,
    key_nibble: int = 2,
    compression_level: int = 1,
) -> bytes:
    if key_nibble not in CURRENT_WESYS_KEYS:
        raise WesysError(f"Unsupported WESYS key nibble: {key_nibble}")
    if not 0 <= compression_level <= 9:
        raise WesysError("Zlib compression level must be between 0 and 9")
    if not data:
        return struct.pack("<BBB5sII", 0xFF, 0x20 | key_nibble, 0x02, b"WESYS", 0, 0)

    compressed = zlib.compress(data, level=compression_level)
    encrypted = crypt_current_payload(
        compressed,
        key_nibble,
        len(compressed),
        len(data),
    )
    header = struct.pack(
        "<BBB5sII",
        0xFF,
        0x20 | key_nibble,
        0x83,
        b"WESYS",
        len(encrypted),
        len(data),
    )
    return header + encrypted


def unpack_wesys_payload(data: bytes) -> bytes:
    if not is_wesys_container(data):
        try:
            return zlib.decompress(data)
        except zlib.error:
            return data

    compressed_size, original_size = struct.unpack_from("<II", data, 8)
    payload = data[16:]
    if compressed_size == 0 and original_size == 0:
        if payload:
            raise WesysError("Empty WESYS container has an unexpected payload")
        return b""

    current_format = data[0] == 0xFF
    if current_format:
        decrypted = crypt_current_payload(
            payload,
            data[1] & 0x0F,
            compressed_size,
            original_size,
        )
    else:
        decrypted = _crypt_legacy_payload(payload, data[0]) if data[0] >= 0x20 else payload

    try:
        unpacked = zlib.decompress(decrypted)
    except zlib.error as exc:
        if current_format:
            raise WesysError("Current WESYS payload could not be decrypted") from exc
        return decrypted

    if current_format and len(unpacked) != original_size:
        raise WesysError(f"WESYS decoded size mismatch: {len(unpacked)} != {original_size}")
    return unpacked


MAX_WESYS_DECODED_SIZE = 256 * 1024 * 1024  # 256 MiB


def unpack_wesys_fast(data: bytes, dll_candidates: tuple[Path, ...] = ()) -> bytes:
    if not is_wesys_container(data):
        return unpack_wesys_payload(data)

    expected_size = struct.unpack_from("<I", data, 12)[0]
    if expected_size == 0:
        return b""
    if expected_size > MAX_WESYS_DECODED_SIZE:
        raise WesysError(f"WESYS container decoded size exceeds safety limit: {expected_size}")

    for dll_path in dll_candidates:
        if not dll_path.is_file():
            continue
        try:
            library = ctypes.CDLL(str(dll_path))
            function = library.wesys_unpack_native
            function.argtypes = (
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_uint8),
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            )
            function.restype = ctypes.c_int
            source = (ctypes.c_uint8 * len(data)).from_buffer_copy(data)
            output = (ctypes.c_uint8 * expected_size)()
            written = ctypes.c_size_t()
            result = function(
                source,
                len(data),
                output,
                expected_size,
                ctypes.byref(written),
            )
            if result == 0 and written.value == expected_size:
                return bytes(output)
        except (AttributeError, OSError, ValueError):
            continue
    return unpack_wesys_payload(data)
