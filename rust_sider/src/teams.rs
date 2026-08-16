use std::collections::HashMap;
use std::fs::File;
use std::io::{BufRead, BufReader, Read};
use std::path::{Path, PathBuf};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::RwLock;
use std::thread;
use std::time::Duration;
use windows_sys::Win32::Foundation::HANDLE;
use windows_sys::Win32::System::Diagnostics::Debug::{ReadProcessMemory, WriteProcessMemory};
use windows_sys::Win32::System::Memory::{
    VirtualQuery, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_EXECUTE,
    PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY, PAGE_GUARD, PAGE_NOACCESS,
    PAGE_READONLY, PAGE_READWRITE, PAGE_WRITECOPY,
};
use windows_sys::Win32::System::Threading::GetCurrentProcess;

pub struct ActiveMod {
    pub name: String,
    pub path: PathBuf,
}

#[derive(Clone, Debug)]
pub struct TeamReplacement {
    pub query_lower_ascii: Vec<u8>,
    pub query_lower_u16: Vec<u16>,
    pub replacement_ascii: Vec<u8>,
    pub replacement_u16: Vec<u16>,
    pub original_from: String,
    pub original_to: String,
}

static RULES: RwLock<Vec<TeamReplacement>> = RwLock::new(Vec::new());
static PATCHER_RUNNING: AtomicBool = AtomicBool::new(false);

