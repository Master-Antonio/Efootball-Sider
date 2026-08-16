use retour::GenericDetour;
use std::collections::HashMap;
use std::path::PathBuf;
use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::{OnceLock, RwLock};
use walkdir::WalkDir;
use windows_sys::Win32::Foundation::{HANDLE, INVALID_HANDLE_VALUE};
use windows_sys::Win32::Security::SECURITY_ATTRIBUTES;
use windows_sys::Win32::System::LibraryLoader::{GetModuleHandleA, GetProcAddress};

type FnCreateFileW = unsafe extern "system" fn(
    lp_file_name: *const u16,
    dw_desired_access: u32,
    dw_share_mode: u32,
    lp_security_attributes: *const SECURITY_ATTRIBUTES,
    dw_creation_disposition: u32,
    dw_flags_and_attributes: u32,
    h_template_file: HANDLE,
) -> HANDLE;

pub struct VfsTable {
    pub rel_map: HashMap<String, PathBuf>,
    pub basename_map: HashMap<String, PathBuf>,
}

static HOOK_CREATE_FILE_W: OnceLock<GenericDetour<FnCreateFileW>> = OnceLock::new();
static VFS_MAP: RwLock<Option<VfsTable>> = RwLock::new(None);
static ACTIVE_ROOTS: RwLock<Vec<PathBuf>> = RwLock::new(Vec::new());
static OVERRIDE_LOG_COUNT: AtomicUsize = AtomicUsize::new(0);
static BASENAME_LOG_COUNT: AtomicUsize = AtomicUsize::new(0);
const MAX_LOGGED_OVERRIDES: usize = 20;

pub fn init_livecpk_vfs(mod_roots: Vec<PathBuf>) {
    let mut rel_map = HashMap::new();
    let mut basename_map = HashMap::new();
    let mut active_roots_list = Vec::new();
    let mut indexed_count = 0;

    for root in &mod_roots {
        if !root.exists() {
            continue;
        }
        active_roots_list.push(root.clone());
        for entry in WalkDir::new(root).into_iter().filter_map(|e| e.ok()) {
            let p = entry.path();
            if p.is_file() {
                if let Ok(rel) = p.strip_prefix(root) {
                    let key = rel.to_string_lossy().replace('/', "\\").to_lowercase();
                    rel_map.entry(key).or_insert_with(|| p.to_path_buf());
                    if let Some(file_name) = p.file_name() {
                        let base_key = file_name.to_string_lossy().to_lowercase();
                        basename_map.entry(base_key).or_insert_with(|| p.to_path_buf());
                    }
                    indexed_count += 1;
                }
            }
        }
    }

    let total_indexed = rel_map.len();
    let roots_count = active_roots_list.len();
    if let Ok(mut guard) = ACTIVE_ROOTS.write() {
        *guard = active_roots_list;
    }
    if let Ok(mut guard) = VFS_MAP.write() {
        *guard = Some(VfsTable {
            rel_map,
            basename_map,
        });
    }
    crate::log_msg(&format!(
        "[LIVECPK] Indicizzazione VFS completata: {} asset da {} root esplicite ({} inserimenti).",
        total_indexed,
        roots_count,
        indexed_count
    ));
}

pub fn get_vfs_diagnostics() -> String {
    let mut out = String::new();
    let roots_count = if let Ok(guard) = ACTIVE_ROOTS.read() {
        guard.len()
    } else {
        0
    };

    if let Ok(guard) = VFS_MAP.read() {
        if let Some(ref vfs) = *guard {
            out.push_str(&format!(
                "LiveCPK VFS Diagnostics:\n• Total Indexed Files: {}\n• Active Roots: {}\n",
                vfs.rel_map.len(),
                roots_count
            ));
            out.push_str("• Sample Indexed Paths (First 5):\n");
            for (idx, (k, v)) in vfs.rel_map.iter().take(5).enumerate() {
                out.push_str(&format!("  [{}] '{}' -> '{}'\n", idx + 1, k, v.display()));
            }
        } else {
            out.push_str("LiveCPK VFS is not initialized.\n");
        }
    } else {
        out.push_str("Could not acquire VFS lock.\n");
    }
    out
}

