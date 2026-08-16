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
pub fn unpack_wesys(data: &[u8]) -> Option<Vec<u8>> {
    if !is_wesys_container(data) {
        let mut decoder = ZlibDecoder::new(data);
        let mut decomp = Vec::new();
        if decoder.read_to_end(&mut decomp).is_ok() && !decomp.is_empty() {
            return Some(decomp);
        }
        return Some(data.to_vec());
    }
    let flag_byte = data[0];
    let payload = &data[16..];
    let dec_bytes = if flag_byte >= 0x20 {
        decrypt_payload_xorshift(payload, flag_byte)
    } else {
        payload.to_vec()
    };
    let mut decoder = ZlibDecoder::new(&dec_bytes[..]);
    let mut decomp = Vec::new();
    if decoder.read_to_end(&mut decomp).is_ok() {
        Some(decomp)
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