pub fn load_active_mods_from_sider_ini(sider_ini_path: &Path) -> Vec<ActiveMod> {
    let mut mods = Vec::new();
    if !sider_ini_path.exists() {
        return mods;
    }
    let base_dir = sider_ini_path.parent().unwrap_or(Path::new("."));
    let game_root = base_dir.parent().and_then(|p| p.parent()).and_then(|p| p.parent()).unwrap_or(base_dir);

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
                        let candidate_paths = [
                            PathBuf::from(raw_val),
                            base_dir.join(raw_val),
                            game_root.join(raw_val),
                            game_root.join("content").join(raw_val),
                        ];

                        let full_path = candidate_paths
                            .into_iter()
                            .find(|p| p.exists())
                            .unwrap_or_else(|| base_dir.join(raw_val));

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

fn parse_simple_json_pairs(content: &str) -> Vec<(String, String)> {
    let mut pairs = Vec::new();
    let mut inside_quote = false;
    let mut current_str = String::new();
    let mut current_pair = Vec::new();

    for ch in content.chars() {
        if ch == '"' {
            inside_quote = !inside_quote;
            if !inside_quote {
                current_pair.push(current_str.clone());
                current_str.clear();
                if current_pair.len() == 2 {
                    pairs.push((current_pair[0].clone(), current_pair[1].clone()));
                    current_pair.clear();
                }
            }
        } else if inside_quote {
            current_str.push(ch);
        }
    }
    pairs
}

fn create_rule(from_str: &str, to_str: &str) -> Option<TeamReplacement> {
    let from_trimmed = from_str.trim();
    let to_trimmed = to_str.trim();

    if from_trimmed.is_empty() || to_trimmed.is_empty() || from_trimmed == to_trimmed || from_trimmed.len() < 5 {
        return None;
    }

    let query_lower_ascii = from_trimmed.to_ascii_lowercase().as_bytes().to_vec();
    let query_lower_u16: Vec<u16> = from_trimmed.to_lowercase().encode_utf16().collect();

    let replacement_ascii = to_trimmed.as_bytes().to_vec();
    let replacement_u16: Vec<u16> = to_trimmed.encode_utf16().collect();

    Some(TeamReplacement {
        query_lower_ascii,
        query_lower_u16,
        replacement_ascii,
        replacement_u16,
        original_from: from_trimmed.to_string(),
        original_to: to_trimmed.to_string(),
    })
}

fn add_rule_variants(rules: &mut Vec<TeamReplacement>, from_str: &str, to_str: &str) {
    if let Some(r) = create_rule(from_str, to_str) {
        rules.push(r);
    }

    // Strip fake suffixes like " B", " RB", " WB", " BN", " A", " R", " W"
    for suffix in &[" B", " RB", " WB", " BN", " A", " R", " W", " G", " YB", " BV", " RA", " AA", " BW", " RW", " BA", " BR", " BC"] {
        if from_str.ends_with(suffix) {
            let stripped = &from_str[..from_str.len() - suffix.len()];
            if stripped.len() >= 5 {
                if let Some(r) = create_rule(stripped, to_str) {
                    rules.push(r);
                }
            }
        }
    }
}

pub fn load_team_rules_from_database(roots: &[PathBuf]) -> Vec<TeamReplacement> {
    let mut rules = Vec::new();

    let mut search_dirs = Vec::new();
    for r in roots {
        search_dirs.push(r.clone());
        search_dirs.push(r.join("common").join("etc").join("pesdb"));
    }
    search_dirs.push(PathBuf::from(r"content\database\common\etc\pesdb"));
    search_dirs.push(PathBuf::from(r"..\..\..\content\database\common\etc\pesdb"));
    search_dirs.push(PathBuf::from(r"A:\SteamLibrary\steamapps\common\eFootball\content\database\common\etc\pesdb"));

    for dir in search_dirs {
        // Priority 1: Check team_replacements.json
        let json_path = if dir.is_file() {
            dir.with_file_name("team_replacements.json")
        } else {
            dir.join("team_replacements.json")
        };

        if json_path.is_file() {
            if let Ok(mut f) = File::open(&json_path) {
                let mut content = String::new();
                if f.read_to_string(&mut content).is_ok() {
                    let pairs = parse_simple_json_pairs(&content);
                    if !pairs.is_empty() {
                        crate::log_msg(&format!(
                            "[TEAMS] Loaded {} dynamic replacement rules from {:?}",
                            pairs.len(),
                            json_path
                        ));
                        for (from_name, to_name) in pairs {
                            if from_name.len() >= 5 {
                                crate::log_msg(&format!("[TEAMS DYNAMIC RULE] '{}' -> '{}'", from_name, to_name));
                                add_rule_variants(&mut rules, &from_name, &to_name);
                            }
                        }
                        if !rules.is_empty() {
                            return rules;
                        }
                    }
                }
            }
        }

        // Priority 2: Binary comparison between Team.bin and Team.bin.vanilla
        let team_bin = if dir.is_file() { dir.clone() } else { dir.join("Team.bin") };
        let vanilla_bin = if dir.is_file() {
            dir.with_file_name("Team.bin.vanilla")
        } else {
            dir.join("Team.bin.vanilla")
        };

        if team_bin.is_file() && vanilla_bin.is_file() {
            if let (Ok(mut f_mod), Ok(mut f_van)) = (File::open(&team_bin), File::open(&vanilla_bin)) {
                let mut mod_data = Vec::new();
                let mut van_data = Vec::new();
                if f_mod.read_to_end(&mut mod_data).is_ok() && f_van.read_to_end(&mut van_data).is_ok() {
                    if mod_data.len() >= 1600 && van_data.len() >= 1600 {
                        let mut van_map: HashMap<u32, (String, String)> = HashMap::new();
                        for chunk in van_data.chunks_exact(1600) {
                            let tid = u32::from_le_bytes(chunk[12..16].try_into().unwrap_or([0; 4]));
                            let raw_name = &chunk[396..396 + 70];
                            let name_end = raw_name.iter().position(|&b| b == 0).unwrap_or(70);
                            let name = String::from_utf8_lossy(&raw_name[..name_end]).trim().to_string();

                            let raw_short = &chunk[886..886 + 10];
                            let short_end = raw_short.iter().position(|&b| b == 0).unwrap_or(10);
                            let short = String::from_utf8_lossy(&raw_short[..short_end]).trim().to_string();

                            van_map.insert(tid, (name, short));
                        }

                        for chunk in mod_data.chunks_exact(1600) {
                            let tid = u32::from_le_bytes(chunk[12..16].try_into().unwrap_or([0; 4]));
                            if let Some((van_name, _van_short)) = van_map.get(&tid) {
                                let raw_mod_name = &chunk[396..396 + 70];
                                let mod_name_end = raw_mod_name.iter().position(|&b| b == 0).unwrap_or(70);
                                let mod_name = String::from_utf8_lossy(&raw_mod_name[..mod_name_end]).trim().to_string();

                                if !mod_name.is_empty() && !van_name.is_empty() && &mod_name != van_name && van_name.len() >= 5 {
                                    crate::log_msg(&format!("[TEAMS DYNAMIC RULE] Team #{} Name: '{}' -> '{}'", tid, van_name, mod_name));
                                    add_rule_variants(&mut rules, van_name, &mod_name);
                                }
                            }
                        }

                        if !rules.is_empty() {
                            return rules;
                        }
                    }
                }
            }
        }
    }

    rules
}

pub fn start_database_team_syncer(roots: Vec<PathBuf>) {
    if PATCHER_RUNNING.swap(true, Ordering::SeqCst) {
        return;
    }

    thread::spawn(move || {
        let process_handle: HANDLE = unsafe { GetCurrentProcess() };
        let mut buffer = vec![0u8; 16 * 1024 * 1024]; // 16MB buffer
        let mut loop_count = 0u64;

        // Give the game engine 4 seconds to finish initial boot before syncing
        thread::sleep(Duration::from_secs(4));

        loop {
            thread::sleep(Duration::from_millis(1500));
            loop_count += 1;

            // Periodically reload rules from database
            if loop_count % 10 == 1 {
                let loaded = load_team_rules_from_database(&roots);
                if !loaded.is_empty() {
                    if let Ok(mut g) = RULES.write() {
                        if g.len() != loaded.len() {
                            crate::log_msg(&format!(
                                "[TEAMS] Dynamic Database-Driven Team Patcher active with {} search patterns.",
                                loaded.len()
                            ));
                        }
                        *g = loaded;
                    }
                }
            }

            let current_rules = match RULES.read() {
                Ok(g) => g.clone(),
                Err(_) => continue,
            };

            if current_rules.is_empty() {
                continue;
            }

            let mut address = 0x10000usize;
            let max_address = 0x00007FFFFFFFFFF0usize;
            let mut mbi: MEMORY_BASIC_INFORMATION = unsafe { std::mem::zeroed() };
            let mut total_replacements = 0usize;

            while address < max_address {
                let res = unsafe {
                    VirtualQuery(
                        address as *const _,
                        &mut mbi,
                        std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                    )
                };
                if res == 0 {
                    break;
                }

                let is_code_sec = (mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) != 0;
                let is_readable = mbi.State == MEM_COMMIT
                    && (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS) == 0)
                    && (mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY) != 0)
                    && mbi.RegionSize > 0
                    && mbi.RegionSize <= buffer.len();

                if is_readable && !is_code_sec {
                    let base = mbi.BaseAddress as usize;
                    let size = mbi.RegionSize;
                    let mut bytes_read = 0usize;

                    let ok = unsafe {
                        ReadProcessMemory(
                            process_handle,
                            base as *const _,
                            buffer.as_mut_ptr() as *mut _,
                            size,
                            &mut bytes_read,
                        )
                    };

                    if ok != 0 && bytes_read > 0 {
                        let chunk = &buffer[..bytes_read];

                        for rule in &current_rules {
                            let q_len_ascii = rule.query_lower_ascii.len();
                            let q_len_u16 = rule.query_lower_u16.len();

                            // 1. Case-Insensitive ASCII Search & Exact-Length Null-Padded Inject
                            if bytes_read >= q_len_ascii {
                                let mut pos = 0;
                                while pos + q_len_ascii <= bytes_read {
                                    let mut matches = true;
                                    for i in 0..q_len_ascii {
                                        if chunk[pos + i].to_ascii_lowercase() != rule.query_lower_ascii[i] {
                                            matches = false;
                                            break;
                                        }
                                    }

                                    if matches {
                                        let snippet_len = (bytes_read - pos).min(q_len_ascii + 24);
                                        let snippet = &chunk[pos..pos + snippet_len];
                                        let is_path = snippet.contains(&b'/')
                                            || snippet.contains(&b'\\')
                                            || snippet.windows(7).any(|w| w == b".uasset")
                                            || snippet.windows(6).any(|w| w == b".ubulk");

                                        if !is_path {
                                            let is_upper = chunk[pos..pos + q_len_ascii]
                                                .iter()
                                                .filter(|&&b| b.is_ascii_alphabetic())
                                                .all(|&b| b.is_ascii_uppercase());

                                            let mut payload = if is_upper {
                                                rule.original_to.to_uppercase().into_bytes()
                                            } else {
                                                rule.replacement_ascii.clone()
                                            };

                                            // Exactly q_len_ascii bytes, null-padded (\0)
                                            if payload.len() < q_len_ascii {
                                                payload.resize(q_len_ascii, 0);
                                            } else if payload.len() > q_len_ascii {
                                                payload.truncate(q_len_ascii);
                                            }

                                            let target_addr = base + pos;
                                            let mut bytes_written = 0usize;

                                            unsafe {
                                                WriteProcessMemory(
                                                    process_handle,
                                                    target_addr as *mut _,
                                                    payload.as_ptr() as *const _,
                                                    q_len_ascii,
                                                    &mut bytes_written,
                                                );
                                            }
                                            total_replacements += 1;
                                            pos += q_len_ascii;
                                            continue;
                                        }
                                    }
                                    pos += 1;
                                }
                            }

                            // 2. Case-Insensitive UTF-16 Search & Exact-Length Null-Padded Inject
                            let q_bytes_u16 = q_len_u16 * 2;
                            if bytes_read >= q_bytes_u16 {
                                let mut pos = 0;
                                while pos + q_bytes_u16 <= bytes_read {
                                    let mut matches = true;
                                    for i in 0..q_len_u16 {
                                        let ch_u16 = u16::from_le_bytes([chunk[pos + i * 2], chunk[pos + i * 2 + 1]]);
                                        let ch_lower = if ch_u16 <= 0x7F {
                                            (ch_u16 as u8).to_ascii_lowercase() as u16
                                        } else {
                                            ch_u16
                                        };
                                        if ch_lower != rule.query_lower_u16[i] {
                                            matches = false;
                                            break;
                                        }
                                    }

                                    if matches {
                                        let target_addr = base + pos;

                                        let mut is_upper = true;
                                        for i in 0..q_len_u16 {
                                            let ch = u16::from_le_bytes([chunk[pos + i * 2], chunk[pos + i * 2 + 1]]);
                                            if ch >= 'a' as u16 && ch <= 'z' as u16 {
                                                is_upper = false;
                                                break;
                                            }
                                        }

                                        let mut u16_payload = if is_upper {
                                            rule.original_to.to_uppercase().encode_utf16().collect::<Vec<u16>>()
                                        } else {
                                            rule.replacement_u16.clone()
                                        };

                                        // Exactly q_len_u16 UTF-16 elements, null-padded (0x0000)
                                        if u16_payload.len() < q_len_u16 {
                                            u16_payload.resize(q_len_u16, 0);
                                        } else if u16_payload.len() > q_len_u16 {
                                            u16_payload.truncate(q_len_u16);
                                        }

                                        let byte_payload: Vec<u8> = u16_payload.iter().flat_map(|&w| w.to_le_bytes()).collect();
                                        let mut bytes_written = 0usize;

                                        unsafe {
                                            WriteProcessMemory(
                                                process_handle,
                                                target_addr as *mut _,
                                                byte_payload.as_ptr() as *const _,
                                                byte_payload.len(),
                                                &mut bytes_written,
                                            );
                                        }
                                        total_replacements += 1;
                                        pos += byte_payload.len();
                                        continue;
                                    }
                                    pos += 2;
                                }
                            }
                        }
                    }
                }

                let next_addr = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
                if next_addr <= address || next_addr >= max_address {
                    break;
                }
                address = next_addr;
            }

            if total_replacements > 0 {
                crate::log_msg(&format!(
                    "[TEAMS SMART INJECTOR] Successfully injected {} UI text strings in RAM.",
                    total_replacements
                ));
            }
        }
    });
}
