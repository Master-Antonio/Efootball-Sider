use std::io::Read;
use flate2::read::ZlibDecoder;
#[derive(Clone, Copy, Debug)]
pub struct CipherConfig {
    pub seed: (u32, u32, u32, u32),
    pub shifts: (u32, u32, u32),
}
pub fn get_cipher_constants(flag_byte: u8) -> CipherConfig {
    match flag_byte {
        0x20 => CipherConfig {
            seed: (0x12345678, 0x9ABCDEF0, 0x13579BDF, 0x2468ACE0),
            shifts: (11, 8, 19),
        },
        0x21 => CipherConfig {
            seed: (0x87654321, 0x0FEDCBA9, 0xFDB97531, 0x0ECA8642),
            shifts: (11, 8, 19),
        },
        _ => CipherConfig {
            seed: (0x6C8E9CF5, 0x3B2F7E41, 0x9D4C1A8B, 0x5E6A7D2C),
            shifts: (11, 8, 19),
        },
    }
}
pub struct XorShift128 {
    pub x: u32,
    pub y: u32,
    pub z: u32,
    pub w: u32,
    pub s1: u32,
    pub s2: u32,
    pub s3: u32,
}
impl XorShift128 {
    pub fn new(cfg: &CipherConfig) -> Self {
        Self {
            x: cfg.seed.0,
            y: cfg.seed.1,
            z: cfg.seed.2,
            w: cfg.seed.3,
            s1: cfg.shifts.0,
            s2: cfg.shifts.1,
            s3: cfg.shifts.2,
        }
    }
    #[inline(always)]
    pub fn next_u32(&mut self) -> u32 {
        let t = self.x ^ (self.x << self.s1);
        self.x = self.y;
        self.y = self.z;
        self.z = self.w;
        self.w = (self.w ^ (self.w >> self.s3)) ^ (t ^ (t >> self.s2));
        self.w
    }
}
pub fn is_wesys_container(data: &[u8]) -> bool {
    if data.len() < 16 {
        return false;
    }
    &data[3..8] == b"WESYS"
}
pub fn decrypt_payload_xorshift(payload: &[u8], flag_byte: u8) -> Vec<u8> {
    let cfg = get_cipher_constants(flag_byte);
    let mut prng = XorShift128::new(&cfg);
    let mut out = payload.to_vec();
    let n_words = out.len() / 4;
    for i in 0..n_words {
        let offset = i * 4;
        let k = prng.next_u32();
        let orig = u32::from_le_bytes([out[offset], out[offset + 1], out[offset + 2], out[offset + 3]]);
        let dec = orig ^ k;
        let b = dec.to_le_bytes();
        out[offset..offset + 4].copy_from_slice(&b);
    }
    out
}

fn decrypt_current_wesys_payload(
    payload: &[u8],
    key_nibble: u8,
    compressed_size: u32,
    original_size: u32,
) -> Option<Vec<u8>> {
    let (mut x, mut y, mut z) = match key_nibble {
        1 => (0x168EA000u32, 0x2E2AA6F2u32, 0x0CC8DCD3u32),
        2 => (0xED5B2960u32, 0x4A523B4Eu32, 0xF3A31BADu32),
        _ => return None,
    };
    let mut w = original_size.wrapping_shl(16) | compressed_size;
    let mut out = payload.to_vec();

    for word in out.chunks_exact_mut(4) {
        let t = x ^ (x << 11);
        x = y;
        y = z;
        z = w;
        w = w ^ (((w >> 11) ^ t) >> 8) ^ t;

        let value = u32::from_le_bytes(word.try_into().ok()?) ^ w;
        word.copy_from_slice(&value.to_le_bytes());
    }

    Some(out)
}

const MAX_WESYS_SIZE: usize = 256 * 1024 * 1024; // 256 MiB

