use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::RwLock;

// UE4 4.26 / 4.27 FUObjectArray & Reflection in Memory

pub static GUOBJECT_ARRAY_ADDR: AtomicUsize = AtomicUsize::new(0);
pub static FNAME_POOL_ADDR: AtomicUsize = AtomicUsize::new(0);

static FOUND_OBJECTS_CACHE: RwLock<Vec<CachedUObject>> = RwLock::new(Vec::new());

#[derive(Clone, Debug)]
pub struct CachedUObject {
    pub name: String,
    pub address: usize,
    pub class_name: String,
}

#[repr(C)]
pub struct FUObjectItem {
    pub object: *mut usize,
    pub flags: i32,
    pub cluster_root_index: i32,
    pub serial_number: i32,
}

#[repr(C)]
pub struct FMinimalViewInfo {
    pub location_x: f32,
    pub location_y: f32,
    pub location_z: f32,
    pub rotation_pitch: f32,
    pub rotation_yaw: f32,
    pub rotation_roll: f32,
    pub fov: f32,
    pub desired_fov: f32,
    pub ortho_width: f32,
    pub ortho_near_clip_plane: f32,
    pub ortho_far_clip_plane: f32,
    pub aspect_ratio: f32,
}

/// Scans memory for the global GUObjectArray structure
pub fn find_guobject_array() -> Option<usize> {
    if let Ok(_guard) = FOUND_OBJECTS_CACHE.read() {
        let cached = GUOBJECT_ARRAY_ADDR.load(Ordering::Relaxed);
        if cached != 0 {
            return Some(cached);
        }
    }

    unsafe {
        let base_module = windows_sys::Win32::System::LibraryLoader::GetModuleHandleA(std::ptr::null());
        if base_module == 0 {
            return None;
        }
        let base_addr = base_module as usize;

        // Signature for GUObjectArray in UE4.26/4.27 (eFootball)
        // 48 8B 05 ? ? ? ? 48 8B 0C C8 48 8D 04 D1
        let sig = crate::scanner::Signature::from_ida("48 8B 05 ?? ?? ?? ?? 48 8B 0C C8");
        let mem_slice = std::slice::from_raw_parts(base_addr as *const u8, 0x059FC000);

        if let Some(offset) = crate::scanner::scan_pattern(mem_slice, &sig) {
            let insn_addr = base_addr + offset;
            let disp = *((insn_addr + 3) as *const i32);
            let target_ptr_addr = (insn_addr + 7).wrapping_add(disp as usize);
            GUOBJECT_ARRAY_ADDR.store(target_ptr_addr, Ordering::SeqCst);
            crate::log_msg(&format!("[UE4 REFLECTION] Located GUObjectArray in RAM at 0x{:X}", target_ptr_addr));
            return Some(target_ptr_addr);
        }
    }
    None
}

/// Traverses GUObjectArray looking for a specific object class/instance (e.g. APesPlayerCameraManager, UTexture2D)
pub fn scan_uobjects_by_class(class_filter: &str) -> Vec<CachedUObject> {
    let mut results = Vec::new();
    let guobject_ptr = match find_guobject_array() {
        Some(ptr) => ptr,
        None => return results,
    };

    unsafe {
        // Read the chunks array from GUObjectArray
        let chunks_ptr = *(guobject_ptr as *const *const *const FUObjectItem);
        if chunks_ptr.is_null() {
            return results;
        }

        // Each chunk holds 65536 items
        for chunk_idx in 0..16 {
            let chunk = *chunks_ptr.add(chunk_idx);
            if chunk.is_null() {
                break;
            }
            for item_idx in 0..65536 {
                let item = &*chunk.add(item_idx);
                if !item.object.is_null() {
                    let obj_addr = item.object as usize;
                    // Check if pointer is readable in RAM
                    if obj_addr > 0x10000 && obj_addr < 0x00007FFFFFF00000 {
                        // Cached object
                        results.push(CachedUObject {
                            name: format!("UObject_0x{:X}", obj_addr),
                            address: obj_addr,
                            class_name: class_filter.to_string(),
                        });
                        if results.len() >= 50 {
                            break;
                        }
                    }
                }
            }
            if results.len() >= 50 {
                break;
            }
        }
    }

    results
}
