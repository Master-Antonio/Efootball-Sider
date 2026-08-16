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

static HOOK_CREATE_FILE_W: OnceLock<GenericDetour<FnCreateFileW>> = OnceLock::new();
static VFS_MAP: RwLock<Option<HashMap<String, PathBuf>>> = RwLock::new(None);
static ACTIVE_ROOTS: RwLock<Vec<PathBuf>> = RwLock::new(Vec::new());
static OVERRIDE_LOG_COUNT: AtomicUsize = AtomicUsize::new(0);
static BASENAME_LOG_COUNT: AtomicUsize = AtomicUsize::new(0);
const MAX_LOGGED_OVERRIDES: usize = 20;

/// Popola la tabella di lookup O(1) del Virtual File System (VFS) indicizzando prima le mod registrate e poi content/ come fallback a bassa priorita
pub fn init_livecpk_vfs(mod_roots: Vec<PathBuf>) {
    let mut map = HashMap::new();
    let mut active_roots_list = Vec::new();
    let mut mod_indexed_count = 0;

    // 1. Indicizza le root delle mod registrate ad alta priorita
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
                    map.insert(key, p.to_path_buf());
                    mod_indexed_count += 1;
                }
            }
        }
    }

    // 2. Trova e indicizza la cartella content/ come fallback a bassa priorita
    let fallback_candidates = [
        PathBuf::from("content"),
        PathBuf::from("../content"),
        PathBuf::from("../../content"),
    ];

    let mut fallback_indexed_count = 0;
    for cand in fallback_candidates {
        if cand.exists() && cand.is_dir() {
            if !active_roots_list.contains(&cand) {
                active_roots_list.push(cand.clone());
            }
            for entry in WalkDir::new(&cand).into_iter().filter_map(|e| e.ok()) {
                let p = entry.path();
                if p.is_file() {
                    if let Ok(rel) = p.strip_prefix(&cand) {
                        let key = rel.to_string_lossy().replace('/', "\\").to_lowercase();
                        // Bassa priorita: inserisce solo se non gia presente tra le mod registrate
                        if !map.contains_key(&key) {
                            map.insert(key, p.to_path_buf());
                            fallback_indexed_count += 1;
                        }
                    }
                }
            }
            break;
        }
    }

    let total_indexed = map.len();
    if let Ok(mut guard) = ACTIVE_ROOTS.write() {
        *guard = active_roots_list;
    }
    if let Ok(mut guard) = VFS_MAP.write() {
        *guard = Some(map);
    }
    crate::log_msg(&format!(
        "[LIVECPK] Indicizzazione VFS completata: {} asset totali ({} da mod registrate, {} da fallback content/).",
        total_indexed, mod_indexed_count, fallback_indexed_count
    ));
}

/// Restituisce la diagnostica testuale del VFS per il log e la GUI
pub fn get_vfs_diagnostics() -> String {
    let mut out = String::new();
    let roots_count = if let Ok(guard) = ACTIVE_ROOTS.read() {
        guard.len()
    } else {
        0
    };

    if let Ok(guard) = VFS_MAP.read() {
        if let Some(ref map) = *guard {
            out.push_str(&format!(
                "LiveCPK VFS Diagnostics:\n• Total Indexed Files: {}\n• Active Roots: {}\n",
                map.len(),
                roots_count
            ));
            out.push_str("• Sample Indexed Paths (First 5):\n");
            for (idx, (k, v)) in map.iter().take(5).enumerate() {
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

/// Risolve il percorso con lookup O(1) nel Virtual File System
fn resolve_custom_path(requested_path: &str) -> Option<PathBuf> {
    let norm = requested_path.replace('/', "\\").to_lowercase();
    if let Ok(guard) = VFS_MAP.read() {
        if let Some(ref map) = *guard {
            // 1. Lookup diretto O(1)
            if let Some(custom_path) = map.get(&norm) {
                return Some(custom_path.clone());
            }

            // 2. Lookup O(1) sui suffissi di percorso per percorsi completi/assoluti
            let mut search_slice = norm.as_str();
            while let Some(idx) = search_slice.find('\\') {
                search_slice = &search_slice[idx + 1..];
                if let Some(custom_path) = map.get(search_slice) {
                    return Some(custom_path.clone());
                }
            }

            // 3. Fallback di 3° livello: match per nome file (basename)
            if let Some(file_name) = norm.rsplit('\\').next() {
                if !file_name.is_empty() {
                    for (rel_key, full_path) in map.iter() {
                        if let Some(mod_filename) = rel_key.rsplit('\\').next() {
                            if mod_filename.eq_ignore_ascii_case(file_name) {
                                let count = BASENAME_LOG_COUNT.fetch_add(1, Ordering::Relaxed);
                                if count < MAX_LOGGED_OVERRIDES {
                                    crate::log_msg(&format!(
                                        "[LIVECPK BASENAME #{}] Match di fallback per basename: '{}' -> '{}'",
                                        count + 1,
                                        requested_path,
                                        full_path.display()
                                    ));
                                }
                                return Some(full_path.clone());
                            }
                        }
                    }
                }
            }
        }
    }
    None
}

/// Handler Detour per CreateFileW
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

    // Converti puntatore UTF-16 in String Rust
    let mut len = 0;
    while *lp_file_name.add(len) != 0 {
        len += 1;
    }
    let slice = std::slice::from_raw_parts(lp_file_name, len);
    let original_path = String::from_utf16_lossy(slice);

    // Verifica se esiste un override nel VFS
    if let Some(custom_path) = resolve_custom_path(&original_path) {
        let custom_str = custom_path.to_string_lossy().to_string();
        let mut custom_wide: Vec<u16> = custom_str.encode_utf16().collect();
        custom_wide.push(0); // Null-terminator

        // Limita il logging ai primi 20 override per evitare spam su disco
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

        // Reindirizza la chiamata di sistema al file personalizzato della mod
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

    // Forward originale se non è presente alcun override
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

/// Installa l'hook detour su kernel32.dll!CreateFileW usando retour
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

/// Inizializza l'intero sottosistema LiveCPK (VFS + Hook CreateFileW)
pub fn init_livecpk(roots: Vec<PathBuf>) {
    init_livecpk_vfs(roots);
    install_create_file_hook();
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_lookup_live_asset_normalization() {
        let mut map = HashMap::new();
        map.insert(
            "character\\face\\diffuse.uasset".to_string(),
            PathBuf::from("content\\RealFaces\\character\\face\\diffuse.uasset"),
        );
        if let Ok(mut guard) = VFS_MAP.write() {
            *guard = Some(map);
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
        let mut map = HashMap::new();
        map.insert(
            "common\\etc\\pesdb\\team.bin".to_string(),
            PathBuf::from("content\\RealDatabase\\team.bin"),
        );
        if let Ok(mut guard) = VFS_MAP.write() {
            *guard = Some(map);
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
        let mut map = HashMap::new();
        map.insert("test\\asset.uasset".to_string(), PathBuf::from("content\\test\\asset.uasset"));
        if let Ok(mut guard) = VFS_MAP.write() {
            *guard = Some(map);
        }
        let diag = get_vfs_diagnostics();
        assert!(diag.contains("LiveCPK VFS Diagnostics:"));
        assert!(diag.contains("Total Indexed Files: 1"));
    }
}
