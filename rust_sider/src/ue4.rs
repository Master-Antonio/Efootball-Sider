use std::sync::atomic::{AtomicUsize, Ordering};
use std::sync::RwLock;
use windows_sys::Win32::System::Memory::{
    VirtualQuery, MEMORY_BASIC_INFORMATION, MEM_COMMIT, PAGE_EXECUTE, PAGE_EXECUTE_READ,
    PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY, PAGE_GUARD, PAGE_NOACCESS, PAGE_READONLY,
    PAGE_READWRITE, PAGE_WRITECOPY,
};

// UE4 4.26 / 4.27 FUObjectArray locator.
//
// NOTE: full reflection (UObject names/classes via GNames/FName pool) is NOT
// implemented. This module only locates a validated GUObjectArray candidate;
// anything beyond that requires real name-pool resolution work.

pub static GUOBJECT_ARRAY_ADDR: AtomicUsize = AtomicUsize::new(0);
pub static FNAME_POOL_ADDR: AtomicUsize = AtomicUsize::new(0);

static FOUND_OBJECTS_CACHE: RwLock<()> = RwLock::new(());

/// Returns true when `addr` points at committed, readable data memory.
/// GUObjectArray must live in writable data, so a candidate resolving into an
/// executable code section is a signature false positive and is rejected.
fn is_plausible_data_pointer(addr: usize) -> bool {
    if addr < 0x10000 {
        return false;
    }
    let mut mbi: MEMORY_BASIC_INFORMATION = unsafe { std::mem::zeroed() };
    let res = unsafe {
        VirtualQuery(
            addr as *const _,
            &mut mbi,
            std::mem::size_of::<MEMORY_BASIC_INFORMATION>(),
        )
    };
    if res == 0 || mbi.State != MEM_COMMIT {
        return false;
    }
    if mbi.Protect & (PAGE_GUARD | PAGE_NOACCESS) != 0 {
        return false;
    }
    // Reject executable regions (code sections): the object array is data.
    if mbi.Protect
        & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)
        != 0
    {
        return false;
    }
    mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY) != 0
}

/// Scans memory for the global GUObjectArray structure
pub fn find_guobject_array() -> Option<usize> {
    let _guard = FOUND_OBJECTS_CACHE.read().ok()?;
    let cached = GUOBJECT_ARRAY_ADDR.load(Ordering::Relaxed);
    if cached != 0 {
        return Some(cached);
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

            if !is_plausible_data_pointer(target_ptr_addr) {
                crate::log_msg(&format!(
                    "[UE4 REFLECTION] GUObjectArray candidate at 0x{:X} is not committed data; ignoring false positive.",
                    target_ptr_addr
                ));
                return None;
            }

            GUOBJECT_ARRAY_ADDR.store(target_ptr_addr, Ordering::SeqCst);
            crate::log_msg(&format!("[UE4 REFLECTION] Located GUObjectArray in RAM at 0x{:X}", target_ptr_addr));
            return Some(target_ptr_addr);
        }
    }
    None
}
