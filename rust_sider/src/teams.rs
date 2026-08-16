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
    VirtualQuery, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_GUARD, PAGE_NOACCESS,
    PAGE_READONLY, PAGE_READWRITE, PAGE_WRITECOPY,
};
use windows_sys::Win32::System::Threading::GetCurrentProcess;

pub struct ActiveMod {
    pub name: String,
    pub path: PathBuf,
}

#[derive(Clone, Debug)]
pub struct TeamReplacement {
    pub from_bytes: Vec<u8>,
    pub to_bytes: Vec<u8>,
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

fn add_string_variants(rules: &mut Vec<TeamReplacement>, from_str: &str, to_str: &str) {
    let from_trimmed = from_str.trim();
    let to_trimmed = to_str.trim();

    if from_trimmed.is_empty() || to_trimmed.is_empty() || from_trimmed == to_trimmed || from_trimmed.len() < 3 {
        return;
    }

    // 1. Exact case ASCII / UTF-8
    let from_ascii = from_trimmed.as_bytes().to_vec();
    let mut to_ascii = to_trimmed.as_bytes().to_vec();
    if to_ascii.len() < from_ascii.len() {
        to_ascii.resize(from_ascii.len(), 0);
    } else if to_ascii.len() > from_ascii.len() {
        to_ascii.truncate(from_ascii.len());
    }
    rules.push(TeamReplacement {
        from_bytes: from_ascii,
        to_bytes: to_ascii,
        original_from: from_trimmed.to_string(),
        original_to: to_trimmed.to_string(),
    });

    // 2. UPPERCASE ASCII
    let from_upper = from_trimmed.to_uppercase();
    let to_upper = to_trimmed.to_uppercase();
    let from_upper_ascii = from_upper.as_bytes().to_vec();
    let mut to_upper_ascii = to_upper.as_bytes().to_vec();
    if to_upper_ascii.len() < from_upper_ascii.len() {
        to_upper_ascii.resize(from_upper_ascii.len(), 0);
    } else if to_upper_ascii.len() > from_upper_ascii.len() {
        to_upper_ascii.truncate(from_upper_ascii.len());
    }
    if from_upper_ascii != from_trimmed.as_bytes() {
        rules.push(TeamReplacement {
            from_bytes: from_upper_ascii,
            to_bytes: to_upper_ascii,
            original_from: from_upper,
            original_to: to_upper,
        });
    }

    // 3. Exact case UTF-16LE
    let from_u16: Vec<u16> = from_trimmed.encode_utf16().collect();
    let from_utf16: Vec<u8> = from_u16.iter().flat_map(|&w| w.to_le_bytes()).collect();

    let mut to_u16: Vec<u16> = to_trimmed.encode_utf16().collect();
    if to_u16.len() < from_u16.len() {
        to_u16.resize(from_u16.len(), 0);
    } else if to_u16.len() > from_u16.len() {
        to_u16.truncate(from_u16.len());
    }
    let to_utf16: Vec<u8> = to_u16.iter().flat_map(|&w| w.to_le_bytes()).collect();

    rules.push(TeamReplacement {
        from_bytes: from_utf16,
        to_bytes: to_utf16,
        original_from: format!("{} (UTF16)", from_trimmed),
        original_to: format!("{} (UTF16)", to_trimmed),
    });

    // 4. UPPERCASE UTF-16LE
    let from_u16_up: Vec<u16> = from_trimmed.to_uppercase().encode_utf16().collect();
    let from_utf16_up: Vec<u8> = from_u16_up.iter().flat_map(|&w| w.to_le_bytes()).collect();

    let mut to_u16_up: Vec<u16> = to_trimmed.to_uppercase().encode_utf16().collect();
    if to_u16_up.len() < from_u16_up.len() {
        to_u16_up.resize(from_u16_up.len(), 0);
    } else if to_u16_up.len() > from_u16_up.len() {
        to_u16_up.truncate(from_u16_up.len());
    }
    let to_utf16_up: Vec<u8> = to_u16_up.iter().flat_map(|&w| w.to_le_bytes()).collect();

    if from_utf16_up != from_trimmed.encode_utf16().flat_map(|w| w.to_le_bytes()).collect::<Vec<u8>>() {
        rules.push(TeamReplacement {
            from_bytes: from_utf16_up,
            to_bytes: to_utf16_up,
            original_from: format!("{} (UTF16-UPPER)", from_trimmed),
            original_to: format!("{} (UTF16-UPPER)", to_trimmed),
        });
    }
}

pub fn load_team_rules_from_database(roots: &[PathBuf]) -> Vec<TeamReplacement> {
    let mut rules = Vec::new();

    // Check candidate folders for custom database
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
                            crate::log_msg(&format!("[TEAMS DYNAMIC RULE] '{}' -> '{}'", from_name, to_name));
                            add_string_variants(&mut rules, &from_name, &to_name);
                        }
                        return rules;
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
                            if let Some((van_name, van_short)) = van_map.get(&tid) {
                                let raw_mod_name = &chunk[396..396 + 70];
                                let mod_name_end = raw_mod_name.iter().position(|&b| b == 0).unwrap_or(70);
                                let mod_name = String::from_utf8_lossy(&raw_mod_name[..mod_name_end]).trim().to_string();

                                if !mod_name.is_empty() && !van_name.is_empty() && &mod_name != van_name {
                                    crate::log_msg(&format!("[TEAMS DYNAMIC RULE] Team #{} Name: '{}' -> '{}'", tid, van_name, mod_name));
                                    add_string_variants(&mut rules, van_name, &mod_name);
                                }

                                let raw_mod_short = &chunk[886..886 + 10];
                                let mod_short_end = raw_mod_short.iter().position(|&b| b == 0).unwrap_or(10);
                                let mod_short = String::from_utf8_lossy(&raw_mod_short[..mod_short_end]).trim().to_string();

                                if !mod_short.is_empty() && !van_short.is_empty() && &mod_short != van_short && van_short.len() >= 3 {
                                    crate::log_msg(&format!("[TEAMS DYNAMIC RULE] Team #{} Code: '{}' -> '{}'", tid, van_short, mod_short));
                                    add_string_variants(&mut rules, van_short, &mod_short);
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
        // Short delay to let engine initialize memory mappings
        thread::sleep(Duration::from_secs(5));

        let process_handle: HANDLE = unsafe { GetCurrentProcess() };
        let mut buffer = vec![0u8; 4 * 1024 * 1024]; // 4MB buffer for safe kernel reads
        let mut loop_count = 0u64;

        loop {
            thread::sleep(Duration::from_millis(2000));
            loop_count += 1;

            // Periodically reload rules from database
            if loop_count % 10 == 1 {
                let loaded = load_team_rules_from_database(&roots);
                if !loaded.is_empty() {
                    if let Ok(mut g) = RULES.write() {
                        if g.len() != loaded.len() {
                            crate::log_msg(&format!(
                                "[TEAMS] Dynamic Database-Driven Team Patcher active with {} pattern variants.",
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

            let mut addr = 0x10000usize; // Start at 64KB (all user-mode memory)
            let max_addr = 0x7FFFFFFF0000usize;
            let mut mbi: MEMORY_BASIC_INFORMATION = unsafe { std::mem::zeroed() };
            let mut total_replacements = 0usize;

            while addr < max_addr {
                let res = unsafe {
                    VirtualQuery(
                        addr as *const _,
                        &mut mbi,
                        std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
                    )
                };
                if res == 0 {
                    break;
                }

                // Check committed data pages (skip guarded or no-access pages)
                let is_data_page = mbi.State == MEM_COMMIT
                    && (mbi.Protect & (PAGE_READWRITE | PAGE_WRITECOPY | PAGE_READONLY) != 0)
                    && (mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS) == 0)
                    && mbi.RegionSize > 0
                    && mbi.RegionSize <= 64 * 1024 * 1024;

                if is_data_page {
                    let base = mbi.BaseAddress as usize;
                    let size = mbi.RegionSize;

                    // Read safely via Windows Kernel API
                    let to_read = size.min(buffer.len());
                    let mut bytes_read = 0usize;

                    let ok = unsafe {
                        ReadProcessMemory(
                            process_handle,
                            base as *const _,
                            buffer.as_mut_ptr() as *mut _,
                            to_read,
                            &mut bytes_read,
                        )
                    };

                    if ok != 0 && bytes_read > 0 {
                        let chunk = &buffer[..bytes_read];

                        for rule in &current_rules {
                            let rule_len = rule.from_bytes.len();
                            if bytes_read >= rule_len {
                                let mut pos = 0;
                                while pos + rule_len <= bytes_read {
                                    if &chunk[pos..pos + rule_len] == rule.from_bytes.as_slice() {
                                        let target_addr = base + pos;
                                        let mut bytes_written = 0usize;
                                        unsafe {
                                            WriteProcessMemory(
                                                process_handle,
                                                target_addr as *mut _,
                                                rule.to_bytes.as_ptr() as *const _,
                                                rule_len,
                                                &mut bytes_written,
                                            );
                                        }
                                        total_replacements += 1;
                                        pos += rule_len;
                                    } else {
                                        pos += 1;
                                    }
                                }
                            }
                        }
                    }
                }

                let next_addr = (mbi.BaseAddress as usize).saturating_add(mbi.RegionSize);
                if next_addr <= addr {
                    break;
                }
                addr = next_addr;
            }

            if total_replacements > 0 {
                crate::log_msg(&format!(
                    "[TEAMS SYNC] Overwrote {} instances of Konami Live Update names in RAM.",
                    total_replacements
                ));
            }
        }
    });
}
