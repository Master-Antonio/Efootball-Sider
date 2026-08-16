"""
==============================================================================
eFootball Live Sider (Memory Interceptor & Live RAM Patcher)
==============================================================================
Reads rules directly from teams.ini.
Scans eFootball.exe committed RAM and live-patches exact user-defined strings.
"""
import sys
import os
import time
import ctypes
from ctypes import wintypes
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100
class MEMORY_BASIC_INFORMATION64(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("Alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("Alignment2", wintypes.DWORD),
    ]
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(MEMORY_BASIC_INFORMATION64), ctypes.c_size_t]
VirtualQueryEx.restype = ctypes.c_size_t
ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL
WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
WriteProcessMemory.restype = wintypes.BOOL
VirtualProtectEx = kernel32.VirtualProtectEx
VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
VirtualProtectEx.restype = wintypes.BOOL
OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE
CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL
def load_ini_rules(ini_path):
    table = []
    if not os.path.exists(ini_path):
        return table
    with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(";") or line.startswith("#") or line.startswith("["):
                continue
            if "=" in line:
                f_str, t_str = line.split("=", 1)
                f_str = f_str.strip()
                t_str = t_str.strip()
                if not f_str or not t_str:
                    continue
                flen = len(f_str)
                t_pad = t_str
                if len(t_pad) < flen:
                    t_pad = t_pad + " " * (flen - len(t_pad))
                elif len(t_pad) > flen:
                    t_pad = t_pad[:flen]
                f_ascii = f_str.encode("latin-1")
                t_ascii = t_pad.encode("latin-1")
                table.append((f_ascii, t_ascii, f"'{f_str}' -> '{t_str}' [ASCII]"))
                f_u16 = f_str.encode("utf-16le")
                t_u16 = t_pad.encode("utf-16le")
                table.append((f_u16, t_u16, f"'{f_str}' -> '{t_str}' [UTF-16]"))
    return table
def find_efootball_pids():
    import subprocess
    try:
        output = subprocess.check_output('tasklist /FI "IMAGENAME eq eFootball.exe" /FO CSV /NH', shell=True).decode()
        pids = []
        for line in output.strip().split("\n"):
            if "eFootball.exe" in line:
                parts = line.replace('"', '').split(",")
                if len(parts) >= 2:
                    pids.append(int(parts[1]))
        return pids
    except Exception:
        return []
def scan_and_patch(h_process, replacements):
    mbi = MEMORY_BASIC_INFORMATION64()
    address = 0x10000
    total_regions = 0
    total_mb = 0
    patched_count = 0
    while True:
        res = VirtualQueryEx(h_process, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if res == 0:
            break
        total_regions += 1
        is_readable = (
            mbi.State == MEM_COMMIT
            and (mbi.Protect & PAGE_GUARD == 0)
            and (mbi.Protect & PAGE_NOACCESS == 0)
            and bool(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))
        )
        if is_readable and 0 < mbi.RegionSize <= 256 * 1024 * 1024:
            region_size = mbi.RegionSize
            total_mb += region_size / (1024 * 1024)
            buffer = ctypes.create_string_buffer(region_size)
            bytes_read = ctypes.c_size_t(0)
            if ReadProcessMemory(h_process, ctypes.c_void_p(mbi.BaseAddress), buffer, region_size, ctypes.byref(bytes_read)):
                raw_bytes = buffer.raw[:bytes_read.value]
                for from_b, to_b, desc in replacements:
                    flen = len(from_b)
                    start = 0
                    while True:
                        idx = raw_bytes.find(from_b, start)
                        if idx == -1:
                            break
                        target_addr = mbi.BaseAddress + idx
                        old_protect = wintypes.DWORD(0)
                        if VirtualProtectEx(h_process, ctypes.c_void_p(target_addr), flen, PAGE_EXECUTE_READWRITE, ctypes.byref(old_protect)):
                            bytes_written = ctypes.c_size_t(0)
                            patch_buf = ctypes.create_string_buffer(to_b, flen)
                            if WriteProcessMemory(h_process, ctypes.c_void_p(target_addr), patch_buf, flen, ctypes.byref(bytes_written)):
                                patched_count += 1
                                print(f"  [+] Patched {desc} at memory 0x{target_addr:X}")
                            VirtualProtectEx(h_process, ctypes.c_void_p(target_addr), flen, old_protect.value, ctypes.byref(old_protect))
                        start = idx + flen
        next_addr = mbi.BaseAddress + mbi.RegionSize
        if next_addr <= address or next_addr >= 0x00007FFFFFFFFFF0:
            break
        address = next_addr
    return total_regions, total_mb, patched_count
def main():
    print("=" * 75)
    print("  eFootball Modder Live Sider (Dynamic teams.ini RAM Engine)")
    print("=" * 75)
    ini_paths = [
        "teams.ini",
        r"A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64\teams.ini",
        r"A:\Mod Efootball\GEMINI\SIDER\teams.ini"
    ]
    rules = []
    active_ini = None
    for p in ini_paths:
        if os.path.exists(p):
            rules = load_ini_rules(p)
            if rules:
                active_ini = p
                break
    if not rules:
        print("[-] ERROR: No teams.ini found! Please make sure teams.ini exists.")
        return
    print(f"[+] Loaded {len(rules)//2} custom modder rules from: {active_ini}")
    print("\n[*] Looking for active eFootball.exe process...")
    while True:
        pids = find_efootball_pids()
        if not pids:
            time.sleep(1.5)
            continue
        pid = pids[0]
        print(f"[+] Hooked eFootball.exe (PID: {pid})")
        h_process = OpenProcess(PROCESS_ALL_ACCESS, False, pid)
        if not h_process:
            print(f"[-] Could not open PID {pid}. (Make sure to run with Admin privileges).")
            time.sleep(2)
            continue
        print("[*] Live memory interception running...")
        pass_num = 0
        try:
            while True:
                pass_num += 1
                regions, mb_scanned, patched = scan_and_patch(h_process, rules)
                print(f"[Scan #{pass_num:03d}] {regions} memory blocks ({mb_scanned:.1f} MB RAM) -> {patched} string matches patched")
                time.sleep(1.0)
        except KeyboardInterrupt:
            print("\n[*] Sider stopped by modder.")
            CloseHandle(h_process)
            break
        except Exception as e:
            print(f"[-] Loop notice: {e}")
            time.sleep(2)
if __name__ == "__main__":
    main()
