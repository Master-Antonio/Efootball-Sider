use std::fs::File;
use std::io::{BufRead, BufReader};
use std::path::{Path, PathBuf};
const XOR_KEY: u8 = 0x6B;
#[derive(Clone)]
pub struct TeamReplacement {
    pub from_ascii_masked: Vec<u8>,
    pub to_ascii: Vec<u8>,
    pub from_utf16_masked: Vec<u8>,
    pub to_utf16: Vec<u8>,
    pub from_len_ascii: usize,
    pub from_len_utf16: usize,
    pub original_from: String,
    pub original_to: String,
}
pub struct ActiveMod {
    pub name: String,
    pub path: PathBuf,
}
pub fn load_active_mods_from_sider_ini(sider_ini_path: &Path) -> Vec<ActiveMod> {
    let mut mods = Vec::new();
    if !sider_ini_path.exists() {
        return mods;
    }
    let base_dir = sider_ini_path.parent().unwrap_or(Path::new("."));
    if let Ok(file) = File::open(sider_ini_path) {
        let reader = BufReader::new(file);
        for line in reader.lines().flatten() {
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
                        let mod_name = full_path.file_name().unwrap_or_default().to_string_lossy().to_string();
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
fn create_padded_rule(from: &str, to: &str) -> Option<TeamReplacement> {
    let from_trimmed = from.trim();
    let to_trimmed = to.trim();
    if from_trimmed.len() < 4 || to_trimmed.is_empty() {
        return None;
    }
    if from_trimmed.eq_ignore_ascii_case(to_trimmed) {
        return None;
    }
    let target_len = from_trimmed.len();
    let mut padded_to = to_trimmed.to_string();
    if padded_to.len() < target_len {
        padded_to.push_str(&" ".repeat(target_len - padded_to.len()));
    } else if padded_to.len() > target_len {
        padded_to.truncate(target_len);
    }
    let from_ascii_masked: Vec<u8> = from_trimmed.as_bytes().iter().map(|b| b ^ XOR_KEY).collect();
    let to_ascii = padded_to.as_bytes().to_vec();
    let from_utf16_raw: Vec<u8> = from_trimmed.encode_utf16().flat_map(|u| u.to_le_bytes()).collect();
    let from_utf16_masked: Vec<u8> = from_utf16_raw.iter().map(|b| b ^ XOR_KEY).collect();
    let to_utf16: Vec<u8> = padded_to.encode_utf16().flat_map(|u| u.to_le_bytes()).collect();
    let from_len_ascii = from_ascii_masked.len();
    let from_len_utf16 = from_utf16_masked.len();
    Some(TeamReplacement {
        from_ascii_masked,
        to_ascii,
        from_utf16_masked,
        to_utf16,
        from_len_ascii,
        from_len_utf16,
        original_from: from_trimmed.to_string(),
        original_to: padded_to,
    })
}
pub fn load_replacements_from_ini(ini_path: &Path) -> Vec<TeamReplacement> {
    let mut replacements = Vec::new();
    if !ini_path.exists() {
        return replacements;
    }
    if let Ok(file) = File::open(ini_path) {
        let reader = BufReader::new(file);
        let mut in_teams_section = false;
        for line in reader.lines().flatten() {
            let line = line.trim();
            if line.is_empty() || line.starts_with(';') || line.starts_with('#') {
                continue;
            }
            if line.starts_with('[') && line.ends_with(']') {
                let sec_name = line[1..line.len() - 1].trim().to_lowercase();
                in_teams_section = sec_name == "teams";
                continue;
            }
            if let Some((from_part, to_part)) = line.split_once('=') {
                let from = from_part.trim().trim_matches('"').trim_matches('\'').trim();
                let to = to_part.trim().trim_matches('"').trim_matches('\'').trim();
                if from.eq_ignore_ascii_case("name") 
                    || from.eq_ignore_ascii_case("author") 
                    || from.eq_ignore_ascii_case("version") 
                    || from.eq_ignore_ascii_case("category") 
                    || from.eq_ignore_ascii_case("description") 
                    || from.eq_ignore_ascii_case("mods_directory") 
                    || from.eq_ignore_ascii_case("cpk.root") {
                    if !in_teams_section {
                        continue;
                    }
                }
                if let Some(rule) = create_padded_rule(from, to) {
                    replacements.push(rule);
                }
                let upper_from = from.to_uppercase();
                let upper_to = to.to_uppercase();
                if upper_from != from {
                    if let Some(rule) = create_padded_rule(&upper_from, &upper_to) {
                        replacements.push(rule);
                    }
                }
                let lower_from = from.to_lowercase();
                let lower_to = to.to_lowercase();
                if lower_from != from {
                    if let Some(rule) = create_padded_rule(&lower_from, &lower_to) {
                        replacements.push(rule);
                    }
                }
            }
        }
    }
    replacements.sort_by(|a, b| b.from_len_ascii.cmp(&a.from_len_ascii));
    replacements
}
