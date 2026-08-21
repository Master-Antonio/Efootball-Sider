use std::collections::HashSet;
use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicUsize, Ordering};

pub const DEFAULT_XOR_KEY: u8 = 0x6B;
const MAX_LOGGED_PATCHES: usize = 50;
static PATCH_LOG_COUNT: AtomicUsize = AtomicUsize::new(0);

#[derive(Clone, Debug, PartialEq)]
pub struct ReplacementRule {
    pub original_from: String,
    pub original_to: String,
    pub is_player: bool,
    // XOR 0x6B ASCII (target_len matches original_from.len(), padded with 0x00 ^ mask = mask)
    pub from_ascii_masked: Vec<u8>,
    pub to_ascii_masked: Vec<u8>,
    // XOR 0x6B UTF-16LE (target_len matches original_from.len() * 2, padded with 0x00 ^ mask = mask)
    pub from_utf16_masked: Vec<u8>,
    pub to_utf16_masked: Vec<u8>,
    // Raw UTF-8 / ASCII (target_len matches original_from.len(), padded with 0x00)
    pub from_raw_ascii: Vec<u8>,
    pub to_raw_ascii: Vec<u8>,
    // Raw UTF-16LE (target_len matches original_from.len() * 2, padded with 0x00)
    pub from_raw_utf16: Vec<u8>,
    pub to_raw_utf16: Vec<u8>,
}

#[derive(Clone, Debug)]
pub struct DbInjectionConfig {
    pub enabled: bool,
    pub xor_mask: u8,
    pub rules: Vec<ReplacementRule>,
}

impl Default for DbInjectionConfig {
    fn default() -> Self {
        Self {
            enabled: true,
            xor_mask: DEFAULT_XOR_KEY,
            rules: Vec::new(),
        }
    }
}

pub struct ActiveMod {
    pub name: String,
    pub path: PathBuf,
}

/// Populates active mod package directories from sider.ini cpk.root directives
pub fn load_active_mods_from_sider_ini(sider_ini_path: &Path) -> Vec<ActiveMod> {
    let mut mods = Vec::new();
    if !sider_ini_path.exists() {
        return mods;
    }
    let base_dir = sider_ini_path.parent().unwrap_or(Path::new("."));
    if let Ok(file) = File::open(sider_ini_path) {
        let reader = BufReader::new(file);
        for line in reader.lines().map_while(Result::ok) {
            let line = line.trim();
            if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
                continue;
            }
            if let Some((key_part, val_part)) = line.split_once('=') {
                if key_part.trim().eq_ignore_ascii_case("cpk.root") {
                    let raw_val = val_part.trim().trim_matches('"').trim_matches('\'');
                    if !raw_val.is_empty() {
                        let full_path = if Path::new(raw_val).is_absolute() {
                            PathBuf::from(raw_val)
                        } else {
                            base_dir.join(raw_val)
                        };
                        let mod_name = full_path
                            .file_name()
                            .unwrap_or_default()
                            .to_string_lossy()
                            .to_string();
                        mods.push(ActiveMod {
                            name: mod_name,
                            path: full_path,
                        });
                    }
                }
            }
        }
    }
    mods
}

