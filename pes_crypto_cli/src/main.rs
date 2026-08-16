use std::fs::File;
use std::io::{Read, Write};
use std::path::Path;
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
    if data.len() < 16 || &data[3..8] != b"WESYS" {
        let mut decoder = ZlibDecoder::new(data);
        let mut decomp = Vec::new();
        if decoder.read_to_end(&mut decomp).is_ok() && !decomp.is_empty() {
            return Some(decomp);
        }
        return Some(data.to_vec());
    }
    let flag_byte = data[1];
    let comp_sz = u32::from_le_bytes([data[8], data[9], data[10], data[11]]) as usize;
    let _uncomp_sz = u32::from_le_bytes([data[12], data[13], data[14], data[15]]) as usize;
    let payload_end = (16 + comp_sz).min(data.len());
    let raw_payload = &data[16..payload_end];
    let mut dec = ZlibDecoder::new(raw_payload);
    let mut out = Vec::new();
    if dec.read_to_end(&mut out).is_ok() && !out.is_empty() {
        return Some(out);
    }
    let dec_payload = decrypt_payload_xorshift(raw_payload, flag_byte);
    let mut dec2 = ZlibDecoder::new(dec_payload.as_slice());
    let mut out2 = Vec::new();
    if dec2.read_to_end(&mut out2).is_ok() && !out2.is_empty() {
        return Some(out2);
    }
    None
}
fn main() {
    println!("=== eFootball / PES WESYS Container Tool (Pure Rust) ===");
    let args: Vec<String> = std::env::args().skip(1).collect();
    if args.is_empty() {
        println!("Usage: pes_crypto_cli <file1.bin> [file2.bin ...]");
        return;
    }
    for arg in args {
        let p = Path::new(&arg);
        if !p.exists() {
            println!("File not found: {}", arg);
            continue;
        }
        println!("Processing: {}", arg);
        let mut f = match File::open(p) {
            Ok(file) => file,
            Err(e) => {
                println!("Error opening file: {}", e);
                continue;
            }
        };
        let mut buf = Vec::new();
        if let Err(e) = f.read_to_end(&mut buf) {
            println!("Error reading file: {}", e);
            continue;
        }
        match unpack_wesys(&buf) {
            Some(unpacked) => {
                let out_path = format!("{}.unpacked.raw", arg);
                match File::create(&out_path) {
                    Ok(mut out_f) => {
                        let _ = out_f.write_all(&unpacked);
                        println!("✅ Unpacked successfully! Saved to: {} ({} bytes)", out_path, unpacked.len());
                    }
                    Err(e) => println!("Error creating output file: {}", e),
                }
            }
            None => println!("❌ Failed to unpack WESYS container: {}", arg),
        }
    }
}