pub fn unpack_wesys(data: &[u8]) -> Option<Vec<u8>> {
    if !is_wesys_container(data) {
        let mut decoder = ZlibDecoder::new(data);
        let mut decomp = Vec::new();
        if decoder.read_to_end(&mut decomp).is_ok() && !decomp.is_empty() {
            return Some(decomp);
        }
        return Some(data.to_vec());
    }

    let compressed_size = u32::from_le_bytes(data[8..12].try_into().ok()?);
    let original_size = u32::from_le_bytes(data[12..16].try_into().ok()?);
    let payload = &data[16..];

    if compressed_size == 0 && original_size == 0 {
        if !payload.is_empty() {
            return None;
        }
        return Some(Vec::new());
    }
    if compressed_size as usize > MAX_WESYS_SIZE || original_size as usize > MAX_WESYS_SIZE {
        return None;
    }
    if payload.len() != compressed_size as usize {
        return None;
    }

    let is_current_format = data[0] == 0xFF;
    let dec_bytes = if is_current_format {
        decrypt_current_wesys_payload(
            payload,
            data[1] & 0x0F,
            compressed_size,
            original_size,
        )?
    } else if data[0] >= 0x20 {
        decrypt_payload_xorshift(payload, data[0])
    } else {
        payload.to_vec()
    };

    let mut decoder = ZlibDecoder::new(&dec_bytes[..]);
    let mut decomp = Vec::with_capacity(original_size.min(1024 * 1024) as usize);
    if decoder.read_to_end(&mut decomp).is_ok() {
        if is_current_format && decomp.len() != original_size as usize {
            None
        } else {
            Some(decomp)
        }
    } else if is_current_format {
        None
    } else {
        Some(dec_bytes)
    }
}
#[no_mangle]
pub unsafe extern "C" fn wesys_unpack_native(
    input_ptr: *const u8,
    input_len: usize,
    out_buf: *mut u8,
    out_cap: usize,
    out_written: *mut usize,
) -> i32 {
    if input_ptr.is_null() || out_buf.is_null() || out_written.is_null() {
        return -1;
    }
    let slice = std::slice::from_raw_parts(input_ptr, input_len);
    match unpack_wesys(slice) {
        Some(unpacked) => {
            if unpacked.len() > out_cap {
                *out_written = unpacked.len();
                return -2; 
            }
            std::ptr::copy_nonoverlapping(unpacked.as_ptr(), out_buf, unpacked.len());
            *out_written = unpacked.len();
            0 
        }
        None => -3,
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    use flate2::write::ZlibEncoder;
    use flate2::Compression;
    use std::io::Write;

    fn pack_verified_wesys_v5(payload: &[u8], key_nibble: u8) -> Vec<u8> {
        let mut encoder = ZlibEncoder::new(Vec::new(), Compression::fast());
        encoder.write_all(payload).unwrap();
        let mut compressed = encoder.finish().unwrap();

        let compressed_size = compressed.len() as u32;
        let original_size = payload.len() as u32;
        let (mut x, mut y, mut z) = match key_nibble {
            1 => (0x168EA000u32, 0x2E2AA6F2u32, 0x0CC8DCD3u32),
            2 => (0xED5B2960u32, 0x4A523B4Eu32, 0xF3A31BADu32),
            _ => panic!("unsupported test key nibble"),
        };
        let mut w = (original_size << 16) | compressed_size;

        for word in compressed.chunks_exact_mut(4) {
            let t = x ^ (x << 11);
            x = y;
            y = z;
            z = w;
            w = w ^ (((w >> 11) ^ t) >> 8) ^ t;

            let value = u32::from_le_bytes(word.try_into().unwrap()) ^ w;
            word.copy_from_slice(&value.to_le_bytes());
        }

        let mut container = Vec::with_capacity(16 + compressed.len());
        container.extend_from_slice(&[0xFF, 0x20 | key_nibble, 0x83]);
        container.extend_from_slice(b"WESYS");
        container.extend_from_slice(&compressed_size.to_le_bytes());
        container.extend_from_slice(&original_size.to_le_bytes());
        container.extend_from_slice(&compressed);
        container
    }

    #[test]
    fn test_unpack_current_wesys_v5_container() {
        let original = b"current eFootball PlayerAssignment.bin payload".repeat(128);
        let packed = pack_verified_wesys_v5(&original, 2);

        let unpacked = unpack_wesys(&packed).expect("current WESYS container should unpack");
        assert_eq!(unpacked.len(), original.len());
        assert_eq!(unpacked, original);
    }

    #[test]
    fn test_xorshift_deterministic_keystream() {
        let cfg = get_cipher_constants(0x20);
        let mut prng1 = XorShift128::new(&cfg);
        let mut prng2 = XorShift128::new(&cfg);
        for _ in 0..100 {
            assert_eq!(prng1.next_u32(), prng2.next_u32());
        }
    }
    #[test]
    fn test_wesys_container_detection() {
        let fake_wesys = [0x20, 0x00, 0x00, b'W', b'E', b'S', b'Y', b'S', 0, 0, 0, 0, 0, 0, 0, 0];
        assert!(is_wesys_container(&fake_wesys));
        let non_wesys = [0u8; 16];
        assert!(!is_wesys_container(&non_wesys));
    }
}