/// Creates a replacement rule with length validation, boundary protection, and encoding padding.
/// If `to` is longer than `from`, the rule is rejected (returns None) to avoid buffer corruption.
pub fn create_replacement_rule(
    from: &str,
    to: &str,
    is_player: bool,
    mask: u8,
) -> Option<ReplacementRule> {
    let from_trimmed = from.trim();
    let to_trimmed = to.trim();

    if from_trimmed.len() < 3 || to_trimmed.is_empty() {
        return None;
    }
    if from_trimmed.eq_ignore_ascii_case(to_trimmed) {
        return None;
    }

    let from_bytes = from_trimmed.as_bytes();
    let to_bytes = to_trimmed.as_bytes();

    if to_bytes.len() > from_bytes.len() {
        crate::log_msg(&format!(
            "[DB INJECTION] Rule rejected: Replacement '{}' ({} bytes) exceeds target '{}' ({} bytes). Silent truncation is forbidden.",
            to_trimmed, to_bytes.len(), from_trimmed, from_bytes.len()
        ));
        return None;
    }

    let from_u16: Vec<u16> = from_trimmed.encode_utf16().collect();
    let to_u16: Vec<u16> = to_trimmed.encode_utf16().collect();

    if to_u16.len() > from_u16.len() {
        return None;
    }

    // 1. ASCII padding (padded with 0x00)
    let target_ascii_len = from_bytes.len();
    let mut to_padded_ascii = to_bytes.to_vec();
    to_padded_ascii.resize(target_ascii_len, 0x00);

    let from_ascii_masked: Vec<u8> = from_bytes.iter().map(|&b| b ^ mask).collect();
    let to_ascii_masked: Vec<u8> = to_padded_ascii.iter().map(|&b| b ^ mask).collect();
    let from_raw_ascii = from_bytes.to_vec();
    let to_raw_ascii = to_padded_ascii;

    // 2. UTF-16LE padding (padded with 0u16)
    let target_u16_len = from_u16.len();
    let mut to_padded_u16 = to_u16;
    to_padded_u16.resize(target_u16_len, 0u16);

    let from_raw_utf16: Vec<u8> = from_u16.iter().flat_map(|&u| u.to_le_bytes()).collect();
    let to_raw_utf16: Vec<u8> = to_padded_u16.iter().flat_map(|&u| u.to_le_bytes()).collect();
    let from_utf16_masked: Vec<u8> = from_raw_utf16.iter().map(|&b| b ^ mask).collect();
    let to_utf16_masked: Vec<u8> = to_raw_utf16.iter().map(|&b| b ^ mask).collect();

    Some(ReplacementRule {
        original_from: from_trimmed.to_string(),
        original_to: to_trimmed.to_string(),
        is_player,
        from_ascii_masked,
        to_ascii_masked,
        from_utf16_masked,
        to_utf16_masked,
        from_raw_ascii,
        to_raw_ascii,
        from_raw_utf16,
        to_raw_utf16,
    })
}

/// Boundary check for ASCII/UTF-8 single-byte fields
#[inline]
pub fn is_ascii_field_boundary(buf: &[u8], start: usize, len: usize, null_byte: u8) -> bool {
    let before_ok = start == 0 || buf[start - 1] == null_byte;
    let after_ok = match buf.get(start + len) {
        Some(&b) => b == null_byte,
        None => true,
    };
    before_ok && after_ok
}

/// Boundary check for UTF-16LE 2-byte fields (checks 2-byte null terminator)
#[inline]
pub fn is_utf16_field_boundary(buf: &[u8], start: usize, len: usize, null_byte: u8) -> bool {
    let before_ok = start < 2 || (buf[start - 2] == null_byte && buf[start - 1] == null_byte);
    let after_ok = if start + len + 1 < buf.len() {
        buf[start + len] == null_byte && buf[start + len + 1] == null_byte
    } else {
        true
    };
    before_ok && after_ok
}

/// Helper to find all occurrences of a needle inside a haystack
pub fn find_all_occurrences(haystack: &[u8], needle: &[u8]) -> Vec<usize> {
    if needle.is_empty() || haystack.len() < needle.len() {
        return Vec::new();
    }
    let mut matches = Vec::new();
    let first = needle[0];
    let end = haystack.len() - needle.len();
    let mut i = 0;
    while i <= end {
        if haystack[i] == first && &haystack[i..i + needle.len()] == needle {
            matches.push(i);
            i += needle.len();
        } else {
            i += 1;
        }
    }
    matches
}

/// Patches matching patterns inside a raw memory slice (for testing or direct buffer manipulation)
pub fn scan_and_patch_slice(
    slice: &mut [u8],
    rules: &[ReplacementRule],
    xor_mask: u8,
) -> usize {
    let mut patched_count = 0;

    for rule in rules {
        // 1. XOR ASCII
        let occurrences = find_all_occurrences(slice, &rule.from_ascii_masked);
        for idx in occurrences {
            if is_ascii_field_boundary(slice, idx, rule.from_ascii_masked.len(), xor_mask) {
                let len = rule.to_ascii_masked.len();
                slice[idx..idx + len].copy_from_slice(&rule.to_ascii_masked);
                patched_count += 1;
            }
        }

        // 2. XOR UTF-16
        let occurrences = find_all_occurrences(slice, &rule.from_utf16_masked);
        for idx in occurrences {
            if is_utf16_field_boundary(slice, idx, rule.from_utf16_masked.len(), xor_mask) {
                let len = rule.to_utf16_masked.len();
                slice[idx..idx + len].copy_from_slice(&rule.to_utf16_masked);
                patched_count += 1;
            }
        }

        // 3. Raw ASCII
        let occurrences = find_all_occurrences(slice, &rule.from_raw_ascii);
        for idx in occurrences {
            if is_ascii_field_boundary(slice, idx, rule.from_raw_ascii.len(), 0x00) {
                let len = rule.to_raw_ascii.len();
                slice[idx..idx + len].copy_from_slice(&rule.to_raw_ascii);
                patched_count += 1;
            }
        }

        // 4. Raw UTF-16
        let occurrences = find_all_occurrences(slice, &rule.from_raw_utf16);
        for idx in occurrences {
            if is_utf16_field_boundary(slice, idx, rule.from_raw_utf16.len(), 0x00) {
                let len = rule.to_raw_utf16.len();
                slice[idx..idx + len].copy_from_slice(&rule.to_raw_utf16);
                patched_count += 1;
            }
        }
    }

    patched_count
}

