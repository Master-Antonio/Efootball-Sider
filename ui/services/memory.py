from __future__ import annotations

import ctypes
import os
import re
import threading
from ctypes import wintypes
from dataclasses import dataclass

import psutil

PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_GUARD = 0x100
READABLE_PAGES = PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE
MAX_ADDRESS = 0x00007FFFFFFFFFF0

ASSET_PATTERN = re.compile(
    rb"(?:/(?:Game|Engine|PesConsole|Asset|Wwise)/[A-Za-z0-9_/\-.]+|"
    rb"common/[A-Za-z0-9_/\-.]+|"
    rb"[A-Za-z0-9_\-.]{3,}\.(?:uasset|ubulk|uexp|bin|dds|png|cpk|pak|utoc|ucas|locres|wem|bnk)|"
    rb"(?:st[0-9]{3}|u[0-9]{4})[A-Za-z0-9_\-.]*)",
    re.IGNORECASE,
)


class MemoryBasicInformation64(ctypes.Structure):
    _fields_ = (
        ("BaseAddress", ctypes.c_ulonglong),
        ("AllocationBase", ctypes.c_ulonglong),
        ("AllocationProtect", wintypes.DWORD),
        ("Alignment1", wintypes.DWORD),
        ("RegionSize", ctypes.c_ulonglong),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("Alignment2", wintypes.DWORD),
    )


@dataclass(frozen=True)
class AssetHit:
    address: int
    category: str
    path: str
    region_size: int


def classify_asset(path: str) -> str:
    value = path.lower()
    if value.endswith((".dds", ".png")) or "texture" in value:
        return "Texture"
    if value.endswith((".ubulk", ".uexp")) or "mesh" in value:
        return "Mesh / payload"
    if value.endswith(".bin") or "pesdb" in value:
        return "Database"
    if value.endswith((".utoc", ".ucas", ".pak", ".cpk")):
        return "Container"
    if value.endswith((".wem", ".bnk")) or "audio" in value:
        return "Audio"
    if "stadium" in value or "pitch" in value or value.startswith("st"):
        return "Stadium"
    if "kit" in value or value.startswith("u0"):
        return "Kit"
    return "Asset"


class MemoryDiscoveryService:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.pid: int | None = None
        self.handle: int | None = None
        self.cursor = 0x10000
        self._kernel32 = None
        if os.name == "nt":
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
            kernel32.OpenProcess.restype = wintypes.HANDLE
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL
            kernel32.VirtualQueryEx.argtypes = (
                wintypes.HANDLE,
                ctypes.c_void_p,
                ctypes.POINTER(MemoryBasicInformation64),
                ctypes.c_size_t,
            )
            kernel32.VirtualQueryEx.restype = ctypes.c_size_t
            kernel32.ReadProcessMemory.argtypes = (
                wintypes.HANDLE,
                ctypes.c_void_p,
                ctypes.c_void_p,
                ctypes.c_size_t,
                ctypes.POINTER(ctypes.c_size_t),
            )
            kernel32.ReadProcessMemory.restype = wintypes.BOOL
            self._kernel32 = kernel32

    def attach(self) -> int:
        if self._kernel32 is None:
            raise OSError("Memory discovery is available on Windows only")
        process = next(
            (
                process
                for process in psutil.process_iter(("pid", "name"))
                if process.info["name"] and process.info["name"].lower() == "efootball.exe"
            ),
            None,
        )
        if process is None:
            raise RuntimeError("eFootball is not running")
        handle = self._kernel32.OpenProcess(PROCESS_QUERY_INFORMATION | PROCESS_VM_READ, False, process.pid)
        if not handle:
            raise PermissionError(f"Could not open eFootball process {process.pid}")
        with self._lock:
            if self.handle and self._kernel32 is not None:
                try:
                    self._kernel32.CloseHandle(self.handle)
                except Exception:
                    pass
            self.pid = process.pid
            self.handle = handle
            self.cursor = 0x10000
        return process.pid

    def detach(self) -> None:
        with self._lock:
            if self.handle and self._kernel32 is not None:
                try:
                    self._kernel32.CloseHandle(self.handle)
                except Exception:
                    pass
            self.pid = None
            self.handle = None
            self.cursor = 0x10000

    def attached(self) -> bool:
        with self._lock:
            return bool(self.handle and self.pid and psutil.pid_exists(self.pid))

    def scan(self, budget_mb: int = 48, max_results: int = 100) -> list[AssetHit]:
        with self._lock:
            if not self.attached() or self._kernel32 is None or self.handle is None:
                raise RuntimeError("Attach to eFootball before scanning memory")
            handle = self.handle
            address = self.cursor

        budget = budget_mb * 1024 * 1024
        scanned = 0
        results = []
        information = MemoryBasicInformation64()

        while address < MAX_ADDRESS and scanned < budget and len(results) < max_results:
            try:
                queried = self._kernel32.VirtualQueryEx(
                    handle,
                    ctypes.c_void_p(address),
                    ctypes.byref(information),
                    ctypes.sizeof(information),
                )
            except Exception:
                break
            if not queried:
                address = 0x10000
                break
            region_size = int(information.RegionSize)
            next_address = int(information.BaseAddress) + region_size
            readable = (
                information.State == MEM_COMMIT
                and not information.Protect & (PAGE_GUARD | PAGE_NOACCESS)
                and bool(information.Protect & READABLE_PAGES)
                and 4096 <= region_size <= 8 * 1024 * 1024
            )
            if readable:
                buffer = ctypes.create_string_buffer(region_size)
                bytes_read = ctypes.c_size_t()
                read_ok = False
                try:
                    read_ok = bool(
                        self._kernel32.ReadProcessMemory(
                            handle,
                            ctypes.c_void_p(information.BaseAddress),
                            buffer,
                            region_size,
                            ctypes.byref(bytes_read),
                        )
                    )
                except Exception:
                    read_ok = False
                if read_ok:
                    raw = buffer.raw[: bytes_read.value]
                    scanned += bytes_read.value
                    for match in ASSET_PATTERN.finditer(raw):
                        path = match.group(0).decode("latin-1", errors="ignore").strip()
                        if path:
                            results.append(
                                AssetHit(
                                    address=int(information.BaseAddress) + match.start(),
                                    category=classify_asset(path),
                                    path=path,
                                    region_size=region_size,
                                )
                            )
                        if len(results) >= max_results:
                            break
            if next_address <= address:
                address = 0x10000
                break
            address = next_address

        with self._lock:
            if self.handle == handle:
                self.cursor = address if address < MAX_ADDRESS else 0x10000
        return results

    def close(self) -> None:
        self.detach()