fn resolve_custom_path(requested_path: &str) -> Option<PathBuf> {
    let norm = requested_path.replace('/', "\\").to_lowercase();
    if let Ok(guard) = VFS_MAP.read() {
        if let Some(ref vfs) = *guard {
            if let Some(custom_path) = vfs.rel_map.get(&norm) {
                return Some(custom_path.clone());
            }

            let mut search_slice = norm.as_str();
            while let Some(idx) = search_slice.find('\\') {
                search_slice = &search_slice[idx + 1..];
                if let Some(custom_path) = vfs.rel_map.get(search_slice) {
                    return Some(custom_path.clone());
                }
            }

            if let Some(file_name) = norm.rsplit('\\').next() {
                if !file_name.is_empty() {
                    if let Some(custom_path) = vfs.basename_map.get(file_name) {
                        let count = BASENAME_LOG_COUNT.fetch_add(1, Ordering::Relaxed);
                        if count < MAX_LOGGED_OVERRIDES {
                            crate::log_msg(&format!(
                                "[LIVECPK BASENAME #{}] Match di fallback per basename: '{}' -> '{}'",
                                count + 1,
                                requested_path,
                                custom_path.display()
                            ));
                        }
                        return Some(custom_path.clone());
                    }
                }
            }
        }
    }
    None
}

unsafe extern "system" fn detour_create_file_w(
    lp_file_name: *const u16,
    dw_desired_access: u32,
    dw_share_mode: u32,
    lp_security_attributes: *const SECURITY_ATTRIBUTES,
    dw_creation_disposition: u32,
    dw_flags_and_attributes: u32,
    h_template_file: HANDLE,
) -> HANDLE {
    if lp_file_name.is_null() {
        if let Some(hook) = HOOK_CREATE_FILE_W.get() {
            return hook.call(
                lp_file_name,
                dw_desired_access,
                dw_share_mode,
                lp_security_attributes,
                dw_creation_disposition,
                dw_flags_and_attributes,
                h_template_file,
            );
        }
        return INVALID_HANDLE_VALUE;
    }

    let mut len = 0;
    while *lp_file_name.add(len) != 0 {
        len += 1;
    }
    let slice = std::slice::from_raw_parts(lp_file_name, len);
    let original_path = String::from_utf16_lossy(slice);

    if let Some(custom_path) = resolve_custom_path(&original_path) {
        let custom_str = custom_path.to_string_lossy().to_string();
        let mut custom_wide: Vec<u16> = custom_str.encode_utf16().collect();
        custom_wide.push(0);

        let count = OVERRIDE_LOG_COUNT.fetch_add(1, Ordering::Relaxed);
        if count < MAX_LOGGED_OVERRIDES {
            crate::log_msg(&format!(
                "[LIVECPK OVERRIDE #{}] '{}' -> '{}'",
                count + 1,
                original_path,
                custom_str
            ));
        } else if count == MAX_LOGGED_OVERRIDES {
            crate::log_msg("[LIVECPK] Limite di 20 log di override raggiunto; ulteriori log silenziati.");
        }

        if let Some(hook) = HOOK_CREATE_FILE_W.get() {
            return hook.call(
                custom_wide.as_ptr(),
                dw_desired_access,
                dw_share_mode,
                lp_security_attributes,
                dw_creation_disposition,
                dw_flags_and_attributes,
                h_template_file,
            );
        }
    }

    if let Some(hook) = HOOK_CREATE_FILE_W.get() {
        hook.call(
            lp_file_name,
            dw_desired_access,
            dw_share_mode,
            lp_security_attributes,
            dw_creation_disposition,
            dw_flags_and_attributes,
            h_template_file,
        )
    } else {
        INVALID_HANDLE_VALUE
    }
}