/// Loads [db_injection], [teams], and [players] sections from sider.ini, with length verification and sorting.
pub fn load_db_injection_config_from_ini(ini_path: &Path) -> DbInjectionConfig {
    let mut config = DbInjectionConfig::default();
    if !ini_path.exists() {
        return config;
    }

    let mut raw_rules = Vec::new();
    let mut seen_keys = HashSet::new();

    if let Ok(file) = File::open(ini_path) {
        let reader = BufReader::new(file);
        let mut current_section = String::new();

        for line in reader.lines().map_while(Result::ok) {
            let line = line.trim();
            if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
                continue;
            }
            if line.starts_with('[') && line.ends_with(']') {
                current_section = line[1..line.len() - 1].trim().to_lowercase();
                continue;
            }

            if let Some((k_part, v_part)) = line.split_once('=') {
                let key = k_part.trim().trim_matches('"').trim_matches('\'').trim();
                let val = v_part.trim().trim_matches('"').trim_matches('\'').trim();

                if current_section == "db_injection" {
                    if key.eq_ignore_ascii_case("enabled") {
                        config.enabled = val == "1" || val.eq_ignore_ascii_case("true");
                    } else if key.eq_ignore_ascii_case("xor_mask") {
                        if let Ok(m) = if val.starts_with("0x") || val.starts_with("0X") {
                            u8::from_str_radix(&val[2..], 16)
                        } else {
                            val.parse::<u8>()
                        } {
                            config.xor_mask = m;
                        }
                    }
                } else if current_section == "teams" || current_section == "players" {
                    let is_player = current_section == "players";
                    if !seen_keys.insert((key.to_string(), is_player)) {
                        continue;
                    }

                    // Base rule
                    if let Some(rule) = create_replacement_rule(key, val, is_player, config.xor_mask) {
                        raw_rules.push(rule);
                    }

                    // Uppercase variation
                    let upper_key = key.to_uppercase();
                    let upper_val = val.to_uppercase();
                    if upper_key != key && seen_keys.insert((upper_key.clone(), is_player)) {
                        if let Some(rule) = create_replacement_rule(&upper_key, &upper_val, is_player, config.xor_mask) {
                            raw_rules.push(rule);
                        }
                    }

                    // Lowercase variation
                    let lower_key = key.to_lowercase();
                    let lower_val = val.to_lowercase();
                    if lower_key != key && seen_keys.insert((lower_key.clone(), is_player)) {
                        if let Some(rule) = create_replacement_rule(&lower_key, &lower_val, is_player, config.xor_mask) {
                            raw_rules.push(rule);
                        }
                    }
                }
            }
        }
    }

    // Sort descending by target length to prevent short prefixes from preempting longer strings
    raw_rules.sort_by_key(|b| std::cmp::Reverse(b.from_raw_ascii.len()));
    config.rules = raw_rules;
    config
}

/// Internal helper for scanning and patching a chunk using Read/WriteProcessMemory
#[allow(clippy::too_many_arguments)]
unsafe fn find_and_patch_process_chunk(
    h_proc: isize,
    target_read_addr: usize,
    slice: &[u8],
    needle: &[u8],
    replacement: &[u8],
    null_byte: u8,
    is_utf16: bool,
    from_name: &str,
    to_name: &str,
    fmt_name: &'static str,
) -> usize {
    let occurrences = find_all_occurrences(slice, needle);
    let mut patched = 0;

    for idx in occurrences {
        let is_valid = if is_utf16 {
            is_utf16_field_boundary(slice, idx, needle.len(), null_byte)
        } else {
            is_ascii_field_boundary(slice, idx, needle.len(), null_byte)
        };

        if is_valid {
            let write_addr = target_read_addr + idx;
            let mut bytes_written = 0usize;
            let ok = windows_sys::Win32::System::Diagnostics::Debug::WriteProcessMemory(
                h_proc,
                write_addr as _,
                replacement.as_ptr() as _,
                replacement.len(),
                &mut bytes_written,
            );

            if ok != 0 {
                patched += 1;
                let count = PATCH_LOG_COUNT.fetch_add(1, Ordering::Relaxed);
                if count < MAX_LOGGED_PATCHES {
                    crate::log_msg(&format!(
                        "[DB INJECTION] Patched '{}' -> '{}' at 0x{:X} (fmt={})",
                        from_name, to_name, write_addr, fmt_name
                    ));
                }
            }
        }
    }

    patched
}

/// Hardened process memory scanner:
/// 1. Uses ReadProcessMemory / WriteProcessMemory on self to avoid AV crashes on freed pages.
/// 2. Filters strictly for MEM_PRIVATE committed readable/writable heap/stack regions (excludes MEM_MAPPED and MEM_IMAGE).
/// 3. Validates boundary delimiters to prevent false positive overwrites.
pub fn scan_and_patch_process_memory(config: &DbInjectionConfig) -> usize {
    if !config.enabled || config.rules.is_empty() {
        return 0;
    }

    unsafe {
        use windows_sys::Win32::System::Diagnostics::Debug::ReadProcessMemory;
        use windows_sys::Win32::System::Memory::{
            VirtualQuery, MEMORY_BASIC_INFORMATION, MEM_COMMIT, MEM_PRIVATE,
            PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY, PAGE_GUARD, PAGE_NOACCESS,
            PAGE_READWRITE, PAGE_WRITECOPY,
        };
        use windows_sys::Win32::System::Threading::GetCurrentProcess;

        let h_proc = GetCurrentProcess();
        let mut addr: usize = 0x10000;
        let mut mbi: MEMORY_BASIC_INFORMATION = std::mem::zeroed();
        let max_addr = 0x00007FFFFFF00000usize;
        let mut total_patched = 0;

        let chunk_capacity = 2 * 1024 * 1024; // 2MB read buffer
        let mut read_buf = vec![0u8; chunk_capacity];

        while addr < max_addr {
            let res = VirtualQuery(
                addr as _,
                &mut mbi,
                std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
            );
            if res == 0 {
                break;
            }

            // Exclude MEM_MAPPED (prevents write-through to disk) and MEM_IMAGE; require MEM_PRIVATE
            let is_safe_private_rw = mbi.State == MEM_COMMIT
                && mbi.Type == MEM_PRIVATE
                && (mbi.Protect
                    & (PAGE_GUARD | PAGE_NOACCESS | PAGE_WRITECOPY | PAGE_EXECUTE_WRITECOPY)
                    == 0)
                && (mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE) != 0);

            if is_safe_private_rw && mbi.RegionSize >= 4 {
                let base = mbi.BaseAddress as usize;
                let size = mbi.RegionSize;

                let mut region_offset = 0;
                while region_offset < size {
                    let bytes_to_read = (size - region_offset).min(chunk_capacity);
                    let target_read_addr = base + region_offset;
                    let mut bytes_read = 0usize;

                    let ok = ReadProcessMemory(
                        h_proc,
                        target_read_addr as _,
                        read_buf.as_mut_ptr() as _,
                        bytes_to_read,
                        &mut bytes_read,
                    );

                    if ok != 0 && bytes_read >= 4 {
                        let slice = &read_buf[..bytes_read];
                        for rule in &config.rules {
                            // 1. XOR ASCII
                            total_patched += find_and_patch_process_chunk(
                                h_proc,
                                target_read_addr,
                                slice,
                                &rule.from_ascii_masked,
                                &rule.to_ascii_masked,
                                config.xor_mask,
                                false,
                                &rule.original_from,
                                &rule.original_to,
                                "XOR_ASCII",
                            );
                            // 2. XOR UTF-16
                            total_patched += find_and_patch_process_chunk(
                                h_proc,
                                target_read_addr,
                                slice,
                                &rule.from_utf16_masked,
                                &rule.to_utf16_masked,
                                config.xor_mask,
                                true,
                                &rule.original_from,
                                &rule.original_to,
                                "XOR_UTF16",
                            );
                            // 3. Raw ASCII
                            total_patched += find_and_patch_process_chunk(
                                h_proc,
                                target_read_addr,
                                slice,
                                &rule.from_raw_ascii,
                                &rule.to_raw_ascii,
                                0x00,
                                false,
                                &rule.original_from,
                                &rule.original_to,
                                "RAW_ASCII",
                            );
                            // 4. Raw UTF-16
                            total_patched += find_and_patch_process_chunk(
                                h_proc,
                                target_read_addr,
                                slice,
                                &rule.from_raw_utf16,
                                &rule.to_raw_utf16,
                                0x00,
                                true,
                                &rule.original_from,
                                &rule.original_to,
                                "RAW_UTF16",
                            );
                        }
                    }

                    region_offset += bytes_to_read;
                }
            }

            let next_addr = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
            if next_addr <= addr {
                break;
            }
            addr = next_addr;
        }

        total_patched
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_padding_xor_encoding_correctness() {
        let rule = create_replacement_rule("London FC", "Arsenal", false, 0x6B).unwrap();

        assert_eq!(rule.from_ascii_masked.len(), 9);
        assert_eq!(rule.to_ascii_masked.len(), 9);

        // The padded tail (positions 7 and 8) should be 0x00 ^ 0x6B = 0x6B
        assert_eq!(rule.to_ascii_masked[7], 0x6B);
        assert_eq!(rule.to_ascii_masked[8], 0x6B);

        // Decrypted to_ascii_masked should equal "Arsenal\0\0"
        let decrypted: Vec<u8> = rule.to_ascii_masked.iter().map(|&b| b ^ 0x6B).collect();
        assert_eq!(&decrypted[..7], b"Arsenal");
        assert_eq!(decrypted[7], 0x00);
        assert_eq!(decrypted[8], 0x00);
    }

    #[test]
    fn test_rule_rejection_when_to_longer_than_from() {
        // "Arsenal" (7) -> "Real Madrid" (11) must be rejected
        let res = create_replacement_rule("Arsenal", "Real Madrid", false, 0x6B);
        assert!(res.is_none());
    }

    #[test]
    fn test_boundary_validation_positive_and_negative() {
        let mask = 0x6B;
        let null_masked = 0x00 ^ mask; // 0x6B

        // Case 1: Valid boundary [0x6B, 'L'^0x6B, ..., 'C'^0x6B, 0x6B]
        let mut valid_buf = vec![null_masked];
        valid_buf.extend(b"London FC".iter().map(|&b| b ^ mask));
        valid_buf.push(null_masked);

        assert!(is_ascii_field_boundary(&valid_buf, 1, 9, null_masked));

        // Case 2: Invalid boundary (embedded in larger word: 'X'^0x6B, 'L'^0x6B, ..., 'C'^0x6B, 'Y'^0x6B)
        let mut invalid_buf = vec![b'X' ^ mask];
        invalid_buf.extend(b"London FC".iter().map(|&b| b ^ mask));
        invalid_buf.push(b'Y' ^ mask);

        assert!(!is_ascii_field_boundary(&invalid_buf, 1, 9, null_masked));
    }

    #[test]
    fn test_simulated_memory_slice_patch() {
        let rule = create_replacement_rule("London FC", "Arsenal", false, 0x6B).unwrap();
        let rules = vec![rule];

        let null_masked = 0x00 ^ 0x6B;
        let mut mem = vec![null_masked];
        mem.extend(b"London FC".iter().map(|&b| b ^ 0x6B));
        mem.push(null_masked);

        let patched = scan_and_patch_slice(&mut mem, &rules, 0x6B);
        assert_eq!(patched, 1);

        // Verify that mem[1..8] is "Arsenal" ^ 0x6B and mem[8..10] is 0x6B
        let decrypted: Vec<u8> = mem[1..10].iter().map(|&b| b ^ 0x6B).collect();
        assert_eq!(&decrypted[..7], b"Arsenal");
        assert_eq!(decrypted[7], 0x00);
        assert_eq!(decrypted[8], 0x00);
    }

    #[test]
    fn test_rules_sorted_by_length_descending() {
        use std::io::Write;
        let temp_dir = std::env::temp_dir();
        let ini_path = temp_dir.join("test_sider_rules.ini");

        {
            let mut f = File::create(&ini_path).unwrap();
            writeln!(f, "[db_injection]").unwrap();
            writeln!(f, "enabled = 1").unwrap();
            writeln!(f, "xor_mask = 0x6B").unwrap();
            writeln!(f, "[teams]").unwrap();
            writeln!(f, "FC = A").unwrap();
            writeln!(f, "London FC = Arsenal").unwrap();
        }

        let cfg = load_db_injection_config_from_ini(&ini_path);
        assert!(cfg.enabled);
        assert_eq!(cfg.xor_mask, 0x6B);
        assert!(!cfg.rules.is_empty());
        // First rule should have the longest from_raw_ascii length ("London FC" vs "FC")
        assert!(cfg.rules[0].from_raw_ascii.len() >= cfg.rules.last().unwrap().from_raw_ascii.len());

        let _ = std::fs::remove_file(ini_path);
    }
}