pub fn install_create_file_hook() -> bool {
    unsafe {
        let h_kernel32 = GetModuleHandleA(b"kernel32.dll\0".as_ptr());
        if h_kernel32 == 0 {
            crate::log_msg("[LIVECPK] ERRORE: Impossibile ottenere l'handle di kernel32.dll");
            return false;
        }

        let proc = GetProcAddress(h_kernel32, b"CreateFileW\0".as_ptr());
        if proc.is_none() {
            crate::log_msg("[LIVECPK] ERRORE: Impossibile trovare la funzione CreateFileW in kernel32.dll");
            return false;
        }

        let target_fn: FnCreateFileW = std::mem::transmute(proc);
        match GenericDetour::new(target_fn, detour_create_file_w) {
            Ok(detour) => {
                if detour.enable().is_ok() {
                    let _ = HOOK_CREATE_FILE_W.set(detour);
                    crate::log_msg("[LIVECPK] Hook detour CreateFileW abilitato con successo");
                    return true;
                } else {
                    crate::log_msg("[LIVECPK] ERRORE: Abilitazione del detour CreateFileW fallita");
                }
            }
            Err(e) => {
                crate::log_msg(&format!("[LIVECPK] ERRORE: Inizializzazione GenericDetour fallita: {:?}", e));
            }
        }
        false
    }
}

pub fn init_livecpk(roots: Vec<PathBuf>) {
    init_livecpk_vfs(roots);
    install_create_file_hook();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lookup_live_asset_normalization() {
        let mut rel_map = HashMap::new();
        let mut basename_map = HashMap::new();
        rel_map.insert(
            "character\\face\\diffuse.uasset".to_string(),
            PathBuf::from("content\\RealFaces\\character\\face\\diffuse.uasset"),
        );
        basename_map.insert(
            "diffuse.uasset".to_string(),
            PathBuf::from("content\\RealFaces\\character\\face\\diffuse.uasset"),
        );
        if let Ok(mut guard) = VFS_MAP.write() {
            *guard = Some(VfsTable {
                rel_map,
                basename_map,
            });
        }
        let res = resolve_custom_path("C:\\eFootball\\Content\\Character/Face\\Diffuse.uasset");
        assert!(res.is_some());
        assert_eq!(
            res.unwrap(),
            PathBuf::from("content\\RealFaces\\character\\face\\diffuse.uasset")
        );
    }

    #[test]
    fn test_lookup_live_asset_basename_fallback() {
        let mut rel_map = HashMap::new();
        let mut basename_map = HashMap::new();
        rel_map.insert(
            "common\\etc\\pesdb\\team.bin".to_string(),
            PathBuf::from("content\\RealDatabase\\team.bin"),
        );
        basename_map.insert(
            "team.bin".to_string(),
            PathBuf::from("content\\RealDatabase\\team.bin"),
        );
        if let Ok(mut guard) = VFS_MAP.write() {
            *guard = Some(VfsTable {
                rel_map,
                basename_map,
            });
        }
        let res = resolve_custom_path("A:\\Games\\eFootball\\Paks\\SubDir\\Team.bin");
        assert!(res.is_some());
        assert_eq!(
            res.unwrap(),
            PathBuf::from("content\\RealDatabase\\team.bin")
        );
    }

    #[test]
    fn test_vfs_diagnostics() {
        let mut rel_map = HashMap::new();
        let basename_map = HashMap::new();
        rel_map.insert("test\\asset.uasset".to_string(), PathBuf::from("content\\test\\asset.uasset"));
        if let Ok(mut guard) = VFS_MAP.write() {
            *guard = Some(VfsTable {
                rel_map,
                basename_map,
            });
        }
        let diag = get_vfs_diagnostics();
        assert!(diag.contains("LiveCPK VFS Diagnostics:"));
        assert!(diag.contains("Total Indexed Files: 1"));
    }
}
