"""
========================================================================================
Efootball Sider by Toriga (v8.0 Ultimate Visual Asset Sniffer & Hex Studio)
========================================================================================
- Tab 1: 🛰️ Live Asset Sniffer con Ricerca / Filtro Istantaneo in tempo reale
- Tab 2: 🔬 Visual Asset Inspector, Decoded Content & Hex Studio (con anteprima stringhe, header e pixel)
- Tab 3: 🔍 Ricerca Mirata & Smart Injector (con pulizia totale dei residui)
- Tab 4: 📦 Mod Manager & Generatore Automatico di Mod
========================================================================================
"""
import os
import sys
import time
import re
import random
import zipfile
import shutil
import threading
import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import io
import csv
import struct
import zlib
import logging
import configparser
from PIL import Image, ImageTk
logging.basicConfig(
    filename="sider_gui.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
    encoding="utf-8"
)
logger = logging.getLogger("SiderGUI")
class XorShift128:
    def __init__(self, seed=(0x12345678, 0x9ABCDEF0, 0x13579BDF, 0x2468ACE0), shifts=(11, 8, 19)):
        self.x = seed[0] & 0xFFFFFFFF
        self.y = seed[1] & 0xFFFFFFFF
        self.z = seed[2] & 0xFFFFFFFF
        self.w = seed[3] & 0xFFFFFFFF
        self.s1, self.s2, self.s3 = shifts

    def next_u32(self) -> int:
        t = (self.x ^ ((self.x << self.s1) & 0xFFFFFFFF)) & 0xFFFFFFFF
        self.x = self.y
        self.y = self.z
        self.z = self.w
        self.w = ((self.w ^ (self.w >> self.s3)) ^ (t ^ (t >> self.s2))) & 0xFFFFFFFF
        return self.w

def get_cipher_constants(flag_byte: int):
    if flag_byte == 0x20:
        return (0x12345678, 0x9ABCDEF0, 0x13579BDF, 0x2468ACE0), (11, 8, 19)
    elif flag_byte == 0x21:
        return (0x87654321, 0x0FEDCBA9, 0xFDB97531, 0x0ECA8642), (11, 8, 19)
    else:
        return (0x6C8E9CF5, 0x3B2F7E41, 0x9D4C1A8B, 0x5E6A7D2C), (11, 8, 19)

def crypt_payload_xorshift(payload: bytes, flag_byte: int = 0x20) -> bytes:
    seed, shifts = get_cipher_constants(flag_byte)
    prng = XorShift128(seed, shifts)
    out = bytearray(payload)
    n_words = len(out) // 4
    for i in range(n_words):
        offset = i * 4
        k = prng.next_u32()
        orig = struct.unpack_from("<I", out, offset)[0]
        enc = orig ^ k
        struct.pack_into("<I", out, offset, enc)
    return bytes(out)

def is_wesys_container(data: bytes) -> bool:
    return len(data) >= 16 and data[3:8] == b"WESYS"

def pack_wesys_container(data: bytes, flag_byte: int = 0x20) -> bytes:
    compressed = zlib.compress(data, level=9)
    encrypted = crypt_payload_xorshift(compressed, flag_byte) if flag_byte >= 0x20 else compressed
    header = struct.pack("<BBB5sII", flag_byte, 0, 0, b"WESYS", len(data), len(encrypted))
    return header + encrypted

def unpack_wesys_payload(data: bytes) -> bytes:
    if not is_wesys_container(data):
        try:
            return zlib.decompress(data)
        except Exception:
            return data
    flag_byte = data[0]
    payload = data[16:]
    decrypted = crypt_payload_xorshift(payload, flag_byte) if flag_byte >= 0x20 else payload
    try:
        return zlib.decompress(decrypted)
    except Exception:
        return decrypted

def native_rust_unpack_wesys(data: bytes) -> bytes:
    if not data:
        return b""
    dll_candidates = [
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "dxgi.dll"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "rust_sider", "target", "release", "dxgi.dll"),
        r"A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64\dxgi.dll"
    ]
    for cand in dll_candidates:
        if os.path.isfile(cand):
            try:
                lib = ctypes.CDLL(cand)
                if hasattr(lib, "wesys_unpack_native"):
                    max_out = max(len(data) * 8, 1024 * 1024 * 16)
                    out_buf = (ctypes.c_uint8 * max_out)()
                    written = ctypes.c_size_t(0)
                    ret = lib.wesys_unpack_native(data, len(data), out_buf, max_out, ctypes.byref(written))
                    if ret == 0 and written.value > 0:
                        return bytes(out_buf[:written.value])
            except Exception:
                pass
    return unpack_wesys_payload(data)
def parse_player_assignment_bin(data: bytes):
    records = []
    stride = 24
    count = len(data) // stride
    for i in range(count):
        chunk = data[i * stride : (i + 1) * stride]
        if len(chunk) < stride:
            break
        pid_32 = struct.unpack("<I", chunk[0:4])[0]
        team_id = struct.unpack("<I", chunk[4:8])[0]
        squad_number = chunk[8]
        roster_slot = chunk[9]
        records.append({
            "row": i + 1,
            "index": i,
            "pid_32": pid_32,
            "pid_hex": chunk[0:4].hex(" "),
            "team_id": team_id,
            "squad_number": squad_number,
            "roster_slot": roster_slot,
        })
    return records

def parse_team_bin(data: bytes):
    records = []
    stride = 64
    count = len(data) // stride
    for i in range(count):
        chunk = data[i * stride : (i + 1) * stride]
        if len(chunk) < stride:
            break
        team_id = struct.unpack("<I", chunk[0:4])[0]
        name_bytes = bytearray()
        for b in chunk[4:]:
            if 32 <= b <= 126:
                name_bytes.append(b)
            elif b == 0 and len(name_bytes) > 1:
                break
        team_name = name_bytes.decode("latin-1", errors="ignore").strip()
        if not team_name:
            team_name = f"Team #{team_id}"
        records.append({
            "row": i + 1,
            "index": i,
            "offset": f"0x{i * stride:06X}",
            "team_id": team_id,
            "name": team_name,
            "hex": chunk[:16].hex(" ")
        })
    return records

def parse_team_color_bin(data: bytes):
    records = []
    stride = 64
    count = len(data) // stride
    for i in range(count):
        chunk = data[i * stride : (i + 1) * stride]
        if len(chunk) < stride:
            break
        team_id = struct.unpack("<I", chunk[0:4])[0]
        r1, g1, b1 = chunk[4], chunk[5], chunk[6]
        r2, g2, b2 = chunk[8], chunk[9], chunk[10]
        hex_color1 = f"#{r1:02X}{g1:02X}{b1:02X}"
        hex_color2 = f"#{r2:02X}{g2:02X}{b2:02X}"
        records.append({
            "row": i + 1,
            "index": i,
            "offset": f"0x{i * stride:06X}",
            "team_id": team_id,
            "color_primary": hex_color1,
            "color_secondary": hex_color2,
            "rgb_primary": f"RGB({r1},{g1},{b1})",
            "rgb_secondary": f"RGB({r2},{g2},{b2})",
            "hex": chunk[:16].hex(" ")
        })
    return records

def parse_player_bin(data: bytes):
    records = []
    stride = 400
    count = len(data) // stride
    for i in range(count):
        chunk = data[i * stride : (i + 1) * stride]
        if len(chunk) < stride:
            break
        pid = struct.unpack("<I", chunk[0:4])[0]
        att_style = chunk[20] if len(chunk) > 20 else 0
        nationality = struct.unpack("<H", chunk[8:10])[0] if len(chunk) >= 10 else 0
        height_cm = chunk[16] if len(chunk) > 16 else 0
        weight_kg = chunk[17] if len(chunk) > 17 else 0
        records.append({
            "row": i + 1,
            "index": i,
            "offset": f"0x{i * stride:06X}",
            "player_id": pid,
            "nationality_id": nationality,
            "height_cm": height_cm,
            "weight_kg": weight_kg,
            "attacking_style": att_style,
            "hex": chunk[:16].hex(" ")
        })
    return records

def parse_player_record_400(chunk: bytes):
    if len(chunk) < 400:
        return None
    native_pid = struct.unpack("<I", chunk[0:4])[0]
    att_style = chunk[20] if len(chunk) > 20 else 0
    return {
        "native_pid": native_pid,
        "external_pid_hex": chunk[0:4].hex(" "),
        "attacking_style_id": att_style,
        "defensive_style_name": "Standard"
    }
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_VM_READ = 0x0010
PROCESS_VM_WRITE = 0x0020
PROCESS_VM_OPERATION = 0x0008
PROCESS_STEALTH_ACCESS = PROCESS_QUERY_INFORMATION | PROCESS_VM_READ | PROCESS_VM_WRITE | PROCESS_VM_OPERATION
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
ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(ctypes.c_char), ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL
WriteProcessMemory = kernel32.WriteProcessMemory
WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
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
GetExitCodeProcess = kernel32.GetExitCodeProcess
GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
GetExitCodeProcess.restype = wintypes.BOOL
LANG_DATA = {
    "IT": {
        "title": "Efootball Sider by Toriga (Visual Asset & Hex Studio)",
        "waiting": "● In attesa di eFootball.exe...",
        "connected": "● Connesso: eFootball.exe (PID: {pid}) [Modalità Stealth Attiva]",
        "attach_err": "● Errore Aggancio (PID: {pid})",
        "tab_sniffer": "🛰️ 1. Live Asset Sniffer",
        "tab_hex": "🔬 2. Visual Asset & Hex Inspector",
        "tab_search": "🔍 3. Ricerca & Smart Inject",
        "tab_mods": "📦 4. Mod Manager & Generatore",
        "tab_db_injector": "💉 5. Database & File Injector",
        "tab_camera": "🎬 6. Camera Studio & Broadcast Master",
        "lbl_db_scan_title": "🔍 Database Attivi di Konami Rilevati in RAM:",
        "btn_db_scan": "🔍 SCANSIONA RAM PER DATABASE ATTIVI",
        "lbl_db_file_sel": "📂 File Database Nostro da Iniettare:",
        "btn_db_browse": "📁 Sfoglia File Database...",
        "btn_db_preset_team": "⚽ Nostro Team.bin Ufficiale",
        "btn_db_preset_color": "🎨 Nostro TeamColor.bin",
        "btn_db_preset_folder": "📂 Nostra Cartella pesdb Completa",
        "btn_db_inject_ram": "⚡ INIETTA SUBITO IN RAM (Live Process)",
        "btn_db_save_livecpk": "💾 SALVA NEL SIDER (LiveCPK Permanente)",
        "btn_db_restore": "🔄 Ripristina Database Originale",
        "col_db_addr": "Indirizzo RAM",
        "col_db_size": "Dimensione Blocco",
        "col_db_name": "Database / Struttura Identificata",
        "col_db_status": "Stato Memoria",
        "lbl_db_log_title": "📜 Log Operazioni Iniezione Database:",
        "msg_select_db_block": "Seleziona un blocco di memoria database dalla tabella!",
        "msg_select_db_file": "Seleziona prima un file database valido da iniettare!",
        "msg_db_inject_ok": "Database iniettato con successo in RAM!",
        "msg_db_save_ok": "Database salvato nel Sider in content/Official_TeamName_Toriga/common/etc/pesdb/!",
        "btn_start_sniffer": "▶ AVVIA ASSET SNIFFER",
        "btn_stop_sniffer": "⏹ FERMA SNIFFER",
        "btn_clear_sniffer": "🧹 Pulisci Lista",
        "lbl_filter_sniffer": "🔎 Filtra Asset:",
        "btn_inspect_hex": "🔬 Ispeziona Dettagli & Hex",
        "btn_make_mod": "📦 Crea Mod da Questo Asset",
        "sniffer_info_idle": "Avvia lo Sniffer e muoviti nel gioco per catturare percorsi file, texture e modelli 3D!",
        "sniffer_info_active": "📡 SNIFFER ATTIVO: Intercettazione in tempo reale degli asset caricati...",
        "col_time": "Orario",
        "col_type": "Tipo Asset",
        "col_addr": "Indirizzo RAM",
        "col_path": "Percorso File / Nome Asset Riconosciuto",
        "col_size": "Dimensione",
        "lbl_hex_addr": "Indirizzo Memoria:",
        "btn_read_hex": "🔄 Rileggi RAM",
        "btn_save_hex": "💾 Salva Modifiche Byte in RAM",
        "lbl_visual_title": "📋 Ispezione Contenuto & Decodifica:",
        "lbl_hex_title": "🔬 Visualizzazione Esadecimale (RAM Dump):",
        "tab_strings": "📝 Testo & Stringhe Decodificate",
        "tab_structure": "ℹ️ Struttura & Header Asset",
        "tab_palette": "🖼️ Anteprima Texture",
        "lbl_search_prompt": "Testo o Nome Asset da Cercare:",
        "btn_search": "🔍 CERCA IN RAM",
        "btn_stop_search": "⏹ Ferma",
        "chk_case": "Maiuscole",
        "search_hint": "Cerca squadre, stadi (st85), texture (T_Grass) o qualsiasi parola",
        "col_encoding": "Codifica",
        "lbl_new_val": "✏️ Nuovo Testo:",
        "btn_inj_sel": "⚡ INIETTA SELEZIONATO (1-Clic)",
        "btn_inj_smart": "🚀 INIETTA TUTTI I TESTI UI (Smart)",
        "btn_install_zip": "📥 Installa Mod da File .ZIP",
        "btn_open_folder": "📁 Apri Cartella Mod (content)",
        "btn_del_mod": "🗑️ Elimina Mod Selezionata",
        "btn_reload_mods": "🔄 Ricarica Elenco",
        "col_status": "Stato Mod",
        "col_mod_name": "Nome Mod",
        "col_mod_cat": "Tipo / Categoria",
        "col_author": "Autore & Versione",
        "col_folder": "Cartella Mod",
        "btn_toggle_mod": "⚡ Attiva / Disattiva Mod (Doppio Clic)",
        "btn_apply_mod_live": "⚡ Inietta Squadre della Mod Subito in RAM",
        "btn_sync_game": "🚀 Sincronizza & Installa Sider nel Gioco",
        "msg_select_row": "Seleziona prima una riga dalla tabella!",
        "msg_success": "Operazione completata con successo!",
        "msg_err": "Errore durante l'operazione.",
        "msg_sync_ok": "Tutte le Mod e il Sider sono stati sincronizzati e installati in eFootball!",
        "msg_confirm_del": "Sei sicuro di voler eliminare la mod '{name}'?",
        "msg_game_not_found": "Avvia prima eFootball da Steam!",
        "msg_applied_mod": "Iniettate con successo {count} squadre della mod '{name}' in RAM!",
        "msg_no_teams_mod": "Nessuna regola squadre trovata in questa mod.",
        "mod_active": "🟢 ATTIVA",
        "mod_disabled": "⚪ Disattivata",
        "safe_ui": "🟢 Testo UI Schermo (Sicuro)",
        "internal_key": "⚙️ Chiave Interna Motore",
        "code_sec": "🔴 Codice Eseguibile",
    },
    "EN": {
        "title": "Efootball Sider by Toriga (Visual Asset & Hex Studio)",
        "waiting": "● Waiting for eFootball.exe...",
        "connected": "● Connected: eFootball.exe (PID: {pid}) [Stealth Mode Active]",
        "attach_err": "● Attach Error (PID: {pid})",
        "tab_sniffer": "🛰️ 1. Live Asset Sniffer",
        "tab_hex": "🔬 2. Visual Asset & Hex Inspector",
        "tab_search": "🔍 3. Search & Smart Inject",
        "tab_mods": "📦 4. Mod Manager & Generator",
        "tab_db_injector": "💉 5. Database & File Injector",
        "tab_camera": "🎬 6. Camera Studio & Broadcast Master",
        "lbl_db_scan_title": "🔍 Active Konami Databases Detected in RAM:",
        "btn_db_scan": "🔍 SCAN RAM FOR ACTIVE DATABASES",
        "lbl_db_file_sel": "📂 Custom Database File to Inject:",
        "btn_db_browse": "📁 Browse Database File...",
        "btn_db_preset_team": "⚽ Our Official Team.bin",
        "btn_db_preset_color": "🎨 Our TeamColor.bin",
        "btn_db_preset_folder": "📂 Our Full pesdb Folder",
        "btn_db_inject_ram": "⚡ INJECT DIRECTLY INTO RAM (Live)",
        "btn_db_save_livecpk": "💾 SAVE TO SIDER (Permanent LiveCPK)",
        "btn_db_restore": "🔄 Restore Original Database",
        "col_db_addr": "RAM Address",
        "col_db_size": "Block Size",
        "col_db_name": "Identified Database / Structure",
        "col_db_status": "Memory Status",
        "lbl_db_log_title": "📜 Database Injection Operations Log:",
        "msg_select_db_block": "Please select a database memory block from the table!",
        "msg_select_db_file": "Please select a valid database file to inject!",
        "msg_db_inject_ok": "Database successfully injected into game RAM!",
        "msg_db_save_ok": "Database saved to Sider under content/Official_TeamName_Toriga/common/etc/pesdb/!",
        "btn_start_sniffer": "▶ START ASSET SNIFFER",
        "btn_stop_sniffer": "⏹ STOP SNIFFER",
        "btn_clear_sniffer": "🧹 Clear List",
        "lbl_filter_sniffer": "🔎 Filter Asset:",
        "btn_inspect_hex": "🔬 Inspect Details & Hex",
        "btn_make_mod": "📦 Create Mod from this Asset",
        "sniffer_info_idle": "Start the Sniffer and browse the game to capture file paths, textures & 3D models!",
        "sniffer_info_active": "📡 SNIFFER ACTIVE: Intercepting loaded game assets in real-time...",
        "col_time": "Time",
        "col_type": "Asset Type",
        "col_addr": "RAM Address",
        "col_path": "File Path / Identified Asset Name",
        "col_size": "Size",
        "lbl_hex_addr": "Memory Address:",
        "btn_read_hex": "🔄 Read RAM",
        "btn_save_hex": "💾 Save Byte Edits to RAM",
        "lbl_visual_title": "📋 Content Inspection & Decoding:",
        "lbl_hex_title": "🔬 Hexadecimal View (RAM Dump):",
        "tab_strings": "📝 Decoded Text & Strings",
        "tab_structure": "ℹ️ Asset Structure & Header",
        "tab_palette": "🖼️ Texture Preview",
        "lbl_search_prompt": "Text or Asset Name to Search:",
        "btn_search": "🔍 SEARCH IN RAM",
        "btn_stop_search": "⏹ Stop",
        "chk_case": "Case Sensitive",
        "search_hint": "Search teams, stadiums (st85), textures (T_Grass) or any string",
        "col_encoding": "Encoding",
        "lbl_new_val": "✏️ New Text:",
        "btn_inj_sel": "⚡ INJECT SELECTED (1-Click)",
        "btn_inj_smart": "🚀 INJECT ALL UI TEXTS (Smart)",
        "btn_install_zip": "📥 Install Mod from .ZIP Archive",
        "btn_open_folder": "📁 Open Mod Folder (content)",
        "btn_del_mod": "🗑️ Delete Selected Mod",
        "btn_reload_mods": "🔄 Reload List",
        "col_status": "Mod Status",
        "col_mod_name": "Mod Name",
        "col_mod_cat": "Type / Category",
        "col_author": "Author & Version",
        "col_folder": "Mod Folder",
        "btn_toggle_mod": "⚡ Enable / Disable Mod (Double-Click)",
        "btn_apply_mod_live": "⚡ Inject Mod Teams Live into RAM",
        "btn_sync_game": "🚀 Sync & Install Sider into Game",
        "msg_select_row": "Please select a row from the table first!",
        "msg_success": "Operation completed successfully!",
        "msg_err": "Error during operation.",
        "msg_sync_ok": "All Mods and Sider have been synced & installed into eFootball!",
        "msg_confirm_del": "Are you sure you want to permanently delete mod '{name}'?",
        "msg_game_not_found": "Please launch eFootball from Steam first!",
        "msg_applied_mod": "Successfully injected {count} teams from mod '{name}' into RAM!",
        "msg_no_teams_mod": "No team replacement rules found in this mod.",
        "mod_active": "🟢 ACTIVE",
        "mod_disabled": "⚪ Disabled",
        "safe_ui": "🟢 On-Screen UI Text (Safe)",
        "internal_key": "⚙️ Engine Internal Key",
        "code_sec": "🔴 Executable Code",
    }
}
RE_ASSET_PATH = re.compile(
    rb"(?:/(?:Game|Engine|PesConsole|Asset|Wwise)/[A-Za-z0-9_/\-\.]+|common/[A-Za-z0-9_/\-\.]+|[A-Za-z0-9_\-\.]{3,}\.(?:uasset|ubulk|uexp|bin|dds|png|cpk|pak|locres|wem|bnk)|(?:st[0-9]{3}|u[0-9]{4})[A-Za-z0-9_\-]*)",
    re.IGNORECASE
)
RE_ASSET_UTF16 = re.compile(
    rb"(?:/\x00(?:G\x00a\x00m\x00e\x00|E\x00n\x00g\x00i\x00n\x00e\x00)/[A-Za-z0-9_/\-\.\x00]{4,})",
    re.IGNORECASE
)
class StealthMemoryEngine:
    def __init__(self):
        self.pid = None
        self.handle = None
        self.is_attached = False
        self._sniff_max = 8 * 1024 * 1024
        self._sniff_buf = (ctypes.c_char * self._sniff_max)()
        self._mbi = MEMORY_BASIC_INFORMATION64()
        self.sniffer_cursor = 0x100000000  
        self.sniffer_max_address = 0x00007FFFFFFFFFF0
    def find_process(self):
        import subprocess
        try:
            out = subprocess.check_output('tasklist /FI "IMAGENAME eq eFootball.exe" /FO CSV /NH', shell=True).decode()
            for line in out.strip().split("\n"):
                if "eFootball.exe" in line:
                    parts = line.replace('"', '').split(",")
                    if len(parts) >= 2:
                        return int(parts[1])
        except Exception:
            pass
        return None
    def check_alive(self):
        if not self.handle:
            return False
        exit_code = wintypes.DWORD(0)
        if GetExitCodeProcess(self.handle, ctypes.byref(exit_code)):
            if exit_code.value == 259:
                return True
        self.detach()
        return False
    def attach(self):
        if self.check_alive():
            return True, f"Connected to PID {self.pid}"
        pid = self.find_process()
        if not pid:
            self.detach()
            return False, "Process not running"
        h = OpenProcess(PROCESS_STEALTH_ACCESS, False, pid)
        if not h:
            self.detach()
            return False, f"Cannot open PID {pid}"
        self.pid = pid
        self.handle = h
        self.is_attached = True
        return True, f"Stealth attach to PID {pid}"
    def detach(self):
        if self.handle:
            try:
                CloseHandle(self.handle)
            except Exception:
                pass
            self.handle = None
        self.pid = None
        self.is_attached = False
    def read_bytes(self, address, size):
        if not self.check_alive():
            return None
        buf = (ctypes.c_char * size)()
        read_b = ctypes.c_size_t(0)
        if ReadProcessMemory(self.handle, ctypes.c_void_p(address), buf, size, ctypes.byref(read_b)):
            return bytes(buf[:read_b.value])
        return None
    def write_bytes_safe(self, address, data):
        if not self.check_alive():
            return False
        size = len(data)
        old_prot = wintypes.DWORD(0)
        if not VirtualProtectEx(self.handle, ctypes.c_void_p(address), size, PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot)):
            return False
        written = ctypes.c_size_t(0)
        res = WriteProcessMemory(self.handle, ctypes.c_void_p(address), data, size, ctypes.byref(written))
        VirtualProtectEx(self.handle, ctypes.c_void_p(address), size, old_prot.value, ctypes.byref(old_prot))
        return bool(res and written.value == size)
    def scan_for_database_blocks(self, on_found=None, on_progress=None):
        if not self.check_alive():
            return []
        db_results = []
        mbi = MEMORY_BASIC_INFORMATION64()
        address = 0x10000
        max_chunk = 16 * 1024 * 1024
        buf = (ctypes.c_char * max_chunk)()
        read_b = ctypes.c_size_t(0)
        signatures = [
            (b"WESYS", "Konami PESDB Container (WESYS)"),
            (b"common/etc/pesdb/Team.bin", "Team Database Pointer (Team.bin)"),
            (b"common/etc/pesdb/TeamColor.bin", "Team Colors Pointer (TeamColor.bin)"),
            (b"common/etc/pesdb/CategoryTeamList.bin", "Category Team List Pointer"),
            (b"common/etc/appearance/PlayerAppearance.bin", "Player Appearance Database Pointer"),
            (b"@UTF", "CRI UTF Data Table"),
            (b"Piemonte BN", "Active Team Table (Juventus Slot)"),
            (b"Madrid Chamartin", "Active Team Table (Real Madrid Slot)"),
            (b"London FC", "Active Team Table (Chelsea Slot)"),
            (b"Man Blue", "Active Team Table (Man City Slot)"),
        ]
        regions_scanned = 0
        total_mb = 0
        while True:
            res = VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
            if res == 0:
                break
            is_data_heap = (
                mbi.State == MEM_COMMIT
                and (mbi.Protect & PAGE_GUARD == 0)
                and (mbi.Protect & PAGE_NOACCESS == 0)
                and bool(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY))
                and (mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY) == 0)
            )
            if is_data_heap and 1024 <= mbi.RegionSize <= max_chunk:
                reg_size = mbi.RegionSize
                regions_scanned += 1
                total_mb += reg_size // (1024 * 1024)
                if regions_scanned % 40 == 0 and on_progress:
                    on_progress(regions_scanned, total_mb)
                if ReadProcessMemory(self.handle, ctypes.c_void_p(mbi.BaseAddress), buf, reg_size, ctypes.byref(read_b)):
                    raw = bytes(buf[:read_b.value])
                    for sig_bytes, sig_name in signatures:
                        idx = raw.find(sig_bytes)
                        if idx != -1:
                            match_addr = mbi.BaseAddress + idx
                            entry = {
                                "address": f"0x{match_addr:X}",
                                "int_addr": match_addr,
                                "size": f"{reg_size:,d} bytes",
                                "raw_size": reg_size,
                                "name": sig_name,
                                "status": "🟢 In RAM",
                                "base_addr": mbi.BaseAddress
                            }
                            db_results.append(entry)
                            if on_found:
                                on_found(entry)
            next_addr = mbi.BaseAddress + mbi.RegionSize
            if next_addr <= address or next_addr >= 0x00007FFFFFFFFFF0:
                break
            address = next_addr
        return db_results
    def inject_database_bytes(self, target_address, data_bytes):
        if not self.check_alive() or not data_bytes:
            return False, "Processo non attivo o file vuoto"
        size = len(data_bytes)
        old_prot = wintypes.DWORD(0)
        if not VirtualProtectEx(self.handle, ctypes.c_void_p(target_address), size, PAGE_EXECUTE_READWRITE, ctypes.byref(old_prot)):
            return False, "VirtualProtectEx fallita"
        written = ctypes.c_size_t(0)
        res = WriteProcessMemory(self.handle, ctypes.c_void_p(target_address), data_bytes, size, ctypes.byref(written))
        VirtualProtectEx(self.handle, ctypes.c_void_p(target_address), size, old_prot.value, ctypes.byref(old_prot))
        if res and written.value == size:
            return True, f"Scritti con successo {written.value:,d} byte a 0x{target_address:X}"
        return False, f"Scritti solo {written.value:,d} su {size:,d} byte"
    def scan_memory_generator(self, query_str, case_sensitive=False, stop_event=None, max_results=300):
        if not self.check_alive():
            return
        q_clean = query_str.strip()
        if not q_clean:
            return
        if case_sensitive:
            q_ascii = q_clean.encode("latin-1")
            q_u16 = q_clean.encode("utf-16le")
        else:
            q_ascii = q_clean.lower().encode("latin-1")
            q_u16 = q_clean.lower().encode("utf-16le")
        len_ascii = len(q_ascii)
        len_u16 = len(q_u16)
        mbi = MEMORY_BASIC_INFORMATION64()
        address = 0x10000
        found_count = 0
        max_chunk = 64 * 1024 * 1024
        buf = (ctypes.c_char * max_chunk)()
        read_b = ctypes.c_size_t(0)
        try:
            if case_sensitive:
                re_ascii = re.compile(re.escape(q_clean.encode("latin-1")))
                re_u16 = re.compile(re.escape(q_clean.encode("utf-16le")))
            else:
                re_ascii = re.compile(re.escape(q_clean.encode("latin-1")), re.IGNORECASE)
                re_u16 = re.compile(re.escape(q_clean.encode("utf-16le")), re.IGNORECASE)
        except Exception:
            logger.exception("Errore compilazione regex per la query '%s'", q_clean)
            return
        while True:
            if stop_event and stop_event.is_set():
                break
            res = VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
            if res == 0:
                break
            is_code_sec = bool(mbi.Protect & (PAGE_EXECUTE | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))
            is_readable = (
                mbi.State == MEM_COMMIT
                and (mbi.Protect & PAGE_GUARD == 0)
                and (mbi.Protect & PAGE_NOACCESS == 0)
                and bool(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY))
            )
            if is_readable and 0 < mbi.RegionSize <= max_chunk:
                reg_size = mbi.RegionSize
                if ReadProcessMemory(self.handle, ctypes.c_void_p(mbi.BaseAddress), buf, reg_size, ctypes.byref(read_b)):
                    raw = bytes(buf[:read_b.value])
                    for match in re_ascii.finditer(raw):
                        idx = match.start()
                        target_addr = mbi.BaseAddress + idx
                        ctx_len = min(len(raw) - idx, len_ascii + 24)
                        cur_snippet = raw[idx:idx + ctx_len].decode("latin-1", errors="replace").split("\x00")[0]
                        is_path = "/" in cur_snippet or "\\" in cur_snippet or ".uasset" in cur_snippet or ".ubulk" in cur_snippet
                        is_ui_display = (not is_code_sec) and (not is_path)
                        yield {
                            "address": target_addr,
                            "encoding": "ASCII",
                            "current": cur_snippet,
                            "matched_len": len_ascii,
                            "region_size": reg_size,
                            "is_ui_display": is_ui_display,
                            "is_code": is_code_sec
                        }
                        found_count += 1
                        if found_count >= max_results:
                            return
                    for match in re_u16.finditer(raw):
                        idx = match.start()
                        target_addr = mbi.BaseAddress + idx
                        ctx_len = min(len(raw) - idx, len_u16 + 48)
                        cur_snippet = raw[idx:idx + ctx_len].decode("utf-16le", errors="replace").split("\x00")[0]
                        is_path = "/" in cur_snippet or "\\" in cur_snippet or ".uasset" in cur_snippet or ".ubulk" in cur_snippet
                        is_ui_display = (not is_code_sec) and (not is_path)
                        yield {
                            "address": target_addr,
                            "encoding": "UTF-16",
                            "current": cur_snippet,
                            "matched_len": len_u16,
                            "region_size": reg_size,
                            "is_ui_display": is_ui_display,
                            "is_code": is_code_sec
                        }
                        found_count += 1
                        if found_count >= max_results:
                            return
            next_addr = mbi.BaseAddress + mbi.RegionSize
            if next_addr <= address or next_addr >= 0x00007FFFFFFFFFF0:
                break
            address = next_addr
    def sniff_assets_live(self, budget_mb=32, max_new_items=50):
        if not self.check_alive():
            return []
        sniffed = []
        mbi = self._mbi
        address = self.sniffer_cursor
        buf = self._sniff_buf
        max_chunk = self._sniff_max
        read_b = ctypes.c_size_t(0)
        bytes_scanned = 0
        budget_bytes = budget_mb * 1024 * 1024
        while True:
            res = VirtualQueryEx(self.handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
            if res == 0:
                self.sniffer_cursor = 0x100000000
                break
            is_readable = (
                mbi.State == MEM_COMMIT
                and (mbi.Protect & PAGE_GUARD == 0)
                and (mbi.Protect & PAGE_NOACCESS == 0)
                and bool(mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE))
            )
            if is_readable and 4096 <= mbi.RegionSize <= max_chunk:
                reg_size = mbi.RegionSize
                bytes_scanned += reg_size
                if ReadProcessMemory(self.handle, ctypes.c_void_p(mbi.BaseAddress), buf, reg_size, ctypes.byref(read_b)):
                    raw = bytes(buf[:read_b.value])
                    for match in RE_ASSET_PATH.finditer(raw):
                        asset_bytes = match.group(0)
                        if len(asset_bytes) < 4:
                            continue
                        asset_str = asset_bytes.decode("latin-1", errors="ignore").strip()
                        target_addr = mbi.BaseAddress + match.start()
                        cat = "📦 File / Package"
                        lower = asset_str.lower()
                        if lower.endswith(".dds") or lower.endswith(".png") or "texture" in lower or lower.startswith("t_"):
                            cat = "🎨 Texture 2D (DDS/PNG)"
                        elif lower.endswith(".ubulk") or lower.endswith(".uexp") or "mesh" in lower or "model" in lower:
                            cat = "📐 Modello 3D / Mesh"
                        elif lower.endswith(".bin") or "pesdb" in lower:
                            cat = "📊 Database Fox (.bin)"
                        elif lower.endswith(".wem") or lower.endswith(".bnk") or "sound" in lower or "audio" in lower:
                            cat = "🔊 Audio / Chants (.wem)"
                        elif lower.endswith(".locres") or "localization" in lower:
                            cat = "🌐 Localizzazione / Testo"
                        elif lower.startswith("st0") or lower.startswith("st8") or "pitch" in lower or "turf" in lower or "stadium" in lower:
                            cat = "🏟️ Stadio / Turf"
                        elif lower.startswith("u0") or "kit" in lower or "jersey" in lower:
                            cat = "👕 Maglia / Kit (u0xxx)"
                        elif "piemonte" in lower or "madrid" in lower or "london" in lower or "inter" in lower or "juventus" in lower:
                            cat = "🏆 Squadra / Team"
                        sniffed.append({
                            "category": cat,
                            "address": target_addr,
                            "path": asset_str,
                            "region_size": reg_size
                        })
                        if len(sniffed) >= max_new_items:
                            next_addr = mbi.BaseAddress + mbi.RegionSize
                            self.sniffer_cursor = next_addr if next_addr < self.sniffer_max_address else 0x100000000
                            return sniffed
                    for match in RE_ASSET_UTF16.finditer(raw):
                        asset_bytes = match.group(0)
                        try:
                            asset_str = asset_bytes.decode("utf-16le", errors="ignore").strip()
                            if len(asset_str) >= 4:
                                target_addr = mbi.BaseAddress + match.start()
                                sniffed.append({
                                    "category": "🌐 Asset UTF-16 (UE4)",
                                    "address": target_addr,
                                    "path": asset_str,
                                    "region_size": reg_size
                                })
                                if len(sniffed) >= max_new_items:
                                    next_addr = mbi.BaseAddress + mbi.RegionSize
                                    self.sniffer_cursor = next_addr if next_addr < self.sniffer_max_address else 0x100000000
                                    return sniffed
                        except Exception:
                            pass
            next_addr = mbi.BaseAddress + mbi.RegionSize
            if next_addr <= address or next_addr >= self.sniffer_max_address:
                self.sniffer_cursor = 0x100000000
                break
            address = next_addr
            self.sniffer_cursor = address
            if bytes_scanned >= budget_bytes or len(sniffed) > 0:
                break
        return sniffed
def sort_treeview_column(tv, col, reverse=False):
    l = [(str(tv.set(k, col)), k) for k in tv.get_children("")]
    def convert_val(val_str):
        v = val_str.strip()
        if not v:
            return (3, "")
        if v.startswith("0x") or v.startswith("0X"):
            try:
                return (0, int(v, 16))
            except ValueError:
                pass
        clean = re.sub(r"[^\d.]", "", v)
        if clean:
            try:
                if "." in clean:
                    return (1, float(clean))
                else:
                    return (1, int(clean))
            except ValueError:
                pass
        return (2, v.lower())
    l.sort(key=lambda t: convert_val(t[0]), reverse=reverse)
    for index, (val, k) in enumerate(l):
        tv.move(k, "", index)
    tv.heading(col, command=lambda: sort_treeview_column(tv, col, not reverse))
class SiderTorigaGUI:
    def __init__(self, root):
        self.root = root
        self.lang = "IT"
        self.root.title(self.t("title"))
        self.root.geometry("1340x860")
        self.root.minsize(1100, 720)
        self.root.configure(bg="#111115")
        self.engine = StealthMemoryEngine()
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.sider_pkg_dir = self.base_dir
        self.game_bin_dir = r"A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64"
        self.content_dir = os.path.join(self.base_dir, "content")
        self.sider_ini_path = os.path.join(self.base_dir, "sider.ini")
        if not os.path.exists(self.content_dir):
            os.makedirs(self.content_dir, exist_ok=True)
        self.sniffer_running = False
        self.seen_signatures = set()
        self.all_sniffed_items = []
        self.filtered_sniffed_items = []
        self.current_filter_query = ""
        self.sniffer_page = 1
        self.sniffer_page_size = 50
        self.auto_scroll_latest = tk.BooleanVar(value=True)
        self.sniffer_sort_col = "time"
        self.sniffer_sort_reverse = False
        self.current_hex_addr = None
        self.current_asset_path = ""
        self.current_asset_cat = ""
        self.current_decoded_image = None
        self.current_replacement_file = None
        self._preview_photo_ref = None
        self.search_stop_event = threading.Event()
        self.is_searching = False
        self.search_results = []
        self.installed_mods = []
        self.cam_enabled = tk.BooleanVar(value=True)
        self.cam_zoom = tk.DoubleVar(value=0.82)
        self.cam_height = tk.DoubleVar(value=1.32)
        self.cam_angle = tk.DoubleVar(value=-0.12)
        self.cam_fov = tk.DoubleVar(value=50.0)
        self.cam_freecam_speed = tk.DoubleVar(value=2.5)
        self.setup_ui()
        self.load_installed_mods()
        self.load_camera_from_sider_ini()
        self.auto_attach_loop()
    def t(self, key, **kwargs):
        tmpl = LANG_DATA.get(self.lang, LANG_DATA["IT"]).get(key, key)
        if kwargs:
            return tmpl.format(**kwargs)
        return tmpl
    def switch_language(self, new_lang):
        self.lang = new_lang
        self.refresh_all_labels()
    def setup_ui(self):
        header = tk.Frame(self.root, bg="#181822", height=65)
        header.pack(fill=tk.X, side=tk.TOP)
        self.lbl_title = tk.Label(header, text=f"⚽ {self.t('title')}", font=("Segoe UI", 15, "bold"), fg="#38bdf8", bg="#181822")
        self.lbl_title.pack(side=tk.LEFT, padx=18, pady=12)
        self.lbl_status = tk.Label(header, text=self.t("waiting"), font=("Segoe UI", 10, "bold"), fg="#fbbf24", bg="#181822")
        self.lbl_status.pack(side=tk.LEFT, padx=10)
        lang_frame = tk.Frame(header, bg="#181822")
        lang_frame.pack(side=tk.RIGHT, padx=18, pady=12)
        btn_it = tk.Button(lang_frame, text="🇮🇹 IT", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ffffff", relief=tk.FLAT, padx=8, pady=3, command=lambda: self.switch_language("IT"))
        btn_it.pack(side=tk.LEFT, padx=3)
        btn_en = tk.Button(lang_frame, text="🇬🇧 EN", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#ffffff", relief=tk.FLAT, padx=8, pady=3, command=lambda: self.switch_language("EN"))
        btn_en.pack(side=tk.LEFT, padx=3)
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background="#111115")
        style.configure("TNotebook.Tab", background="#22222c", foreground="#d1d5db", padding=[16, 9], font=("Segoe UI", 10, "bold"))
        style.map("TNotebook.Tab", background=[("selected", "#0284c7")], foreground=[("selected", "#ffffff")])
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)
        self.tab_sniffer = tk.Frame(self.notebook, bg="#16161d")
        self.notebook.add(self.tab_sniffer, text=self.t("tab_sniffer"))
        self.setup_tab_sniffer_ui()
        self.tab_hex = tk.Frame(self.notebook, bg="#16161d")
        self.notebook.add(self.tab_hex, text=self.t("tab_hex"))
        self.setup_tab_hex_ui()
        self.tab_search = tk.Frame(self.notebook, bg="#16161d")
        self.notebook.add(self.tab_search, text=self.t("tab_search"))
        self.setup_tab_search_ui()
        self.tab_mods = tk.Frame(self.notebook, bg="#16161d")
        self.notebook.add(self.tab_mods, text=self.t("tab_mods"))
        self.setup_tab_mods_ui()
        self.tab_db = tk.Frame(self.notebook, bg="#16161d")
        self.notebook.add(self.tab_db, text=self.t("tab_db_injector"))
        self.setup_tab_db_ui()
        self.tab_camera = tk.Frame(self.notebook, bg="#16161d")
        self.notebook.add(self.tab_camera, text=self.t("tab_camera"))
        self.setup_tab_camera_ui()
    def setup_tab_sniffer_ui(self):
        toolbar = tk.Frame(self.tab_sniffer, bg="#1f1f2b", padx=14, pady=8)
        toolbar.pack(fill=tk.X, padx=12, pady=(8, 2))
        self.btn_sniffer = tk.Button(toolbar, text=self.t("btn_start_sniffer"), font=("Segoe UI", 11, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=16, pady=4, command=self.toggle_sniffer)
        self.btn_sniffer.pack(side=tk.LEFT, padx=4)
        self.btn_clear_sniffer = tk.Button(toolbar, text=self.t("btn_clear_sniffer"), font=("Segoe UI", 10), bg="#374151", fg="white", relief=tk.FLAT, padx=10, pady=4, command=self.clear_sniffer_data)
        self.btn_clear_sniffer.pack(side=tk.LEFT, padx=4)
        tk.Label(toolbar, text="🏷️ Tipo Asset:", font=("Segoe UI", 10, "bold"), fg="#38bdf8", bg="#1f1f2b").pack(side=tk.LEFT, padx=(12, 3))
        self.category_filter_list = [
            "🌟 Tutte le Categorie",
            "👕 Maglie & Kit (u0xxx)",
            "🏟️ Stadi & Turf (stxxx)",
            "🎨 Texture 2D (DDS/PNG)",
            "📐 Modelli 3D / Mesh (.ubulk/.uexp)",
            "📊 Database Fox (.bin)",
            "🔊 Audio / Cori / Chants (.wem/.bnk)",
            "🌐 Localizzazione / Testo (.locres)",
            "🏆 Squadre & Team",
            "📦 File / Package Generici",
            "🌐 Asset UTF-16 (UE4)"
        ]
        self.combo_cat_filter = ttk.Combobox(toolbar, values=self.category_filter_list, width=22, state="readonly")
        self.combo_cat_filter.set("🌟 Tutte le Categorie")
        self.combo_cat_filter.pack(side=tk.LEFT, padx=3)
        self.combo_cat_filter.bind("<<ComboboxSelected>>", lambda e: self.apply_sniffer_filter())
        self.lbl_sniffer_filter = tk.Label(toolbar, text="🔎 Testo:", font=("Segoe UI", 10, "bold"), fg="#38bdf8", bg="#1f1f2b")
        self.lbl_sniffer_filter.pack(side=tk.LEFT, padx=(10, 3))
        self.ent_sniffer_filter = tk.Entry(toolbar, font=("Segoe UI", 11), width=18, bg="#111116", fg="#ffffff", insertbackground="white", relief=tk.FLAT)
        self.ent_sniffer_filter.pack(side=tk.LEFT, padx=3, ipady=3)
        self.ent_sniffer_filter.bind("<KeyRelease>", lambda e: self.apply_sniffer_filter())
        self.lbl_sniffer_info = tk.Label(toolbar, text=self.t("sniffer_info_idle"), font=("Segoe UI", 9, "italic"), fg="#fbbf24", bg="#1f1f2b")
        self.lbl_sniffer_info.pack(side=tk.RIGHT, padx=10)
        pill_bar = tk.Frame(self.tab_sniffer, bg="#181824", padx=12, pady=4)
        pill_bar.pack(fill=tk.X, padx=12, pady=(0, 4))
        tk.Label(pill_bar, text="⚡ Filtro Rapido:", font=("Segoe UI", 9, "bold"), fg="#94a3b8", bg="#181824").pack(side=tk.LEFT, padx=(2, 6))
        pills = [
            ("🌟 Tutti", "Tutte"),
            ("👕 Kit", "Kit"),
            ("🏟️ Stadi", "Stadi"),
            ("🎨 Texture", "Texture"),
            ("📐 Mesh 3D", "Modelli"),
            ("📊 Database", "Database"),
            ("🔊 Audio", "Audio"),
            ("🌐 Testi", "Localizzazione"),
            ("🏆 Squadre", "Squadre")
        ]
        for p_label, p_key in pills:
            btn_p = tk.Button(pill_bar, text=p_label, font=("Segoe UI", 8, "bold"), bg="#1e293b", fg="#e2e8f0", activebackground="#0284c7", activeforeground="white", relief=tk.FLAT, padx=6, pady=1, command=lambda k=p_key: self.set_quick_category(k))
            btn_p.pack(side=tk.LEFT, padx=2)
        table_frame = tk.Frame(self.tab_sniffer, bg="#16161d")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        cols = ("time", "cat", "addr", "path")
        self.tree_sniffer = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree_sniffer.heading("time", text=self.t("col_time"), command=lambda: self.sort_sniffer_dataset("time"))
        self.tree_sniffer.heading("cat", text=self.t("col_type"), command=lambda: self.sort_sniffer_dataset("cat"))
        self.tree_sniffer.heading("addr", text=self.t("col_addr"), command=lambda: self.sort_sniffer_dataset("addr"))
        self.tree_sniffer.heading("path", text=self.t("col_path"), command=lambda: self.sort_sniffer_dataset("path"))
        self.tree_sniffer.column("time", width=120, anchor="center")
        self.tree_sniffer.column("cat", width=220, anchor="center")
        self.tree_sniffer.column("addr", width=200, anchor="center")
        self.tree_sniffer.column("path", width=580, anchor="w")
        scroll_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree_sniffer.yview)
        self.tree_sniffer.configure(yscrollcommand=scroll_y.set)
        self.tree_sniffer.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_sniffer.bind("<Double-1>", lambda e: self.open_selected_in_hex())
        pag_bar = tk.Frame(self.tab_sniffer, bg="#181824", padx=14, pady=5)
        pag_bar.pack(fill=tk.X, padx=12, pady=(2, 4))
        self.btn_first_page = tk.Button(pag_bar, text="⏮ Primo", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#38bdf8", relief=tk.FLAT, padx=8, pady=2, command=lambda: self.go_sniffer_page("first"))
        self.btn_first_page.pack(side=tk.LEFT, padx=2)
        self.btn_prev_page = tk.Button(pag_bar, text="◀ Prec", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#38bdf8", relief=tk.FLAT, padx=8, pady=2, command=lambda: self.go_sniffer_page("prev"))
        self.btn_prev_page.pack(side=tk.LEFT, padx=2)
        self.lbl_sniffer_pages = tk.Label(pag_bar, text="Pagina 1 di 1 (0 asset catturati)", font=("Segoe UI", 9, "bold"), fg="#ffffff", bg="#181824")
        self.lbl_sniffer_pages.pack(side=tk.LEFT, padx=10)
        self.btn_next_page = tk.Button(pag_bar, text="Succ ▶", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#38bdf8", relief=tk.FLAT, padx=8, pady=2, command=lambda: self.go_sniffer_page("next"))
        self.btn_next_page.pack(side=tk.LEFT, padx=2)
        self.btn_last_page = tk.Button(pag_bar, text="Ultimo ⏭", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#38bdf8", relief=tk.FLAT, padx=8, pady=2, command=lambda: self.go_sniffer_page("last"))
        self.btn_last_page.pack(side=tk.LEFT, padx=2)
        tk.Label(pag_bar, text="Righe/pag:", font=("Segoe UI", 9), fg="#94a3b8", bg="#181824").pack(side=tk.LEFT, padx=(14, 3))
        self.combo_page_size = ttk.Combobox(pag_bar, values=["25", "50", "100", "200"], width=5, state="readonly")
        self.combo_page_size.set("50")
        self.combo_page_size.pack(side=tk.LEFT, padx=2)
        self.combo_page_size.bind("<<ComboboxSelected>>", self.on_change_page_size)
        self.chk_auto_scroll = tk.Checkbutton(pag_bar, text="🔴 Segui Live (Auto-scroll)", variable=self.auto_scroll_latest, font=("Segoe UI", 9), fg="#4ade80", bg="#181824", selectcolor="#1e293b", activebackground="#181824")
        self.chk_auto_scroll.pack(side=tk.RIGHT, padx=5)
        act_bar = tk.Frame(self.tab_sniffer, bg="#1a1a24", padx=14, pady=8)
        act_bar.pack(fill=tk.X, padx=12, pady=(0, 10))
        self.btn_inspect = tk.Button(act_bar, text=self.t("btn_inspect_hex"), font=("Segoe UI", 10, "bold"), bg="#6366f1", fg="white", relief=tk.FLAT, padx=14, pady=5, command=self.open_selected_in_hex)
        self.btn_inspect.pack(side=tk.LEFT, padx=5)
        self.btn_create_mod = tk.Button(act_bar, text=self.t("btn_make_mod"), font=("Segoe UI", 10, "bold"), bg="#f59e0b", fg="black", relief=tk.FLAT, padx=14, pady=5, command=self.create_mod_from_selected_asset)
        self.btn_create_mod.pack(side=tk.LEFT, padx=5)
    def on_change_page_size(self, event=None):
        try:
            sz = int(self.combo_page_size.get())
            self.sniffer_page_size = sz
            self.sniffer_page = 1
            self.render_sniffer_page()
        except ValueError:
            pass
    def get_active_sniffer_items(self):
        query = self.ent_sniffer_filter.get().strip().lower() if hasattr(self, 'ent_sniffer_filter') else ""
        cat_filter = self.combo_cat_filter.get() if hasattr(self, 'combo_cat_filter') else "🌟 Tutte le Categorie"
        is_filtered = bool(query) or (cat_filter and "Tutte" not in cat_filter)
        return self.filtered_sniffed_items if is_filtered else self.all_sniffed_items
    def sort_sniffer_dataset(self, col):
        if self.sniffer_sort_col == col:
            self.sniffer_sort_reverse = not self.sniffer_sort_reverse
        else:
            self.sniffer_sort_col = col
            self.sniffer_sort_reverse = False
        def get_sort_key(item):
            if col == "time":
                return item.get("time", "")
            elif col == "cat":
                return item.get("category", "").lower()
            elif col == "addr":
                return item.get("address", 0)
            elif col == "path":
                return item.get("path", "").lower()
            return ""
        self.all_sniffed_items.sort(key=get_sort_key, reverse=self.sniffer_sort_reverse)
        if self.filtered_sniffed_items:
            self.filtered_sniffed_items.sort(key=get_sort_key, reverse=self.sniffer_sort_reverse)
        for c, text_key in [("time", "col_time"), ("cat", "col_type"), ("addr", "col_addr"), ("path", "col_path")]:
            arrow = " ▲" if (c == col and not self.sniffer_sort_reverse) else (" ▼" if (c == col and self.sniffer_sort_reverse) else "")
            self.tree_sniffer.heading(c, text=f"{self.t(text_key)}{arrow}", command=lambda c_name=c: self.sort_sniffer_dataset(c_name))
        self.render_sniffer_page()
    def go_sniffer_page(self, action):
        items = self.get_active_sniffer_items()
        total_items = len(items)
        total_pages = max(1, (total_items + self.sniffer_page_size - 1) // self.sniffer_page_size)
        if action == "first":
            self.sniffer_page = 1
        elif action == "prev":
            self.sniffer_page = max(1, self.sniffer_page - 1)
        elif action == "next":
            self.sniffer_page = min(total_pages, self.sniffer_page + 1)
        elif action == "last":
            self.sniffer_page = total_pages
        self.render_sniffer_page()
    def render_sniffer_page(self):
        items = self.get_active_sniffer_items()
        total_items = len(items)
        total_pages = max(1, (total_items + self.sniffer_page_size - 1) // self.sniffer_page_size)
        self.sniffer_page = min(max(1, self.sniffer_page), total_pages)
        start_idx = (self.sniffer_page - 1) * self.sniffer_page_size
        end_idx = start_idx + self.sniffer_page_size
        page_items = items[start_idx:end_idx]
        self.lbl_sniffer_pages.config(text=f"Pagina {self.sniffer_page} di {total_pages} ({total_items:,d} asset catturati)")
        self.tree_sniffer.delete(*self.tree_sniffer.get_children())
        for it in page_items:
            addr_str = f"0x{it['address']:012X}"
            self.tree_sniffer.insert("", tk.END, values=(it["time"], it["category"], addr_str, it["path"]))
    def set_quick_category(self, key):
        for val in self.category_filter_list:
            if key == "Tutte" and "Tutte" in val:
                self.combo_cat_filter.set(val)
                break
            elif key in val:
                self.combo_cat_filter.set(val)
                break
        self.apply_sniffer_filter()
    def _matches_active_filter(self, item, query, cat_filter):
        if cat_filter and "Tutte" not in cat_filter:
            item_cat = item["category"]
            if "Kit" in cat_filter and "Kit" not in item_cat:
                return False
            elif "Stadi" in cat_filter and ("Stadio" not in item_cat and "Turf" not in item_cat):
                return False
            elif "Texture" in cat_filter and "Texture" not in item_cat:
                return False
            elif "Modelli" in cat_filter and ("Modello" not in item_cat and "Mesh" not in item_cat):
                return False
            elif "Database" in cat_filter and "Database" not in item_cat:
                return False
            elif "Audio" in cat_filter and "Audio" not in item_cat:
                return False
            elif "Localizzazione" in cat_filter and "Localizzazione" not in item_cat:
                return False
            elif "Squadre" in cat_filter and "Squadra" not in item_cat:
                return False
            elif "UTF-16" in cat_filter and "UTF-16" not in item_cat:
                return False
            elif "Package" in cat_filter and "Package" not in item_cat:
                return False
        if query:
            return (query in item["path"].lower() or query in item["category"].lower() or query in f"0x{item['address']:X}".lower())
        return True
    def apply_sniffer_filter(self):
        query = self.ent_sniffer_filter.get().strip().lower()
        self.current_filter_query = query
        cat_filter = self.combo_cat_filter.get() if hasattr(self, 'combo_cat_filter') else "🌟 Tutte le Categorie"
        is_filtered = bool(query) or (cat_filter and "Tutte" not in cat_filter)
        if is_filtered:
            self.filtered_sniffed_items = [
                it for it in self.all_sniffed_items
                if self._matches_active_filter(it, query, cat_filter)
            ]
        else:
            self.filtered_sniffed_items = []
        self.sniffer_page = 1
        self.render_sniffer_page()
    def toggle_sniffer(self):
        if self.sniffer_running:
            self.sniffer_running = False
            self.btn_sniffer.config(text=self.t("btn_start_sniffer"), bg="#10b981")
            self.lbl_sniffer_info.config(text=self.t("sniffer_info_idle"))
        else:
            if not self.engine.check_alive():
                self.engine.attach()
                if not self.engine.check_alive():
                    messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                    return
            self.sniffer_running = True
            self.btn_sniffer.config(text=self.t("btn_stop_sniffer"), bg="#ef4444")
            self.lbl_sniffer_info.config(text=self.t("sniffer_info_active"))
            threading.Thread(target=self._sniffer_loop, daemon=True).start()
    def clear_sniffer_data(self):
        self.tree_sniffer.delete(*self.tree_sniffer.get_children())
        self.seen_signatures.clear()
        self.all_sniffed_items.clear()
        self.filtered_sniffed_items.clear()
        self.sniffer_page = 1
        self.render_sniffer_page()
    def _sniffer_loop(self):
        while self.sniffer_running:
            if self.engine.check_alive():
                new_items = self.engine.sniff_assets_live(budget_mb=32, max_new_items=50)
                to_add = []
                cur_time = time.strftime("%H:%M:%S")
                for item in new_items:
                    sig = f"{item['address']}_{item['path']}"
                    if sig not in self.seen_signatures:
                        self.seen_signatures.add(sig)
                        item["time"] = cur_time
                        self.all_sniffed_items.append(item)
                        to_add.append(item)
                if to_add:
                    query = self.current_filter_query
                    cat_filter = self.combo_cat_filter.get() if hasattr(self, 'combo_cat_filter') else ""
                    is_filtered = bool(query) or (cat_filter and "Tutte" not in cat_filter)
                    if is_filtered:
                        for it in to_add:
                            if self._matches_active_filter(it, query, cat_filter):
                                self.filtered_sniffed_items.append(it)
                    if self.auto_scroll_latest.get():
                        items = self.get_active_sniffer_items()
                        total_pages = max(1, (len(items) + self.sniffer_page_size - 1) // self.sniffer_page_size)
                        self.sniffer_page = total_pages
                    self.root.after(0, self.render_sniffer_page)
            time.sleep(0.08)
    def open_selected_in_hex(self):
        sel = self.tree_sniffer.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        vals = self.tree_sniffer.item(sel[0])["values"]
        cat = vals[1]
        addr_hex = vals[2]
        path = str(vals[3]).strip()
        addr = int(addr_hex, 16)
        self.current_hex_addr = addr
        self.current_asset_path = path
        self.current_asset_cat = cat
        self.notebook.select(self.tab_hex)
        self.load_visual_and_hex_from_address(addr, path, cat)
    def create_mod_from_selected_asset(self):
        sel = self.tree_sniffer.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        vals = self.tree_sniffer.item(sel[0])["values"]
        cat = vals[1]
        path = str(vals[3]).strip()
        clean_name = re.sub(r"[^A-Za-z0-9_]", "_", os.path.splitext(os.path.basename(path))[0])
        if not clean_name:
            clean_name = "Custom_Mod_Asset"
        mod_folder_name = f"Mod_{clean_name}"
        target_dir = os.path.join(self.content_dir, mod_folder_name)
        os.makedirs(target_dir, exist_ok=True)
        mod_ini_content = [
            "; ==============================================================================",
            f"; Efootball Sider by Toriga - Mod Package: {mod_folder_name}",
            "; ==============================================================================",
            "[MOD]",
            f'name = "Mod {clean_name}"',
            f'category = "{cat}"',
            'author = "Toriga"',
            'version = "1.0"',
            f'target_asset = "{path}"',
            "",
            "[OVERRIDES]",
            f'; override_target = "{path}"',
        ]
        with open(os.path.join(target_dir, "mod.ini"), "w", encoding="utf-8") as f:
            f.write("\n".join(mod_ini_content) + "\n")
        self.load_installed_mods()
        self.notebook.select(self.tab_mods)
        messagebox.showinfo(self.t("title"), f"Pacchetto Mod '{mod_folder_name}' creato con successo in content/{mod_folder_name}!\nPronto per contenere i tuoi asset sostitutivi.")
    def setup_tab_hex_ui(self):
        top_bar = tk.Frame(self.tab_hex, bg="#1f1f2b", padx=14, pady=10)
        top_bar.pack(fill=tk.X, padx=12, pady=10)
        self.lbl_hex_addr_title = tk.Label(top_bar, text=self.t("lbl_hex_addr"), font=("Segoe UI", 11, "bold"), fg="#ffffff", bg="#1f1f2b")
        self.lbl_hex_addr_title.pack(side=tk.LEFT, padx=5)
        self.ent_hex_addr = tk.Entry(top_bar, font=("Consolas", 12, "bold"), width=20, bg="#111116", fg="#38bdf8", insertbackground="white", relief=tk.FLAT)
        self.ent_hex_addr.pack(side=tk.LEFT, padx=8, ipady=3)
        self.ent_hex_addr.insert(0, "0x00000000")
        self.btn_read_hex = tk.Button(top_bar, text=self.t("btn_read_hex"), font=("Segoe UI", 10, "bold"), bg="#0284c7", fg="white", relief=tk.FLAT, padx=14, pady=4, command=self.refresh_current_hex)
        self.btn_read_hex.pack(side=tk.LEFT, padx=6)
        self.lbl_hex_asset_name = tk.Label(top_bar, text="Asset: Nessuno", font=("Segoe UI", 10, "bold"), fg="#4ade80", bg="#1f1f2b")
        self.lbl_hex_asset_name.pack(side=tk.RIGHT, padx=10)
        paned = tk.PanedWindow(self.tab_hex, orient=tk.HORIZONTAL, bg="#111116", sashwidth=6)
        paned.pack(fill=tk.BOTH, expand=True, padx=12, pady=5)
        left_frame = tk.Frame(paned, bg="#111116", padx=6, pady=6)
        paned.add(left_frame, minsize=520)
        tk.Label(left_frame, text=self.t("lbl_hex_title"), font=("Segoe UI", 10, "bold"), fg="#38bdf8", bg="#111116").pack(anchor="w", pady=(0, 4))
        self.txt_hex = tk.Text(left_frame, font=("Consolas", 11), bg="#0d0d12", fg="#38bdf8", insertbackground="white", relief=tk.FLAT, padx=8, pady=8)
        self.txt_hex.pack(fill=tk.BOTH, expand=True)
        self.txt_hex.tag_configure("offset", foreground="#9ca3af")
        self.txt_hex.tag_configure("hexbyte", foreground="#4ade80")
        self.txt_hex.tag_configure("asciitext", foreground="#fbbf24")
        right_frame = tk.Frame(paned, bg="#181822", padx=6, pady=6)
        paned.add(right_frame, minsize=480)
        tk.Label(right_frame, text=self.t("lbl_visual_title"), font=("Segoe UI", 10, "bold"), fg="#fbbf24", bg="#181822").pack(anchor="w", pady=(0, 4))
        self.sub_notebook = ttk.Notebook(right_frame)
        self.sub_notebook.pack(fill=tk.BOTH, expand=True)
        self.sub_tab_strings = tk.Frame(self.sub_notebook, bg="#14141c")
        self.sub_notebook.add(self.sub_tab_strings, text=self.t("tab_strings"))
        self.txt_decoded = tk.Text(self.sub_tab_strings, font=("Consolas", 11), bg="#0a0a0f", fg="#ffffff", insertbackground="white", relief=tk.FLAT, padx=8, pady=8)
        self.txt_decoded.pack(fill=tk.BOTH, expand=True)
        self.sub_tab_structure = tk.Frame(self.sub_notebook, bg="#14141c")
        self.sub_notebook.add(self.sub_tab_structure, text=self.t("tab_structure"))
        self.txt_struct = tk.Text(self.sub_tab_structure, font=("Consolas", 11), bg="#0a0a0f", fg="#38bdf8", insertbackground="white", relief=tk.FLAT, padx=8, pady=8)
        self.txt_struct.pack(fill=tk.BOTH, expand=True)
        self.sub_tab_palette = tk.Frame(self.sub_notebook, bg="#14141c")
        self.sub_notebook.add(self.sub_tab_palette, text=self.t("tab_palette"))
        tex_toolbar = tk.Frame(self.sub_tab_palette, bg="#181824", padx=8, pady=6)
        tex_toolbar.pack(fill=tk.X, side=tk.TOP)
        tk.Button(tex_toolbar, text="📁 Sfoglia Texture...", font=("Segoe UI", 9, "bold"), bg="#2563eb", fg="white", relief=tk.FLAT, padx=8, pady=3, command=self.browse_and_load_texture_file).pack(side=tk.LEFT, padx=3)
        tk.Button(tex_toolbar, text="🚀 INIETTA IN SIDER (LiveCPK - Sicuro)", font=("Segoe UI", 9, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=10, pady=3, command=self.save_texture_to_livecpk).pack(side=tk.LEFT, padx=3)
        tk.Button(tex_toolbar, text="⚡ Reindirizza Path in RAM", font=("Segoe UI", 9), bg="#8b5cf6", fg="white", relief=tk.FLAT, padx=8, pady=3, command=self.redirect_texture_path_live_ram).pack(side=tk.LEFT, padx=3)
        tk.Button(tex_toolbar, text="💾 Esporta...", font=("Segoe UI", 9), bg="#4b5563", fg="white", relief=tk.FLAT, padx=6, pady=3, command=self.export_current_texture).pack(side=tk.LEFT, padx=3)
        self.lbl_tex_status = tk.Label(self.sub_tab_palette, text="Nessun file sostitutivo caricato. Clicca '📁 Sfoglia Texture' per sceglierne uno.", font=("Segoe UI", 9), fg="#9ca3af", bg="#14141c", anchor="w", padx=10, pady=3)
        self.lbl_tex_status.pack(fill=tk.X, side=tk.TOP)
        self.canvas_preview = tk.Canvas(self.sub_tab_palette, bg="#000000", highlightthickness=0)
        self.canvas_preview.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        bot_bar = tk.Frame(self.tab_hex, bg="#1a1a24", padx=14, pady=10)
        bot_bar.pack(fill=tk.X, padx=12, pady=10)
        tk.Label(bot_bar, text="✏️ Scrivi Stringa Diretta all'Indirizzo:", font=("Segoe UI", 11, "bold"), fg="#38bdf8", bg="#1a1a24").pack(side=tk.LEFT, padx=5)
        self.ent_hex_write = tk.Entry(bot_bar, font=("Segoe UI", 12), width=32, bg="#111116", fg="#ffffff", insertbackground="white", relief=tk.FLAT)
        self.ent_hex_write.pack(side=tk.LEFT, padx=10, ipady=4)
        self.btn_save_hex = tk.Button(bot_bar, text=self.t("btn_save_hex"), font=("Segoe UI", 10, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=16, pady=4, command=self.write_hex_string_to_ram)
        self.btn_save_hex.pack(side=tk.LEFT, padx=6)
    def refresh_current_hex(self):
        addr_str = self.ent_hex_addr.get().strip()
        try:
            addr = int(addr_str, 16)
            self.load_visual_and_hex_from_address(addr, self.current_asset_path, self.current_asset_cat)
        except ValueError:
            messagebox.showerror(self.t("title"), "Indirizzo esadecimale non valido (es. 0x000002A1B040).")
    def load_visual_and_hex_from_address(self, addr, path="", cat=""):
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        self.current_hex_addr = addr
        self.ent_hex_addr.delete(0, tk.END)
        self.ent_hex_addr.insert(0, f"0x{addr:012X}")
        if path:
            self.lbl_hex_asset_name.config(text=f"Asset: {os.path.basename(path)}")
        data = self.engine.read_bytes(addr, 512)
        if not data:
            self.txt_hex.delete("1.0", tk.END)
            self.txt_hex.insert(tk.END, "Impossibile leggere la memoria a questo indirizzo (Pagina non accessibile o terminata).")
            return
        self.txt_hex.delete("1.0", tk.END)
        header_str = "Indirizzo (RAM)     00 01 02 03 04 05 06 07  08 09 0A 0B 0C 0D 0E 0F   Testo Decodificato\n"
        header_str += "----------------------------------------------------------------------------------------\n"
        self.txt_hex.insert(tk.END, header_str, "offset")
        for i in range(0, min(len(data), 256), 16):
            chunk = data[i:i+16]
            line_addr = f"0x{addr + i:012X}   "
            hex_part1 = " ".join(f"{b:02X}" for b in chunk[:8])
            hex_part2 = " ".join(f"{b:02X}" for b in chunk[8:])
            hex_full = f"{hex_part1:<23}  {hex_part2:<23}   "
            ascii_text = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            self.txt_hex.insert(tk.END, line_addr, "offset")
            self.txt_hex.insert(tk.END, hex_full, "hexbyte")
            self.txt_hex.insert(tk.END, f"{ascii_text}\n", "asciitext")
        self.txt_decoded.delete("1.0", tk.END)
        extracted_strings = []
        cur_str = []
        for b in data:
            if 32 <= b <= 126:
                cur_str.append(chr(b))
            else:
                if len(cur_str) >= 3:
                    extracted_strings.append("".join(cur_str))
                cur_str.clear()
        if len(cur_str) >= 3:
            extracted_strings.append("".join(cur_str))
        if extracted_strings:
            self.txt_decoded.insert(tk.END, "=== STRINGHE & TESTI RICONOSCIUTI NEL BUFFER (ASCII/UTF-8) ===\n\n")
            for idx, s in enumerate(extracted_strings, 1):
                self.txt_decoded.insert(tk.END, f"[{idx:02d}] {s}\n")
        else:
            self.txt_decoded.insert(tk.END, "Nessuna stringa leggibile trovata in questo blocco binario puro.\n")
        self.txt_struct.delete("1.0", tk.END)
        header_magic = data[:4]
        magic_desc = "Sconosciuto / Dati Generici"
        if header_magic.startswith(b"DDS "):
            magic_desc = "🎨 Microsoft DirectDraw Surface (Texture DDS DXGI)"
        elif header_magic.startswith(b"\x89PNG"):
            magic_desc = "🎨 Portable Network Graphics (Immagine PNG)"
        elif header_magic.startswith(b"CPK"):
            magic_desc = "📦 CriWare CPK Container"
        elif header_magic.startswith(b"PK\x03\x04"):
            magic_desc = "📦 ZIP / Unreal Engine PAK Signature"
        elif header_magic.startswith(b"OggS"):
            magic_desc = "🔊 Audio OGG Vorbis"
        elif header_magic.startswith(b"RIFF"):
            magic_desc = "🔊 Audio RIFF WAV"
        elif b"/Game/" in data:
            magic_desc = "📐 Unreal Engine 4 Object Package / Asset Ref"
        struct_info = [
            "==================================================================",
            "                   INFORMAZIONI STRUTTURA ASSET                  ",
            "==================================================================",
            f"• Nome / Percorso: {path or 'Dato Dinamico RAM'}",
            f"• Categoria:       {cat or 'Buffer Dinamico'}",
            f"• Base Indirizzo:  0x{addr:012X}",
            f"• Buffer Letto:    {len(data)} Bytes",
            f"• Magic Header:    {header_magic.hex().upper()} ({magic_desc})",
            "------------------------------------------------------------------",
            "• Primo DWORD:     0x" + f"{int.from_bytes(data[:4], 'little'):08X}",
            "• Primo QWORD:     0x" + f"{int.from_bytes(data[:8], 'little'):016X}",
            "• Permessi RAM:    PAGE_READWRITE (Heap Dinamico)",
            "=================================================================="
        ]
        self.txt_struct.insert(tk.END, "\n".join(struct_info))
        decoded_img, img_info = self.try_decode_real_texture(addr, path, data)
        self.render_decoded_texture_image(decoded_img, img_info)
    def render_decoded_texture_image(self, decoded_img, img_info):
        self.canvas_preview.delete("all")
        self._preview_photo_ref = None
        self.current_decoded_image = decoded_img
        cw = self.canvas_preview.winfo_width()
        ch = self.canvas_preview.winfo_height()
        if cw <= 1:
            cw = 460
        if ch <= 1:
            ch = 300
        cx = cw // 2
        cy = ch // 2
        if decoded_img is not None:
            orig_w, orig_h = decoded_img.size
            max_w = max(50, cw - 40)
            max_h = max(50, ch - 80)
            scale = min(max_w / orig_w, max_h / orig_h, 1.0)
            new_w = max(1, int(orig_w * scale))
            new_h = max(1, int(orig_h * scale))
            resample_mode = getattr(Image, "Resampling", None)
            resample_filter = resample_mode.LANCZOS if resample_mode else Image.ANTIALIAS
            resized = decoded_img.resize((new_w, new_h), resample_filter)
            self.canvas_preview.create_rectangle(cx - new_w//2 - 2, cy - new_h//2 - 2, cx + new_w//2 + 2, cy + new_h//2 + 2, fill="#181824", outline="#38bdf8", width=2)
            self._preview_photo_ref = ImageTk.PhotoImage(resized)
            self.canvas_preview.create_image(cx, cy, image=self._preview_photo_ref, anchor="center")
            self.canvas_preview.create_text(cx, max(cy + new_h//2 + 20, ch - 25), text=f"✅ {img_info}", fill="#38bdf8", font=("Segoe UI", 10, "bold"))
            self.sub_notebook.tab(2, text="🖼️ Anteprima Texture (Attiva)")
            self.lbl_tex_status.config(text=f"✅ {img_info} | Pronto per Iniezione in RAM o Salvataggio LiveCPK", fg="#4ade80")
        else:
            card_w = min(420, cw - 30)
            card_h = 170
            self.canvas_preview.create_rectangle(cx - card_w//2, cy - card_h//2, cx + card_w//2, cy + card_h//2, fill="#14141e", outline="#3b82f6", width=2)
            self.canvas_preview.create_text(cx, cy - 55, text="🎮 Descrittore Texture Rilevato in Memoria", fill="#38bdf8", font=("Segoe UI", 11, "bold"))
            p_display = self.current_asset_path if len(self.current_asset_path) <= 45 else "..." + self.current_asset_path[-42:]
            self.canvas_preview.create_text(cx, cy - 30, text=f"• Percorso Asset: {p_display or 'Dato Dinamico RAM'}", fill="#fbbf24", font=("Segoe UI", 9, "bold"))
            addr_txt = f"0x{self.current_hex_addr:012X}" if self.current_hex_addr else "N/D"
            self.canvas_preview.create_text(cx, cy - 10, text=f"• Indirizzo RAM: {addr_txt} (Buffer Attivo)", fill="#a5b4fc", font=("Consolas", 10))
            self.canvas_preview.create_text(cx, cy + 12, text="🟢 Descrittore Pronto per Sostituzione & Iniezione Live", fill="#4ade80", font=("Segoe UI", 9, "bold"))
            self.canvas_preview.create_text(cx, cy + 45, text="👉 Clicca '📁 Sfoglia Texture' per caricare un PNG/DDS sostitutivo,\npoi premi '🚀 INIETTA IN SIDER' per renderlo attivo nel gioco in modo sicuro al 100%!", fill="#9ca3af", font=("Segoe UI", 8), justify="center")
            self.sub_notebook.tab(2, text="🖼️ Anteprima Texture (Pronta)")
            self.lbl_tex_status.config(text=f"📌 Descrittore: {p_display or addr_txt} | Clicca '📁 Sfoglia Texture' per scegliere l'immagine sostitutiva", fg="#fbbf24")
    def browse_and_load_texture_file(self):
        file_path = filedialog.askopenfilename(
            title="Seleziona File Immagine / Texture Sostitutiva",
            filetypes=[
                ("Tutti i formati supportati", "*.png;*.dds;*.bmp;*.jpg;*.jpeg;*.tga;*.webp"),
                ("Immagini PNG", "*.png"),
                ("Texture DirectX DDS", "*.dds"),
                ("Bitmap BMP", "*.bmp"),
                ("Tutti i file", "*.*")
            ]
        )
        if not file_path:
            return
        try:
            with open(file_path, "rb") as f:
                raw_bytes = f.read()
            try:
                im = Image.open(io.BytesIO(raw_bytes))
                im.load()
            except Exception:
                decomp = native_rust_unpack_wesys(raw_bytes)
                im = Image.open(io.BytesIO(decomp))
                im.load()
            self.current_replacement_file = file_path
            self.lbl_hex_asset_name.config(text=f"Asset: {os.path.basename(file_path)}")
            self.render_decoded_texture_image(im, f"Texture Sostitutiva Caricata: {os.path.basename(file_path)} ({im.format} {im.size[0]}x{im.size[1]} {im.mode})")
            self.sub_notebook.select(2)
        except Exception as e:
            messagebox.showerror(self.t("title"), f"Impossibile aprire il file immagine selezionato: {e}")
    def redirect_texture_path_live_ram(self):
        if not self.current_hex_addr:
            messagebox.showinfo(self.t("title"), "Seleziona prima un asset o un indirizzo RAM dal Live Sniffer!")
            return
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        from tkinter import simpledialog
        new_path = simpledialog.askstring(
            self.t("title"),
            "Inserisci il nuovo percorso interno dell'asset da reindirizzare in RAM:\n(es. /Game/Characters/u0001/Kit_01)",
            initialvalue=self.current_asset_path
        )
        if not new_path:
            return
        target_addr = self.current_hex_addr
        raw_str = new_path.encode("latin-1") + b"\x00"
        if self.engine.write_bytes_safe(target_addr, raw_str):
            messagebox.showinfo(
                self.t("title"),
                f"✅ Percorso Asset reindirizzato con successo in RAM!\n\n"
                f"• Nuovo Percorso: {new_path}\n"
                f"• Indirizzo RAM: 0x{target_addr:012X}\n\n"
                f"Il gioco caricherà il nuovo asset al prossimo caricamento senza rischio di crash."
            )
            self.load_visual_and_hex_from_address(target_addr, new_path, self.current_asset_cat)
        else:
            messagebox.showerror(self.t("title"), f"Impossibile scrivere all'indirizzo 0x{target_addr:012X}.\nVerifica che eFootball sia avviato.")
    def save_texture_to_livecpk(self):
        if not self.current_asset_path:
            messagebox.showinfo(self.t("title"), "Seleziona prima un asset dal Live Sniffer per determinare il percorso corretto!")
            return
        if not self.current_replacement_file or not os.path.exists(self.current_replacement_file):
            self.browse_and_load_texture_file()
            if not self.current_replacement_file or not os.path.exists(self.current_replacement_file):
                return
        try:
            clean_rel = self.current_asset_path.replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
            if clean_rel.lower().startswith("game" + os.sep):
                clean_rel = clean_rel[5:]
            mod_root = os.path.join(self.content_dir, "Live_Textures")
            dest_file = os.path.join(mod_root, clean_rel)
            os.makedirs(os.path.dirname(dest_file), exist_ok=True)
            shutil.copy2(self.current_replacement_file, dest_file)
            if os.path.exists(self.sider_ini_path):
                with open(self.sider_ini_path, "r", encoding="utf-8", errors="ignore") as f:
                    ini_content = f.read()
                entry = 'cpk.root = ".\\content\\Live_Textures"'
                if entry not in ini_content:
                    with open(self.sider_ini_path, "a", encoding="utf-8") as f:
                        f.write(f"\n{entry}\n")
            messagebox.showinfo(
                self.t("title"),
                f"✅ Texture salvata con successo in Sider LiveCPK!\n\n"
                f"• Destinazione: {dest_file}\n"
                f"• Pacchetto Mod: content\\Live_Textures\n"
                f"• Registrato in: sider.ini\n\n"
                f"La mod è attiva e sostituirà la texture originale ogni volta che il gioco la richiede."
            )
        except Exception as e:
            messagebox.showerror(self.t("title"), f"Errore durante il salvataggio in LiveCPK: {e}")
    def deep_scan_surrounding_ram_texture(self):
        if not self.current_hex_addr:
            messagebox.showinfo(self.t("title"), "Seleziona prima un indirizzo RAM da ispezionare!")
            return
        if not self.engine.check_alive():
            messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
            return
        addr = self.current_hex_addr
        scan_start = max(0x100000000, addr - 1024 * 1024 * 2)
        scan_size = 1024 * 1024 * 4
        chunk = self.engine.read_bytes(scan_start, scan_size)
        if not chunk:
            messagebox.showwarning(self.t("title"), "Memoria RAM non accessibile a questo indirizzo.")
            return
        im, desc = self._scan_buffer_for_image(chunk, scan_start)
        if im is not None:
            self.render_decoded_texture_image(im, desc)
            self.sub_notebook.select(2)
            messagebox.showinfo(self.t("title"), f"Trovata texture in memoria:\n{desc}")
        else:
            messagebox.showinfo(self.t("title"), "Nessun header di texture (DDS/PNG/BMP) trovato nei 4 MB circostanti.")
    def export_current_texture(self):
        if self.current_decoded_image is None:
            messagebox.showinfo(self.t("title"), "Nessuna immagine renderizzata da esportare al momento.")
            return
        save_path = filedialog.asksaveasfilename(
            title="Salva Immagine / Texture Catturata",
            defaultextension=".png",
            filetypes=[("Immagine PNG", "*.png"), ("Bitmap BMP", "*.bmp"), ("Tutti i file", "*.*")]
        )
        if not save_path:
            return
        try:
            self.current_decoded_image.save(save_path)
            messagebox.showinfo(self.t("title"), f"Immagine salvata con successo in:\n{save_path}")
        except Exception as e:
            messagebox.showerror(self.t("title"), f"Errore durante il salvataggio: {e}")
    def _scan_buffer_for_image(self, chunk, base_offset=0):
        png_idx = chunk.find(b"\x89PNG\r\n\x1a\n")
        if png_idx != -1:
            try:
                im = Image.open(io.BytesIO(chunk[png_idx:]))
                im.load()
                addr_str = f" @ 0x{base_offset + png_idx:012X}" if base_offset else ""
                return im, f"Immagine PNG in Memoria ({im.size[0]}x{im.size[1]}, {im.mode}){addr_str}"
            except Exception:
                pass
        dds_idx = chunk.find(b"DDS ")
        if dds_idx != -1:
            try:
                im = Image.open(io.BytesIO(chunk[dds_idx:]))
                im.load()
                addr_str = f" @ 0x{base_offset + dds_idx:012X}" if base_offset else ""
                return im, f"Texture DirectX DDS in Memoria ({im.size[0]}x{im.size[1]}, {im.mode}){addr_str}"
            except Exception:
                try:
                    h_size, flags, height, width = struct.unpack_from("<IIII", chunk, dds_idx + 4)
                    fourcc = chunk[dds_idx+84:dds_idx+88].decode("ascii", errors="ignore").strip()
                    return None, f"Texture DirectX DDS ({width}x{height}, Formato: {fourcc or 'DXGI'})"
                except Exception:
                    pass
        bmp_idx = chunk.find(b"BM")
        if bmp_idx != -1 and bmp_idx + 14 < len(chunk):
            try:
                im = Image.open(io.BytesIO(chunk[bmp_idx:]))
                im.load()
                return im, f"Bitmap BMP in Memoria ({im.size[0]}x{im.size[1]}, {im.mode})"
            except Exception:
                pass
        jpg_idx = chunk.find(b"\xff\xd8\xff")
        if jpg_idx != -1:
            try:
                im = Image.open(io.BytesIO(chunk[jpg_idx:]))
                im.load()
                return im, f"Immagine JPEG in Memoria ({im.size[0]}x{im.size[1]}, {im.mode})"
            except Exception:
                pass
        return None, ""
    def try_decode_real_texture(self, addr, path, initial_data):
        if initial_data:
            im, desc = self._scan_buffer_for_image(initial_data, addr)
            if im is not None:
                return im, desc
        if addr and self.engine.check_alive():
            scan_start = max(0x100000000, addr - 131072)
            scan_buf = self.engine.read_bytes(scan_start, 1024 * 1024)
            if scan_buf:
                im, desc = self._scan_buffer_for_image(scan_buf, scan_start)
                if im is not None:
                    return im, desc
        if path:
            roots = [
                r"A:\Mod Efootball",
                self.content_dir,
                self.sider_pkg_dir,
                self.base_dir,
                os.path.join(self.base_dir, "live_assets"),
                r"A:\SteamLibrary\steamapps\common\eFootball",
                r"A:\SteamLibrary\steamapps\common\eFootball\eFootball\Content",
                r"A:\Mod Efootball\extracted_evomod_all",
                r"A:\Mod Efootball\extracted_dt870_all",
            ]
            norm = path.replace("/", os.sep).replace("\\", os.sep).lstrip(os.sep)
            candidates = [path] if os.path.isabs(path) else []
            for r in roots:
                candidates.append(os.path.join(r, norm))
                candidates.append(os.path.join(r, "content", norm))
                candidates.append(os.path.join(r, "live_assets", norm))
            bname = os.path.basename(path)
            if bname:
                for r in roots:
                    candidates.append(os.path.join(r, bname))
                    candidates.append(os.path.join(r, "textures", bname))
                    candidates.append(os.path.join(r, "kits", bname))
            for cand in candidates:
                if cand and os.path.isfile(cand):
                    try:
                        with open(cand, "rb") as f:
                            raw = f.read()
                        try:
                            im = Image.open(io.BytesIO(raw))
                            im.load()
                            return im, f"File su Disco: {os.path.basename(cand)} ({im.format} {im.size[0]}x{im.size[1]} {im.mode})"
                        except Exception:
                            decomp = native_rust_unpack_wesys(raw)
                            if decomp and decomp != raw:
                                im = Image.open(io.BytesIO(decomp))
                                im.load()
                                return im, f"Asset WESYS Decodificato: {os.path.basename(cand)} ({im.format} {im.size[0]}x{im.size[1]} {im.mode})"
                    except Exception:
                        pass
        return None, ""
    def write_hex_string_to_ram(self):
        if not self.current_hex_addr:
            messagebox.showinfo(self.t("title"), "Seleziona prima un indirizzo da ispezionare!")
            return
        new_val = self.ent_hex_write.get().strip()
        if not new_val:
            return
        raw = new_val.encode("latin-1")
        if self.engine.write_bytes_safe(self.current_hex_addr, raw):
            messagebox.showinfo(self.t("title"), f"Byte scritti con successo all'indirizzo 0x{self.current_hex_addr:012X}!")
            self.load_visual_and_hex_from_address(self.current_hex_addr, self.current_asset_path, self.current_asset_cat)
        else:
            messagebox.showerror(self.t("title"), "Errore durante la scrittura in memoria RAM.")
    def setup_tab_search_ui(self):
        bar = tk.Frame(self.tab_search, bg="#1f1f2b", padx=14, pady=12)
        bar.pack(fill=tk.X, padx=12, pady=10)
        self.lbl_search_prompt = tk.Label(bar, text=self.t("lbl_search_prompt"), font=("Segoe UI", 11, "bold"), fg="#ffffff", bg="#1f1f2b")
        self.lbl_search_prompt.pack(side=tk.LEFT, padx=5)
        self.ent_search = tk.Entry(bar, font=("Segoe UI", 12), width=28, bg="#111116", fg="#ffffff", insertbackground="white", relief=tk.FLAT)
        self.ent_search.pack(side=tk.LEFT, padx=10, ipady=4)
        self.ent_search.insert(0, "Piemonte")
        self.ent_search.bind("<Return>", lambda e: self.start_search())
        self.btn_search = tk.Button(bar, text=self.t("btn_search"), font=("Segoe UI", 11, "bold"), bg="#0284c7", fg="white", relief=tk.FLAT, padx=16, pady=4, command=self.start_search)
        self.btn_search.pack(side=tk.LEFT, padx=6)
        self.btn_stop = tk.Button(bar, text=self.t("btn_stop_search"), font=("Segoe UI", 10), bg="#ef4444", fg="white", relief=tk.FLAT, padx=10, pady=4, state=tk.DISABLED, command=self.stop_search)
        self.btn_stop.pack(side=tk.LEFT, padx=4)
        self.var_case = tk.BooleanVar(value=False)
        self.chk_case = tk.Checkbutton(bar, text=self.t("chk_case"), variable=self.var_case, fg="#d1d5db", bg="#1f1f2b", selectcolor="#0284c7", activebackground="#1f1f2b")
        self.chk_case.pack(side=tk.LEFT, padx=8)
        self.lbl_search_info = tk.Label(bar, text=self.t("search_hint"), font=("Segoe UI", 9, "italic"), fg="#9ca3af", bg="#1f1f2b")
        self.lbl_search_info.pack(side=tk.RIGHT, padx=5)
        table_frame = tk.Frame(self.tab_search, bg="#16161d")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=5)
        cols = ("addr", "enc", "cur", "type", "size")
        self.tree_res = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree_res.heading("addr", text=self.t("col_addr"), command=lambda: sort_treeview_column(self.tree_res, "addr", False))
        self.tree_res.heading("enc", text=self.t("col_encoding"), command=lambda: sort_treeview_column(self.tree_res, "enc", False))
        self.tree_res.heading("cur", text=self.t("col_path"), command=lambda: sort_treeview_column(self.tree_res, "cur", False))
        self.tree_res.heading("type", text=self.t("col_type"), command=lambda: sort_treeview_column(self.tree_res, "type", False))
        self.tree_res.heading("size", text=self.t("col_size"), command=lambda: sort_treeview_column(self.tree_res, "size", False))
        self.tree_res.column("addr", width=220, anchor="center")
        self.tree_res.column("enc", width=100, anchor="center")
        self.tree_res.column("cur", width=380, anchor="w")
        self.tree_res.column("type", width=220, anchor="center")
        self.tree_res.column("size", width=120, anchor="center")
        scroll_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree_res.yview)
        self.tree_res.configure(yscrollcommand=scroll_y.set)
        self.tree_res.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_res.bind("<<TreeviewSelect>>", self.on_select_result_row)
        self.tree_res.bind("<Double-1>", lambda e: self.inject_selected())
        inj_frame = tk.Frame(self.tab_search, bg="#1a1a24", padx=14, pady=12)
        inj_frame.pack(fill=tk.X, padx=12, pady=10)
        self.lbl_new_val = tk.Label(inj_frame, text=self.t("lbl_new_val"), font=("Segoe UI", 11, "bold"), fg="#38bdf8", bg="#1a1a24")
        self.lbl_new_val.pack(side=tk.LEFT, padx=5)
        self.ent_inject = tk.Entry(inj_frame, font=("Segoe UI", 12), width=28, bg="#111116", fg="#ffffff", insertbackground="white", relief=tk.FLAT)
        self.ent_inject.pack(side=tk.LEFT, padx=10, ipady=4)
        self.ent_inject.insert(0, "Juventus FC")
        self.btn_inject_one = tk.Button(inj_frame, text=self.t("btn_inj_sel"), font=("Segoe UI", 11, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=16, pady=4, command=self.inject_selected)
        self.btn_inject_one.pack(side=tk.LEFT, padx=6)
        self.btn_inject_ui = tk.Button(inj_frame, text=self.t("btn_inj_smart"), font=("Segoe UI", 10, "bold"), bg="#6366f1", fg="white", relief=tk.FLAT, padx=14, pady=4, command=self.inject_all_ui_results)
        self.btn_inject_ui.pack(side=tk.LEFT, padx=6)
    def start_search(self):
        query = self.ent_search.get().strip()
        if not query:
            return
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        self.is_searching = True
        self.search_stop_event.clear()
        self.btn_search.config(state=tk.DISABLED)
        self.btn_stop.config(state=tk.NORMAL)
        self.tree_res.delete(*self.tree_res.get_children())
        self.search_results = []
        self.lbl_search_info.config(text=f"Scanning RAM for '{query}'...")
        threading.Thread(target=self._search_worker, args=(query, self.var_case.get()), daemon=True).start()
    def stop_search(self):
        self.search_stop_event.set()
        self.btn_stop.config(state=tk.DISABLED)
        self.btn_search.config(state=tk.NORMAL)
    def _search_worker(self, query, case_sensitive):
        t0 = time.time()
        batch = []
        try:
            for item in self.engine.scan_memory_generator(query, case_sensitive=case_sensitive, stop_event=self.search_stop_event):
                batch.append(item)
                self.search_results.append(item)
                if len(batch) >= 15:
                    self.root.after(0, self._append_batch_results, batch.copy())
                    batch.clear()
            if batch:
                self.root.after(0, self._append_batch_results, batch.copy())
        except Exception:
            logger.exception("Errore durante l'esecuzione della ricerca in RAM per '%s'", query)
        finally:
            elapsed = (time.time() - t0) * 1000
            self.root.after(0, self._search_finished, elapsed)
    def _append_batch_results(self, batch):
        for item in batch:
            addr_str = f"0x{item['address']:012X}"
            reg_str = f"{item['region_size'] / 1024:.0f} KB"
            type_desc = self.t("safe_ui") if item["is_ui_display"] else (self.t("internal_key") if not item["is_code"] else self.t("code_sec"))
            self.tree_res.insert("", tk.END, values=(addr_str, item["encoding"], item["current"], type_desc, reg_str))
    def _search_finished(self, elapsed_ms):
        self.is_searching = False
        self.btn_search.config(state=tk.NORMAL)
        self.btn_stop.config(state=tk.DISABLED)
        tot = len(self.search_results)
        ui_count = sum(1 for x in self.search_results if x["is_ui_display"])
        self.lbl_search_info.config(text=f"{tot} results ({ui_count} safe UI strings) in {elapsed_ms:.0f} ms.")
    def on_select_result_row(self, event):
        sel = self.tree_res.selection()
        if not sel:
            return
        idx = self.tree_res.index(sel[0])
        if 0 <= idx < len(self.search_results):
            item = self.search_results[idx]
            cur = item["current"].strip()
            if cur:
                self.ent_inject.delete(0, tk.END)
                self.ent_inject.insert(0, cur)
    def inject_selected(self):
        sel = self.tree_res.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        idx = self.tree_res.index(sel[0])
        item = self.search_results[idx]
        addr = item["address"]
        enc = item["encoding"]
        orig_full = item["current"].strip()
        flen = max(item["matched_len"], len(orig_full))
        new_val = self.ent_inject.get()
        if not new_val:
            return
        if enc == "UTF-16":
            raw = new_val.encode("utf-16le")
            if len(raw) < flen * 2:
                raw = raw + b"\x00\x00" * (flen - len(new_val))
            else:
                raw = raw[:flen * 2]
        else:
            raw = new_val.encode("latin-1")
            if len(raw) < flen:
                raw = raw + b" " * (flen - len(raw))
            else:
                raw = raw[:flen]
        if self.engine.write_bytes_safe(addr, raw):
            self.tree_res.set(sel[0], "cur", f"✅ {new_val}")
            messagebox.showinfo(self.t("title"), f"{self.t('msg_success')}\nAddress: 0x{addr:012X}")
        else:
            messagebox.showerror(self.t("title"), self.t("msg_err"))
    def inject_all_ui_results(self):
        if not self.search_results:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        new_val = self.ent_inject.get().strip()
        if not new_val:
            return
        self.btn_inject_ui.config(state=tk.DISABLED, text="⏳ Iniezione...")
        def worker():
            success = 0
            items_to_inject = [it for it in self.search_results if it["is_ui_display"]]
            for i, item in enumerate(items_to_inject):
                addr = item["address"]
                enc = item["encoding"]
                orig_full = item["current"].strip()
                flen = max(item["matched_len"], len(orig_full))
                if enc == "UTF-16":
                    raw = new_val.encode("utf-16le")
                    if len(raw) < flen * 2:
                        raw = raw + b"\x00\x00" * (flen - len(new_val))
                    else:
                        raw = raw[:flen * 2]
                else:
                    raw = new_val.encode("latin-1")
                    if len(raw) < flen:
                        raw = raw + b" " * (flen - len(raw))
                    else:
                        raw = raw[:flen]
                if self.engine.write_bytes_safe(addr, raw):
                    success += 1
            def on_finish():
                self.btn_inject_ui.config(state=tk.NORMAL, text=self.t("btn_inj_smart"))
                messagebox.showinfo(self.t("title"), f"{self.t('msg_success')}\nIniettate con successo: {success} stringhe UI.")
            self.root.after(0, on_finish)
        threading.Thread(target=worker, daemon=True).start()
    def setup_tab_mods_ui(self):
        toolbar = tk.Frame(self.tab_mods, bg="#1f1f2b", padx=14, pady=10)
        toolbar.pack(fill=tk.X, padx=12, pady=10)
        self.btn_zip = tk.Button(toolbar, text=self.t("btn_install_zip"), font=("Segoe UI", 11, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=14, pady=5, command=self.install_mod_from_zip)
        self.btn_zip.pack(side=tk.LEFT, padx=6)
        self.btn_folder = tk.Button(toolbar, text=self.t("btn_open_folder"), font=("Segoe UI", 10), bg="#374151", fg="white", relief=tk.FLAT, padx=12, pady=5, command=self.open_mods_folder)
        self.btn_folder.pack(side=tk.LEFT, padx=6)
        self.btn_delete = tk.Button(toolbar, text=self.t("btn_del_mod"), font=("Segoe UI", 10), bg="#ef4444", fg="white", relief=tk.FLAT, padx=12, pady=5, command=self.delete_selected_mod)
        self.btn_delete.pack(side=tk.LEFT, padx=6)
        self.btn_reload = tk.Button(toolbar, text=self.t("btn_reload_mods"), font=("Segoe UI", 10), bg="#0284c7", fg="white", relief=tk.FLAT, padx=12, pady=5, command=self.load_installed_mods)
        self.btn_reload.pack(side=tk.RIGHT, padx=6)
        table_frame = tk.Frame(self.tab_mods, bg="#16161d")
        table_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=5)
        cols = ("enabled", "name", "category", "author", "folder")
        self.tree_mods = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse")
        self.tree_mods.heading("enabled", text=self.t("col_status"), command=lambda: sort_treeview_column(self.tree_mods, "enabled", False))
        self.tree_mods.heading("name", text=self.t("col_mod_name"), command=lambda: sort_treeview_column(self.tree_mods, "name", False))
        self.tree_mods.heading("category", text=self.t("col_mod_cat"), command=lambda: sort_treeview_column(self.tree_mods, "category", False))
        self.tree_mods.heading("author", text=self.t("col_author"), command=lambda: sort_treeview_column(self.tree_mods, "author", False))
        self.tree_mods.heading("folder", text=self.t("col_folder"), command=lambda: sort_treeview_column(self.tree_mods, "folder", False))
        self.tree_mods.column("enabled", width=120, anchor="center")
        self.tree_mods.column("name", width=280, anchor="w")
        self.tree_mods.column("category", width=180, anchor="center")
        self.tree_mods.column("author", width=200, anchor="w")
        self.tree_mods.column("folder", width=260, anchor="w")
        scroll_y = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree_mods.yview)
        self.tree_mods.configure(yscrollcommand=scroll_y.set)
        self.tree_mods.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_y.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_mods.bind("<Double-1>", lambda e: self.toggle_selected_mod_state())
        bot_bar = tk.Frame(self.tab_mods, bg="#1a1a24", padx=14, pady=10)
        bot_bar.pack(fill=tk.X, padx=12, pady=10)
        self.btn_toggle = tk.Button(bot_bar, text=self.t("btn_toggle_mod"), font=("Segoe UI", 10, "bold"), bg="#f59e0b", fg="black", relief=tk.FLAT, padx=14, pady=5, command=self.toggle_selected_mod_state)
        self.btn_toggle.pack(side=tk.LEFT, padx=5)
        self.btn_apply_live = tk.Button(bot_bar, text=self.t("btn_apply_mod_live"), font=("Segoe UI", 10, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=14, pady=5, command=self.apply_mod_live_to_ram)
        self.btn_apply_live.pack(side=tk.LEFT, padx=5)
        self.btn_diag = tk.Button(bot_bar, text="🔍 DIAGNOSTICA LIVECPK", font=("Segoe UI", 10, "bold"), bg="#6366f1", fg="white", relief=tk.FLAT, padx=14, pady=5, command=self.diagnostica_livecpk)
        self.btn_diag.pack(side=tk.LEFT, padx=5)
        self.btn_sync = tk.Button(bot_bar, text=self.t("btn_sync_game"), font=("Segoe UI", 10, "bold"), bg="#3b82f6", fg="white", relief=tk.FLAT, padx=16, pady=5, command=self.sync_sider_to_game)
        self.btn_sync.pack(side=tk.RIGHT, padx=5)
    def ensure_content_root_registered(self):
        """Assicura che la root 'content' sia registrata in sider.ini"""
        if not os.path.exists(self.sider_ini_path):
            self.save_sider_ini()
            return
        try:
            has_content = False
            with open(self.sider_ini_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    s = line.strip()
                    if s.startswith("cpk.root") and "=" in s:
                        v = s.split("=", 1)[1].strip().strip('"').strip('\'')
                        if v in ["content", ".\\content", "./content"]:
                            has_content = True
                            break
            if not has_content:
                logger.info("Auto-registrazione automatica di cpk.root = 'content' in sider.ini")
                self.save_sider_ini()
                self.db_log("Auto-registrata root 'content' in sider.ini")
        except Exception as e:
            logger.exception("Errore durante verifica registrazione root content in sider.ini: %s", e)
    def diagnostica_livecpk(self):
        self.run_livecpk_diagnostics()
    def run_livecpk_diagnostics(self):
        active_roots = []
        disabled_roots = []
        has_content_root = False
        if os.path.exists(self.sider_ini_path):
            with open(self.sider_ini_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line_s = line.strip()
                    if line_s.startswith("cpk.root"):
                        if "=" in line_s:
                            val = line_s.split("=", 1)[1].strip().strip('"').strip('\'')
                            active_roots.append(val)
                            if val in ["content", ".\\content", "./content"]:
                                has_content_root = True
                    elif line_s.startswith(";") and "cpk.root" in line_s:
                        if "=" in line_s:
                            val = line_s.split("=", 1)[1].strip().strip('"').strip('\'')
                            disabled_roots.append(val)
        content_exists = os.path.exists(self.content_dir)
        total_files = 0
        extensions = {}
        indexed_files = []
        if content_exists:
            for root, _, files in os.walk(self.content_dir):
                for file in files:
                    total_files += 1
                    ext = os.path.splitext(file)[1].lower() or ".bin"
                    extensions[ext] = extensions.get(ext, 0) + 1
                    rel_p = os.path.relpath(os.path.join(root, file), self.base_dir)
                    indexed_files.append(rel_p)
        sample_tests = [
            "common/etc/pesdb/Team.bin",
            "common/etc/pesdb/PlayerAssignment.bin",
            "character/face/diffuse.uasset",
            "textures/turf/grass_color.png"
        ]
        lookup_results = []
        for test_path in sample_tests:
            norm_test = test_path.replace("/", "\\").lower()
            matched = None
            for idx_p in indexed_files:
                norm_idx = idx_p.replace("/", "\\").lower()
                if norm_test in norm_idx or os.path.basename(norm_test) == os.path.basename(norm_idx):
                    matched = idx_p
                    break
            status_symbol = "✅ RISOLTO" if matched else "⚠️ NON PRESENTE"
            lookup_results.append(f"• '{test_path}': {status_symbol}" + (f" ➔ {matched}" if matched else ""))
        ext_str = ", ".join(f"{k}: {v}" for k, v in sorted(extensions.items())) if extensions else "Nessun file trovato"
        suggestions = []
        if not content_exists:
            suggestions.append("⚠️ La cartella 'content/' non esiste. Creala e inserisci le tue mod o texture.")
        elif total_files == 0:
            suggestions.append("ℹ️ La cartella 'content/' è vuota. Inserisci texture (.uasset, .png) o database per attivarne l'override.")
        if not has_content_root:
            suggestions.append("💡 'cpk.root = \"content\"' non era esplicitamente presente in sider.ini. Il Sider lo registrerà automaticamente al prossimo salvataggio.")
        else:
            suggestions.append("✅ 'content/' è registrata correttamente come root LiveCPK in sider.ini.")
        diag_msg = (
            f"=== 🛰️ DIAGNOSTICA LIVECPK VFS ===\n\n"
            f"📁 Cartella Base Content: {self.content_dir} ({'Presente' if content_exists else 'NON TROVATA'})\n"
            f"📊 File Totali nel VFS: {total_files:,d}\n"
            f"🧩 Tipologie file: {ext_str}\n\n"
            f"📌 Root LiveCPK Attive ({len(active_roots)}):\n" + ("\n".join(f"  [+] {r}" for r in active_roots) if active_roots else "  (Nessuna)") + "\n\n"
            f"🔒 Root Disabilitate ({len(disabled_roots)}):\n" + ("\n".join(f"  [-] {r}" for r in disabled_roots) if disabled_roots else "  (Nessuna)") + "\n\n"
            f"🔬 Test Simulazione Lookup VFS (CreateFileW):\n" + "\n".join(lookup_results) + "\n\n"
            f"📋 Suggerimenti & Stato:\n" + "\n".join(f"• {s}" for s in suggestions)
        )
        logger.info("LiveCPK Diagnostics eseguita: %d file in content, %d root attive", total_files, len(active_roots))
        messagebox.showinfo("Diagnostica LiveCPK", diag_msg)
    def load_installed_mods(self):
        self.tree_mods.delete(*self.tree_mods.get_children())
        self.installed_mods = []
        if not os.path.exists(self.content_dir):
            return
        active_roots = set()
        if os.path.exists(self.sider_ini_path):
            with open(self.sider_ini_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("cpk.root"):
                        if "=" in line:
                            _, val = line.split("=", 1)
                            raw = val.strip().strip('"').strip('\'')
                            folder_name = os.path.basename(raw.replace("/", "\\"))
                            active_roots.add(folder_name)
        for entry in os.listdir(self.content_dir):
            full_path = os.path.join(self.content_dir, entry)
            if os.path.isdir(full_path):
                mod_name = entry
                category = "General"
                author = "Modder"
                version = "1.0"
                mod_ini = os.path.join(full_path, "mod.ini")
                if os.path.exists(mod_ini):
                    with open(mod_ini, "r", encoding="utf-8", errors="ignore") as f:
                        for line in f:
                            line = line.strip()
                            if "=" in line:
                                k, v = line.split("=", 1)
                                k = k.strip().lower()
                                v = v.strip().strip('"')
                                if k == "name":
                                    mod_name = v
                                elif k == "category":
                                    category = v
                                elif k == "author":
                                    author = v
                                elif k == "version":
                                    version = v
                elif "turf" in entry.lower() or "st" in entry.lower():
                    category = "Stadium / Turf"
                elif "kit" in entry.lower():
                    category = "Kits"
                elif "name" in entry.lower() or "team" in entry.lower():
                    category = "Database"
                is_active = entry in active_roots
                status_str = self.t("mod_active") if is_active else self.t("mod_disabled")
                mod_data = {
                    "is_active": is_active,
                    "folder": entry,
                    "full_path": full_path,
                    "name": mod_name,
                    "category": category,
                    "author_ver": f"{author} (v{version})"
                }
                self.installed_mods.append(mod_data)
                self.tree_mods.insert("", tk.END, values=(
                    status_str,
                    mod_name,
                    category,
                    f"{author} (v{version})",
                    entry
                ))
    def toggle_selected_mod_state(self):
        sel = self.tree_mods.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        idx = self.tree_mods.index(sel[0])
        mod = self.installed_mods[idx]
        mod["is_active"] = not mod["is_active"]
        self.save_sider_ini()
        self.load_installed_mods()
    def save_sider_ini(self):
        existing_camera = {}
        existing_sider = {}
        if os.path.exists(self.sider_ini_path):
            cfg = configparser.ConfigParser(strict=False)
            try:
                cfg.read(self.sider_ini_path, encoding="utf-8")
                if cfg.has_section("camera"):
                    existing_camera = dict(cfg.items("camera"))
                if cfg.has_section("sider"):
                    existing_sider = dict(cfg.items("sider"))
            except Exception:
                pass
        lines = [
            "; ==============================================================================",
            "; Efootball Sider by Toriga - Master Configuration (sider.ini)",
            "; ==============================================================================",
            "",
            "[SETTINGS]",
            'mods_directory = "content"',
            "live_asset_loader = 1",
            "live_texture_override = 1",
            "live_mesh_override = 1",
            "live_database_override = 1",
            "",
            "[sider]",
            f"debug = {existing_sider.get('debug', '1')}",
            f"freecam = {existing_sider.get('freecam', '0')}",
            "",
            "[camera]",
            f"enabled = {1 if self.cam_enabled.get() else 0}",
            f"zoom = {self.cam_zoom.get():.2f}",
            f"height = {self.cam_height.get():.2f}",
            f"angle = {self.cam_angle.get():.2f}",
            f"fov = {self.cam_fov.get():.1f}",
            f"freecam_speed = {self.cam_freecam_speed.get():.1f}",
            "",
            "[LIVE_CPK]",
            'cpk.root = "content"'
        ]
        for mod in self.installed_mods:
            if mod["is_active"]:
                lines.append(f'cpk.root = "content\\{mod["folder"]}"')
            else:
                lines.append(f'; cpk.root = "content\\{mod["folder"]}"')
        with open(self.sider_ini_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        game_ini = os.path.join(self.game_bin_dir, "sider.ini")
        try:
            shutil.copy2(self.sider_ini_path, game_ini)
        except Exception:
            pass
    def install_mod_from_zip(self):
        zip_path = filedialog.askopenfilename(
            title=self.t("btn_install_zip"),
            filetypes=[("ZIP Archives", "*.zip"), ("All Files", "*.*")]
        )
        if not zip_path:
            return
        self.btn_zip.config(state=tk.DISABLED, text="⏳ Installazione...")
        def worker():
            try:
                with zipfile.ZipFile(zip_path, 'r') as z:
                    mod_name = os.path.splitext(os.path.basename(zip_path))[0]
                    target_folder = os.path.join(self.content_dir, mod_name)
                    os.makedirs(target_folder, exist_ok=True)
                    z.extractall(target_folder)
                def on_ok():
                    self.btn_zip.config(state=tk.NORMAL, text=self.t("btn_install_zip"))
                    self.load_installed_mods()
                    messagebox.showinfo(self.t("title"), f"Mod '{mod_name}' installata con successo in content/{mod_name}!")
                self.root.after(0, on_ok)
            except Exception as e:
                def on_err(err=e):
                    self.btn_zip.config(state=tk.NORMAL, text=self.t("btn_install_zip"))
                    messagebox.showerror(self.t("title"), f"Errore estrazione ZIP:\n{err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def delete_selected_mod(self):
        sel = self.tree_mods.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        idx = self.tree_mods.index(sel[0])
        mod = self.installed_mods[idx]
        confirm = messagebox.askyesno(self.t("title"), self.t("msg_confirm_del", name=mod['name']))
        if confirm:
            try:
                shutil.rmtree(mod['full_path'])
                self.load_installed_mods()
                self.save_sider_ini()
                messagebox.showinfo(self.t("title"), self.t("msg_success"))
            except Exception as e:
                messagebox.showerror(self.t("title"), f"Error:\n{e}")
    def open_mods_folder(self):
        if not os.path.exists(self.content_dir):
            os.makedirs(self.content_dir, exist_ok=True)
        os.startfile(self.content_dir)
    def sync_sider_to_game(self):
        if not os.path.exists(self.game_bin_dir):
            messagebox.showerror(self.t("title"), f"Game folder not found:\n{self.game_bin_dir}")
            return
        self.btn_sync.config(state=tk.DISABLED, text="⏳ Sincronizzazione...")
        def worker():
            try:
                src_dll = os.path.join(self.sider_pkg_dir, "dxgi.dll")
                if os.path.exists(src_dll):
                    try:
                        shutil.copy2(src_dll, os.path.join(self.game_bin_dir, "dxgi.dll"))
                    except Exception:
                        pass
                self.save_sider_ini()
                shutil.copy2(self.sider_ini_path, os.path.join(self.game_bin_dir, "sider.ini"))
                game_content = os.path.join(self.game_bin_dir, "content")
                if os.path.exists(game_content):
                    shutil.rmtree(game_content)
                shutil.copytree(self.content_dir, game_content)
                def on_ok():
                    self.btn_sync.config(state=tk.NORMAL, text=self.t("btn_sync_game"))
                    messagebox.showinfo(self.t("title"), self.t("msg_sync_ok"))
                self.root.after(0, on_ok)
            except Exception as e:
                def on_err(err=e):
                    self.btn_sync.config(state=tk.NORMAL, text=self.t("btn_sync_game"))
                    messagebox.showerror(self.t("title"), f"Sync error:\n{err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def setup_tab_db_ui(self):
        top_bar = tk.Frame(self.tab_db, bg="#1f1f2b", padx=14, pady=8)
        top_bar.pack(fill=tk.X, padx=12, pady=6)
        self.lbl_db_scan_title = tk.Label(top_bar, text=self.t("lbl_db_scan_title"), font=("Segoe UI", 11, "bold"), fg="#38bdf8", bg="#1f1f2b")
        self.lbl_db_scan_title.pack(side=tk.LEFT, padx=5)
        self.btn_db_scan = tk.Button(top_bar, text=self.t("btn_db_scan"), font=("Segoe UI", 10, "bold"), bg="#0284c7", fg="white", relief=tk.FLAT, padx=14, pady=4, command=self.scan_active_databases_ram)
        self.btn_db_scan.pack(side=tk.RIGHT, padx=5)
        table_frame = tk.Frame(self.tab_db, bg="#16161d")
        table_frame.pack(fill=tk.X, padx=12, pady=4)
        cols = ("addr", "name", "size", "status")
        self.tree_db = ttk.Treeview(table_frame, columns=cols, show="headings", selectmode="browse", height=4)
        self.tree_db.heading("addr", text=self.t("col_db_addr"), command=lambda: sort_treeview_column(self.tree_db, "addr", False))
        self.tree_db.heading("name", text=self.t("col_db_name"), command=lambda: sort_treeview_column(self.tree_db, "name", False))
        self.tree_db.heading("size", text=self.t("col_db_size"), command=lambda: sort_treeview_column(self.tree_db, "size", False))
        self.tree_db.heading("status", text=self.t("col_db_status"), command=lambda: sort_treeview_column(self.tree_db, "status", False))
        self.tree_db.column("addr", width=160, anchor="center")
        self.tree_db.column("name", width=420, anchor="w")
        self.tree_db.column("size", width=140, anchor="center")
        self.tree_db.column("status", width=120, anchor="center")
        scroll_db = ttk.Scrollbar(table_frame, orient=tk.VERTICAL, command=self.tree_db.yview)
        self.tree_db.configure(yscrollcommand=scroll_db.set)
        self.tree_db.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_db.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_db.bind("<Double-1>", lambda e: self.inspect_ram_db_in_hex())
        file_panel = tk.LabelFrame(self.tab_db, text=f" {self.t('lbl_db_file_sel')} ", font=("Segoe UI", 10, "bold"), fg="#38bdf8", bg="#181822", padx=12, pady=8)
        file_panel.pack(fill=tk.X, padx=12, pady=6)
        f_row = tk.Frame(file_panel, bg="#181822")
        f_row.pack(fill=tk.X, pady=3)
        self.ent_db_path = tk.Entry(f_row, font=("Consolas", 10), bg="#111116", fg="#ffffff", insertbackground="white")
        self.ent_db_path.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8), ipady=3)
        self.ent_db_path.insert(0, r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb\Team.bin")
        self.btn_db_browse = tk.Button(f_row, text=self.t("btn_db_browse"), font=("Segoe UI", 9, "bold"), bg="#374151", fg="white", relief=tk.FLAT, padx=12, pady=3, command=self.browse_db_file)
        self.btn_db_browse.pack(side=tk.RIGHT)
        p_row = tk.Frame(file_panel, bg="#181822")
        p_row.pack(fill=tk.X, pady=4)
        self.btn_preset_team = tk.Button(p_row, text="⚽ Team.bin", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#38bdf8", relief=tk.FLAT, padx=8, pady=3, command=lambda: self.set_preset_db("team"))
        self.btn_preset_team.pack(side=tk.LEFT, padx=3)
        self.btn_preset_assign = tk.Button(p_row, text="👥 PlayerAssignment.bin", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#4ade80", relief=tk.FLAT, padx=8, pady=3, command=lambda: self.set_preset_db("assignment"))
        self.btn_preset_assign.pack(side=tk.LEFT, padx=3)
        self.btn_preset_player = tk.Button(p_row, text="🏃 Player.bin", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#fbbf24", relief=tk.FLAT, padx=8, pady=3, command=lambda: self.set_preset_db("player"))
        self.btn_preset_player.pack(side=tk.LEFT, padx=3)
        self.btn_preset_color = tk.Button(p_row, text="🎨 TeamColor.bin", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#a78bfa", relief=tk.FLAT, padx=8, pady=3, command=lambda: self.set_preset_db("color"))
        self.btn_preset_color.pack(side=tk.LEFT, padx=3)
        self.btn_view_db = tk.Button(p_row, text="👁️ VISUALIZZA DATABASE", font=("Segoe UI", 9, "bold"), bg="#4338ca", fg="#ffffff", relief=tk.FLAT, padx=10, pady=3, command=self.visualize_selected_db)
        self.btn_view_db.pack(side=tk.LEFT, padx=4)
        self.btn_db_inject = tk.Button(p_row, text=self.t("btn_db_inject_ram"), font=("Segoe UI", 10, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=12, pady=3, command=self.inject_selected_db_to_ram)
        self.btn_db_inject.pack(side=tk.RIGHT, padx=3)
        self.btn_db_save = tk.Button(p_row, text=self.t("btn_db_save_livecpk"), font=("Segoe UI", 10, "bold"), bg="#f59e0b", fg="black", relief=tk.FLAT, padx=12, pady=3, command=self.save_db_to_livecpk)
        self.btn_db_save.pack(side=tk.RIGHT, padx=3)
        w_row = tk.Frame(file_panel, bg="#181822")
        w_row.pack(fill=tk.X, pady=(4, 0))
        self.btn_unpack_wesys = tk.Button(w_row, text="🔓 DECODIFICA / ESTRAI WESYS (.bin ➔ .raw)", font=("Segoe UI", 9, "bold"), bg="#0284c7", fg="white", relief=tk.FLAT, padx=10, pady=3, command=self.unpack_selected_wesys)
        self.btn_unpack_wesys.pack(side=tk.LEFT, padx=3)
        self.btn_pack_wesys = tk.Button(w_row, text="🔒 CODIFICA / COMPILA WESYS (.raw ➔ .bin)", font=("Segoe UI", 9, "bold"), bg="#7c3aed", fg="white", relief=tk.FLAT, padx=10, pady=3, command=self.pack_selected_to_wesys)
        self.btn_pack_wesys.pack(side=tk.LEFT, padx=3)
        self.btn_export_csv = tk.Button(w_row, text="📤 ESPORTA IN CSV", font=("Segoe UI", 9, "bold"), bg="#059669", fg="white", relief=tk.FLAT, padx=10, pady=3, command=self.export_current_db_csv)
        self.btn_export_csv.pack(side=tk.LEFT, padx=3)
        self.btn_batch_pesdb = tk.Button(w_row, text="📂 DECODIFICA CARTELLA PESDB", font=("Segoe UI", 9, "bold"), bg="#d97706", fg="white", relief=tk.FLAT, padx=10, pady=3, command=self.decode_entire_pesdb_folder)
        self.btn_batch_pesdb.pack(side=tk.LEFT, padx=3)
        vis_frame = tk.LabelFrame(self.tab_db, text=" 👁️ Visualizzatore Struttura & Dati Database ", font=("Segoe UI", 10, "bold"), fg="#34d399", bg="#181822", padx=8, pady=6)
        vis_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=6)
        split_pane = tk.PanedWindow(vis_frame, orient=tk.HORIZONTAL, bg="#111116", sashwidth=4)
        split_pane.pack(fill=tk.BOTH, expand=True)
        left_box = tk.Frame(split_pane, bg="#14141c")
        split_pane.add(left_box, width=540)
        lbl_rec = tk.Label(left_box, text="📋 Record & Campi Decodificati:", font=("Segoe UI", 9, "bold"), fg="#94a3b8", bg="#14141c")
        lbl_rec.pack(anchor="w", padx=6, pady=2)
        rec_cols = ("rec_id", "offset", "id_val", "text_val", "hex_preview")
        self.tree_rec = ttk.Treeview(left_box, columns=rec_cols, show="headings", selectmode="browse")
        self.tree_rec.heading("rec_id", text="# Record", command=lambda: sort_treeview_column(self.tree_rec, "rec_id", False))
        self.tree_rec.heading("offset", text="Offset", command=lambda: sort_treeview_column(self.tree_rec, "offset", False))
        self.tree_rec.heading("id_val", text="ID / Param", command=lambda: sort_treeview_column(self.tree_rec, "id_val", False))
        self.tree_rec.heading("text_val", text="Testo / Identificatore", command=lambda: sort_treeview_column(self.tree_rec, "text_val", False))
        self.tree_rec.heading("hex_preview", text="Anteprima Hex", command=lambda: sort_treeview_column(self.tree_rec, "hex_preview", False))
        self.tree_rec.column("rec_id", width=70, anchor="center")
        self.tree_rec.column("offset", width=80, anchor="center")
        self.tree_rec.column("id_val", width=90, anchor="center")
        self.tree_rec.column("text_val", width=180, anchor="w")
        self.tree_rec.column("hex_preview", width=160, anchor="w")
        scroll_rec = ttk.Scrollbar(left_box, orient=tk.VERTICAL, command=self.tree_rec.yview)
        self.tree_rec.configure(yscrollcommand=scroll_rec.set)
        self.tree_rec.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_rec.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree_rec.bind("<<TreeviewSelect>>", lambda e: self.on_select_record())
        right_box = tk.Frame(split_pane, bg="#14141c")
        split_pane.add(right_box, width=540)
        lbl_hex_dump = tk.Label(right_box, text="🔬 Ispezione Esadecimale (Offset | Hex | ASCII):", font=("Segoe UI", 9, "bold"), fg="#94a3b8", bg="#14141c")
        lbl_hex_dump.pack(anchor="w", padx=6, pady=2)
        self.txt_db_hex = tk.Text(right_box, font=("Consolas", 10), bg="#0d0d12", fg="#38bdf8", insertbackground="white", relief=tk.FLAT, padx=6, pady=6)
        scroll_hex = ttk.Scrollbar(right_box, orient=tk.VERTICAL, command=self.txt_db_hex.yview)
        self.txt_db_hex.configure(yscrollcommand=scroll_hex.set)
        self.txt_db_hex.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll_hex.pack(side=tk.RIGHT, fill=tk.Y)
        log_strip = tk.Frame(self.tab_db, bg="#181822", height=30)
        log_strip.pack(fill=tk.X, padx=12, pady=(0, 6))
        self.lbl_db_status_strip = tk.Label(log_strip, text="Pronto. Clicca su '👁️ VISUALIZZA DATABASE' per ispezionare i dati.", font=("Segoe UI", 9, "italic"), fg="#fbbf24", bg="#181822")
        self.lbl_db_status_strip.pack(side=tk.LEFT, padx=8, pady=4)
    def db_log(self, msg):
        self.lbl_db_status_strip.config(text=f"[{time.strftime('%H:%M:%S')}] {msg}")
    def scan_active_databases_ram(self):
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        self.btn_db_scan.config(state=tk.DISABLED, text="⏳ SCANSIONE RAM...")
        self.tree_db.delete(*self.tree_db.get_children())
        self.db_log("Scansione della memoria RAM in corso alla ricerca dei blocchi di database...")
        def worker():
            def on_found(b):
                self.root.after(0, lambda item=b: self.tree_db.insert("", tk.END, values=(item["address"], item["name"], item["size"], item["status"])))
            def on_progress(count, total_mb):
                self.root.after(0, lambda: self.db_log(f"Scansione memoria in corso: {count} blocchi esaminati ({total_mb} MB)..."))
            blocks = self.engine.scan_for_database_blocks(on_found=on_found, on_progress=on_progress)
            def on_finish():
                self.btn_db_scan.config(state=tk.NORMAL, text=self.t("btn_db_scan"))
                self.db_log(f"✅ Scansione completata! Trovati {len(blocks)} blocchi di database attivi in memoria RAM.")
            self.root.after(0, on_finish)
        threading.Thread(target=worker, daemon=True).start()
    def browse_db_file(self):
        fn = filedialog.askopenfilename(
            title="Seleziona File Database (.bin / .db / .dat)",
            filetypes=[("Database Files", "*.bin;*.db;*.dat;*.csv"), ("All Files", "*.*")]
        )
        if fn:
            self.ent_db_path.delete(0, tk.END)
            self.ent_db_path.insert(0, fn)
            self.db_log(f"Selezionato file database: {fn} ({os.path.getsize(fn):,d} bytes)")
            self.visualize_selected_db()
    def set_preset_db(self, db_type):
        paths = {
            "team": r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb\Team.bin",
            "assignment": r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb\PlayerAssignment.bin",
            "player": r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb\Player.bin",
            "color": r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb\TeamColor.bin",
            "pesdb_folder": r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb"
        }
        target = paths.get(db_type)
        if target and os.path.exists(target):
            self.ent_db_path.delete(0, tk.END)
            self.ent_db_path.insert(0, target)
            self.db_log(f"Preset caricato: {target}")
            self.visualize_selected_db()
        else:
            fallback = target.replace("extracted_evomod_all", "extracted_dt870_all") if target else None
            if fallback and os.path.exists(fallback):
                self.ent_db_path.delete(0, tk.END)
                self.ent_db_path.insert(0, fallback)
                self.db_log(f"Preset caricato: {fallback}")
                self.visualize_selected_db()
            else:
                messagebox.showinfo(self.t("title"), f"Percorso preset non trovato: {target}")
    def decode_entire_pesdb_folder(self):
        initial_dir = r"A:\Mod Efootball\extracted_evomod_all\common\etc\pesdb"
        if not os.path.exists(initial_dir):
            initial_dir = self.base_dir
        src_dir = filedialog.askdirectory(
            title="Seleziona la cartella contenente i file .bin di pesdb",
            initialdir=initial_dir
        )
        if not src_dir:
            return
        out_dir = filedialog.askdirectory(
            title="Seleziona la cartella di destinazione per i file decodificati",
            initialdir=src_dir + "_decoded" if not os.path.exists(src_dir + "_decoded") else src_dir
        )
        if not out_dir:
            out_dir = src_dir + "_decoded"
        os.makedirs(out_dir, exist_ok=True)
        self.btn_batch_pesdb.config(state=tk.DISABLED, text="⏳ Decodifica in corso...")
        self.db_log(f"Inizio decodifica batch da '{src_dir}' a '{out_dir}'...")
        def worker():
            decoded_count = 0
            csv_count = 0
            errors = []
            files = [f for f in os.listdir(src_dir) if f.lower().endswith(".bin")]
            total_files = len(files)
            for idx, fn in enumerate(files):
                src_path = os.path.join(src_dir, fn)
                dst_path = os.path.join(out_dir, fn)
                try:
                    with open(src_path, "rb") as fp:
                        data = fp.read()
                    unpacked = native_rust_unpack_wesys(data)
                    with open(dst_path, "wb") as fp:
                        fp.write(unpacked)
                    decoded_count += 1
                    base_name = fn.lower()
                    csv_path = os.path.join(out_dir, f"{os.path.splitext(fn)[0]}.csv")
                    if "teamcolor" in base_name or "color" in base_name:
                        records = parse_team_color_bin(unpacked)
                        if records:
                            with open(csv_path, "w", newline="", encoding="utf-8") as fp_csv:
                                w = csv.DictWriter(fp_csv, fieldnames=["row", "offset", "team_id", "color_primary", "color_secondary", "rgb_primary", "rgb_secondary", "hex"])
                                w.writeheader()
                                w.writerows(records)
                            csv_count += 1
                    elif "team" in base_name:
                        records = parse_team_bin(unpacked)
                        if records:
                            with open(csv_path, "w", newline="", encoding="utf-8") as fp_csv:
                                w = csv.DictWriter(fp_csv, fieldnames=["row", "offset", "team_id", "name", "hex"])
                                w.writeheader()
                                w.writerows(records)
                            csv_count += 1
                    elif "playerassignment" in base_name or "assignment" in base_name:
                        records = parse_player_assignment_bin(unpacked)
                        if records:
                            with open(csv_path, "w", newline="", encoding="utf-8") as fp_csv:
                                w = csv.DictWriter(fp_csv, fieldnames=["row", "index", "pid_32", "pid_hex", "team_id", "squad_number", "roster_slot"])
                                w.writeheader()
                                w.writerows(records)
                            csv_count += 1
                    elif "player" in base_name:
                        records = parse_player_bin(unpacked)
                        if records:
                            with open(csv_path, "w", newline="", encoding="utf-8") as fp_csv:
                                w = csv.DictWriter(fp_csv, fieldnames=["row", "offset", "player_id", "nationality_id", "height_cm", "weight_kg", "attacking_style", "hex"])
                                w.writeheader()
                                w.writerows(records)
                            csv_count += 1
                    self.db_log(f"[{idx+1}/{total_files}] Decodificato {fn} ({len(data):,d} ➔ {len(unpacked):,d} B)")
                except Exception as e:
                    errors.append(f"{fn}: {e}")
            def on_finish():
                self.btn_batch_pesdb.config(state=tk.NORMAL, text="📂 DECODIFICA CARTELLA PESDB")
                self.db_log(f"✅ Decodifica batch completata: {decoded_count}/{total_files} file estratti, {csv_count} CSV generati.")
                msg = (
                    f"✅ Decodifica batch completata con successo!\n\n"
                    f"• File .bin decodificati: {decoded_count} su {total_files}\n"
                    f"• File CSV generati: {csv_count}\n"
                    f"• Cartella di destinazione:\n{out_dir}"
                )
                if errors:
                    msg += f"\n\n⚠️ Errori su {len(errors)} file:\n" + "\n".join(errors[:5])
                messagebox.showinfo("Decodifica Batch pesdb", msg)
            self.root.after(0, on_finish)
        threading.Thread(target=worker, daemon=True).start()
    def unpack_selected_wesys(self):
        db_path = self.ent_db_path.get().strip()
        if not os.path.exists(db_path) or os.path.isdir(db_path):
            messagebox.showwarning(self.t("title"), "Seleziona un file .bin WESYS valido.")
            return
        self.btn_unpack_wesys.config(state=tk.DISABLED, text="⏳ Decodifica...")
        def worker():
            try:
                with open(db_path, "rb") as f:
                    data = f.read()
                unpacked = native_rust_unpack_wesys(data)
                out_path = os.path.splitext(db_path)[0] + "_unpacked.raw"
                with open(out_path, "wb") as f:
                    f.write(unpacked)
                def on_ok():
                    self.btn_unpack_wesys.config(state=tk.NORMAL, text="🔓 DECODIFICA / ESTRAI WESYS (.bin ➔ .raw)")
                    self.db_log(f"🔓 WESYS decodificato ({len(data):,d} ➔ {len(unpacked):,d} byte): {out_path}")
                    messagebox.showinfo(self.t("title"), f"File WESYS decifrato ed estratto con successo!\nSalvato in:\n{out_path}\n({len(unpacked):,d} byte decompattati)")
                    self.ent_db_path.delete(0, tk.END)
                    self.ent_db_path.insert(0, out_path)
                    self.visualize_selected_db()
                self.root.after(0, on_ok)
            except Exception as e:
                def on_err(err=e):
                    self.btn_unpack_wesys.config(state=tk.NORMAL, text="🔓 DECODIFICA / ESTRAI WESYS (.bin ➔ .raw)")
                    messagebox.showerror(self.t("title"), f"Errore durante decodifica WESYS:\n{err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def pack_selected_to_wesys(self):
        raw_path = self.ent_db_path.get().strip()
        if not os.path.exists(raw_path) or os.path.isdir(raw_path):
            messagebox.showwarning(self.t("title"), "Seleziona un file valido da compilare in WESYS.")
            return
        self.btn_pack_wesys.config(state=tk.DISABLED, text="⏳ Compilazione...")
        def worker():
            try:
                with open(raw_path, "rb") as f:
                    data = f.read()
                packed = pack_wesys_container(data, flag_byte=0x20)
                out_path = os.path.splitext(raw_path)[0] + "_wesys.bin"
                with open(out_path, "wb") as f:
                    f.write(packed)
                def on_ok():
                    self.btn_pack_wesys.config(state=tk.NORMAL, text="🔒 CODIFICA / COMPILA WESYS (.raw ➔ .bin)")
                    self.db_log(f"🔒 WESYS cifrato & compilato ({len(data):,d} ➔ {len(packed):,d} byte): {out_path}")
                    messagebox.showinfo(self.t("title"), f"Container WESYS cifrato con successo (XorShift128 0x20)!\nSalvato in:\n{out_path}\nPronto per essere inserito nel LiveCPK.")
                self.root.after(0, on_ok)
            except Exception as e:
                def on_err(err=e):
                    self.btn_pack_wesys.config(state=tk.NORMAL, text="🔒 CODIFICA / COMPILA WESYS (.raw ➔ .bin)")
                    messagebox.showerror(self.t("title"), f"Errore durante compilazione WESYS:\n{err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def export_current_db_csv(self):
        db_path = self.ent_db_path.get().strip()
        if not os.path.exists(db_path) or os.path.isdir(db_path):
            messagebox.showwarning(self.t("title"), "Carica prima un file database valido.")
            return
        csv_path = filedialog.asksaveasfilename(
            title="Salva Esportazione CSV",
            initialfile=f"{os.path.splitext(os.path.basename(db_path))[0]}_export.csv",
            filetypes=[("CSV Files", "*.csv"), ("All Files", "*.*")]
        )
        if not csv_path:
            return
        self.btn_export_csv.config(state=tk.DISABLED, text="⏳ Esportazione...")
        def worker():
            try:
                with open(db_path, "rb") as f:
                    data = f.read()
                unpacked = native_rust_unpack_wesys(data)
                base_name = os.path.basename(db_path).lower()
                if "teamcolor" in base_name or "color" in base_name:
                    records = parse_team_color_bin(unpacked)
                    fieldnames = ["row", "offset", "team_id", "color_primary", "color_secondary", "rgb_primary", "rgb_secondary", "hex"]
                    with open(csv_path, "w", newline="", encoding="utf-8") as fp:
                        w = csv.DictWriter(fp, fieldnames=fieldnames)
                        w.writeheader()
                        w.writerows(records)
                    msg = f"Esportati {len(records):,d} record colori squadra in:\n{csv_path}"
                elif "team" in base_name:
                    records = parse_team_bin(unpacked)
                    fieldnames = ["row", "offset", "team_id", "name", "hex"]
                    with open(csv_path, "w", newline="", encoding="utf-8") as fp:
                        w = csv.DictWriter(fp, fieldnames=fieldnames)
                        w.writeheader()
                        w.writerows(records)
                    msg = f"Esportati {len(records):,d} record squadre in:\n{csv_path}"
                elif "playerassignment" in base_name or "assignment" in base_name:
                    records = parse_player_assignment_bin(unpacked)
                    fieldnames = ["row", "index", "pid_32", "pid_hex", "team_id", "squad_number", "roster_slot"]
                    with open(csv_path, "w", newline="", encoding="utf-8") as fp:
                        w = csv.DictWriter(fp, fieldnames=fieldnames)
                        w.writeheader()
                        w.writerows(records)
                    msg = f"Esportati {len(records):,d} assegnazioni giocatori e numeri di maglia in:\n{csv_path}"
                elif "player" in base_name:
                    records = parse_player_bin(unpacked)
                    fieldnames = ["row", "offset", "player_id", "nationality_id", "height_cm", "weight_kg", "attacking_style", "hex"]
                    with open(csv_path, "w", newline="", encoding="utf-8") as fp:
                        w = csv.DictWriter(fp, fieldnames=fieldnames)
                        w.writeheader()
                        w.writerows(records)
                    msg = f"Esportati {len(records):,d} record giocatori in:\n{csv_path}"
                else:
                    records = []
                    stride = 64
                    for i in range(0, len(unpacked), stride):
                        chunk = unpacked[i:i+stride]
                        records.append({"offset": f"0x{i:06X}", "hex": chunk[:16].hex(" "), "length": len(chunk)})
                    with open(csv_path, "w", newline="", encoding="utf-8") as fp:
                        w = csv.DictWriter(fp, fieldnames=["offset", "hex", "length"])
                        w.writeheader()
                        w.writerows(records)
                    msg = f"Esportati {len(records):,d} record in:\n{csv_path}"
                def on_ok():
                    self.btn_export_csv.config(state=tk.NORMAL, text="📤 ESPORTA IN CSV")
                    self.db_log(f"Esportazione CSV completata: {csv_path}")
                    messagebox.showinfo(self.t("title"), msg)
                self.root.after(0, on_ok)
            except Exception as e:
                def on_err(err=e):
                    self.btn_export_csv.config(state=tk.NORMAL, text="📤 ESPORTA IN CSV")
                    messagebox.showerror(self.t("title"), f"Errore esportazione CSV:\n{err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def visualize_selected_db(self):
        db_path = self.ent_db_path.get().strip()
        if not os.path.exists(db_path) or os.path.isdir(db_path):
            messagebox.showwarning(self.t("title"), "Seleziona un file database valido.")
            return
        with open(db_path, "rb") as f:
            data = f.read()
        is_wesys = is_wesys_container(data)
        unpacked_data = native_rust_unpack_wesys(data) if is_wesys else data
        self.current_db_bytes = unpacked_data
        self.tree_rec.delete(*self.tree_rec.get_children())
        self.txt_db_hex.delete("1.0", tk.END)
        file_sz = len(unpacked_data)
        base_name = os.path.basename(db_path).lower()
        records_count = 0
        if "teamcolor" in base_name or "color" in base_name:
            records = parse_team_color_bin(unpacked_data)
            records_count = len(records)
            for r in records[:500]:
                text_info = f"Primario: {r['color_primary']} ({r['rgb_primary']}) | Secondario: {r['color_secondary']}"
                self.tree_rec.insert("", tk.END, values=(r["row"], r["offset"], f"Team #{r['team_id']}", text_info, r["hex"]))
        elif "team" in base_name:
            records = parse_team_bin(unpacked_data)
            records_count = len(records)
            for r in records[:500]:
                text_info = f"Squadra: {r['name']}"
                self.tree_rec.insert("", tk.END, values=(r["row"], r["offset"], f"ID: {r['team_id']}", text_info, r["hex"]))
        elif "playerassignment" in base_name or "assignment" in base_name:
            records = parse_player_assignment_bin(unpacked_data)
            records_count = len(records)
            for r in records[:500]:
                text_info = f"Team #{r['team_id']} | Maglia #{r['squad_number']} (Slot {r['roster_slot']})"
                self.tree_rec.insert("", tk.END, values=(r["row"], f"0x{r['index']*24:04X}", f"PID: {r['pid_32']}", text_info, r["pid_hex"]))
        elif "player" in base_name:
            records = parse_player_bin(unpacked_data)
            records_count = len(records)
            for r in records[:500]:
                text_info = f"Naz: {r['nationality_id']} | H: {r['height_cm']}cm, W: {r['weight_kg']}kg | Stile Att: {r['attacking_style']}"
                self.tree_rec.insert("", tk.END, values=(r["row"], r["offset"], f"PID: {r['player_id']}", text_info, r["hex"]))
        else:
            stride = 64
            records_count = len(unpacked_data) // stride
            for i in range(min(records_count, 500)):
                chunk = unpacked_data[i * stride : (i + 1) * stride]
                self.tree_rec.insert("", tk.END, values=(i + 1, f"0x{i * stride:04X}", f"Chunk {i+1}", f"Dim: {len(chunk)}B", chunk[:16].hex(" ")))
        hex_lines = []
        for i in range(0, min(file_sz, 65536), 16):
            chunk = unpacked_data[i:i+16]
            hex_part = " ".join(f"{b:02X}" for b in chunk).ljust(48)
            asc_part = "".join(chr(b) if 32 <= b <= 126 else "." for b in chunk)
            hex_lines.append(f"{i:08X}  {hex_part}  |{asc_part}|")
        self.txt_db_hex.insert(tk.END, "\n".join(hex_lines))
        self.db_log(f"Database caricato: {os.path.basename(db_path)} ({file_sz:,d} byte, ~{records_count:,d} record)")
    def on_select_record(self):
        sel = self.tree_rec.selection()
        if not sel:
            return
        item = self.tree_rec.item(sel[0])["values"]
        offset_hex = str(item[1])
        try:
            offset_val = int(offset_hex, 16)
            line_idx = (offset_val // 16) + 1
            self.txt_db_hex.see(f"{line_idx}.0")
            self.txt_db_hex.tag_remove("highlight", "1.0", tk.END)
            self.txt_db_hex.tag_add("highlight", f"{line_idx}.0", f"{line_idx}.end")
            self.txt_db_hex.tag_config("highlight", background="#1e3a8a", foreground="#ffffff")
        except Exception:
            pass
    def inspect_ram_db_in_hex(self):
        sel = self.tree_db.selection()
        if not sel:
            return
        item = self.tree_db.item(sel[0])["values"]
        addr_str = str(item[0])
        try:
            addr_int = int(addr_str, 16)
            self.ent_hex_addr.delete(0, tk.END)
            self.ent_hex_addr.insert(0, f"0x{addr_int:X}")
            self.notebook.select(1) 
            self.read_memory_hex()
        except Exception as e:
            messagebox.showerror(self.t("title"), f"Errore ispezione RAM: {e}")
    def inject_selected_db_to_ram(self):
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        db_path = self.ent_db_path.get().strip()
        if not os.path.exists(db_path) or os.path.isdir(db_path):
            messagebox.showwarning(self.t("title"), self.t("msg_select_db_file"))
            return
        sel = self.tree_db.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), "Seleziona prima un blocco database dalla tabella (esegui prima '🔍 SCANSIONA DATABASE IN RAM').")
            return
        item = self.tree_db.item(sel[0])["values"]
        target_addr = int(str(item[0]), 16)
        target_desc = item[1]
        self.btn_db_inject.config(state=tk.DISABLED, text="⏳ Iniezione...")
        def worker():
            try:
                with open(db_path, "rb") as f:
                    data = f.read()
                self.db_log(f"Iniezione di {len(data):,d} byte da '{os.path.basename(db_path)}' a 0x{target_addr:X} ({target_desc})...")
                ok, msg = self.engine.inject_database_bytes(target_addr, data)
                def on_finish(success=ok, message=msg):
                    self.btn_db_inject.config(state=tk.NORMAL, text=self.t("btn_db_inject_ram"))
                    if success:
                        self.db_log(f"✅ SUCCESSO: {message}")
                        messagebox.showinfo(self.t("title"), self.t("msg_db_inject_ok"))
                    else:
                        self.db_log(f"❌ ERRORE: {message}")
                        messagebox.showerror(self.t("title"), f"Errore iniezione: {message}")
                self.root.after(0, on_finish)
            except Exception as e:
                def on_err(err=e):
                    self.btn_db_inject.config(state=tk.NORMAL, text=self.t("btn_db_inject_ram"))
                    messagebox.showerror(self.t("title"), f"Errore iniezione: {err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def save_db_to_livecpk(self):
        db_path = self.ent_db_path.get().strip()
        if not os.path.exists(db_path):
            messagebox.showwarning(self.t("title"), self.t("msg_select_db_file"))
            return
        target_dir = os.path.join(self.content_dir, "Official_TeamName_Toriga", "common", "etc", "pesdb")
        os.makedirs(target_dir, exist_ok=True)
        if os.path.isdir(db_path):
            for f in os.listdir(db_path):
                src = os.path.join(db_path, f)
                if os.path.isfile(src):
                    shutil.copy2(src, os.path.join(target_dir, f))
            self.db_log(f"✅ Cartella database intera copiata in: {target_dir}")
            logger.info("Cartella database intera copiata in LiveCPK: %s", target_dir)
        else:
            dst = os.path.join(target_dir, os.path.basename(db_path))
            shutil.copy2(db_path, dst)
            self.db_log(f"✅ File database salvato in: {dst}")
            logger.info("File database salvato in LiveCPK: %s", dst)
        self.ensure_content_root_registered()
        self.save_sider_ini()
        self.sync_sider_to_game()
        messagebox.showinfo(self.t("title"), self.t("msg_db_save_ok"))
    def apply_mod_live_to_ram(self):
        sel = self.tree_mods.selection()
        if not sel:
            messagebox.showinfo(self.t("title"), self.t("msg_select_row"))
            return
        idx = self.tree_mods.index(sel[0])
        mod = self.installed_mods[idx]
        team_pairs = {}
        for ini_name in ["mod.ini", "teams.ini"]:
            ini_path = os.path.join(mod["full_path"], ini_name)
            if os.path.exists(ini_path):
                with open(ini_path, "r", encoding="utf-8", errors="ignore") as f:
                    in_teams_sec = False
                    for line in f:
                        line = line.strip()
                        if line.startswith("[") and line.endswith("]"):
                            in_teams_sec = (line.lower() == "[teams]")
                            continue
                        if in_teams_sec and "=" in line:
                            k, v = line.split("=", 1)
                            fake = k.strip().strip('"').strip('\'')
                            real = v.strip().strip('"').strip('\'')
                            if fake and real:
                                team_pairs[fake] = real
        if not team_pairs:
            messagebox.showinfo(self.t("title"), self.t("msg_no_teams_mod"))
            return
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        total_injected = 0
        for fake_name, real_name in team_pairs.items():
            for item in self.engine.scan_memory_generator(fake_name, case_sensitive=False, max_results=30):
                if not item["is_ui_display"]:
                    continue
                addr = item["address"]
                enc = item["encoding"]
                orig_full = item["current"].strip()
                flen = max(item["matched_len"], len(orig_full))
                if enc == "UTF-16":
                    raw = real_name.encode("utf-16le")
                    if len(raw) < flen * 2:
                        raw = raw + b"\x00\x00" * (flen - len(real_name))
                    else:
                        raw = raw[:flen * 2]
                else:
                    raw = real_name.encode("latin-1")
                    if len(raw) < flen:
                        raw = raw + b" " * (flen - len(raw))
                    else:
                        raw = raw[:flen]
                if self.engine.write_bytes_safe(addr, raw):
                    total_injected += 1
        messagebox.showinfo(self.t("title"), self.t("msg_applied_mod", count=total_injected, name=mod["name"]))
    def setup_tab_camera_ui(self):
        head = tk.Frame(self.tab_camera, bg="#1a1a24", padx=16, pady=12)
        head.pack(fill=tk.X, padx=12, pady=(10, 8))
        tk.Label(head, text="🎬 eFootball Camera Studio & Broadcast Master", font=("Segoe UI", 14, "bold"), fg="#38bdf8", bg="#1a1a24").pack(anchor="w")
        tk.Label(head, text="Configura la visuale televisiva ottimale, controlla il campo visivo (FOV), l'altezza, lo zoom e la Freecam 3D in tempo reale.", font=("Segoe UI", 9), fg="#9ca3af", bg="#1a1a24").pack(anchor="w", pady=(2, 0))
        main_frame = tk.Frame(self.tab_camera, bg="#16161d")
        main_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=4)
        left_col = tk.Frame(main_frame, bg="#181824", padx=14, pady=12, width=430)
        left_col.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 8))
        tk.Label(left_col, text="🏆 Preset Visuali Professionali", font=("Segoe UI", 11, "bold"), fg="#fbbf24", bg="#181824").pack(anchor="w", pady=(0, 8))
        presets_frame = tk.Frame(left_col, bg="#181824")
        presets_frame.pack(fill=tk.X, pady=4)
        btn_p1 = tk.Button(presets_frame, text="⭐ Broadcast Ultimate TV (Consigliata)\n[Zoom: 0.82 | Altezza: 1.32 | Tilt: -0.12 | FOV: 50.0°]", font=("Segoe UI", 9, "bold"), bg="#0284c7", fg="white", relief=tk.FLAT, padx=10, pady=6, justify="left", command=lambda: self.apply_camera_preset("broadcast"))
        btn_p1.pack(fill=tk.X, pady=4)
        btn_p2 = tk.Button(presets_frame, text="🏟️ Sky Sports Tactical Wide\n[Zoom: 0.72 | Altezza: 1.45 | Tilt: -0.15 | FOV: 54.0°]", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#e2e8f0", relief=tk.FLAT, padx=10, pady=6, justify="left", command=lambda: self.apply_camera_preset("tactical"))
        btn_p2.pack(fill=tk.X, pady=4)
        btn_p3 = tk.Button(presets_frame, text="⚽ EA Sports TV Style (Dinamica)\n[Zoom: 1.05 | Altezza: 1.15 | Tilt: 0.00 | FOV: 46.0°]", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#e2e8f0", relief=tk.FLAT, padx=10, pady=6, justify="left", command=lambda: self.apply_camera_preset("action"))
        btn_p3.pack(fill=tk.X, pady=4)
        btn_p4 = tk.Button(presets_frame, text="🎮 Curva Fan Cam (Immersiva Spalti)\n[Zoom: 1.20 | Altezza: 0.95 | Tilt: +0.10 | FOV: 42.0°]", font=("Segoe UI", 9, "bold"), bg="#1e293b", fg="#e2e8f0", relief=tk.FLAT, padx=10, pady=6, justify="left", command=lambda: self.apply_camera_preset("curva"))
        btn_p4.pack(fill=tk.X, pady=4)
        btn_p5 = tk.Button(presets_frame, text="🔄 Ripristina Default Konami\n[Zoom: 1.00 | Altezza: 1.00 | Tilt: 0.00 | FOV: 50.0°]", font=("Segoe UI", 9), bg="#374151", fg="#d1d5db", relief=tk.FLAT, padx=10, pady=5, justify="left", command=lambda: self.apply_camera_preset("default"))
        btn_p5.pack(fill=tk.X, pady=(4, 12))
        hk_box = tk.LabelFrame(left_col, text="⌨️ Hotkey Live Durante la Partita", font=("Segoe UI", 9, "bold"), fg="#38bdf8", bg="#14141c", padx=10, pady=8)
        hk_box.pack(fill=tk.X, pady=6)
        hk_text = (
            "• [F1]: Attiva / Disattiva Freecam 3D\n"
            "• [Numpad + / -]: Zoom Campo (+/-)\n"
            "• [Numpad 8 / 2]: Altezza Telecamera (+/-)\n"
            "• [Numpad 4 / 6]: Inclinazione Angolo (+/-)\n"
            "• [Spazio]: Mostra / Nascondi Overlay Sider"
        )
        tk.Label(hk_box, text=hk_text, font=("Consolas", 9), fg="#94a3b8", bg="#14141c", justify="left").pack(anchor="w")
        right_col = tk.Frame(main_frame, bg="#181824", padx=18, pady=12)
        right_col.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.lbl_cam_active_preset = tk.Label(right_col, text="Preset Attivo: ⭐ Broadcast Ultimate TV (Miglior Bilanciamento Realistico)", font=("Segoe UI", 10, "bold"), fg="#38bdf8", bg="#181824")
        self.lbl_cam_active_preset.pack(anchor="w", pady=(0, 10))
        chk_frame = tk.Frame(right_col, bg="#181824")
        chk_frame.pack(fill=tk.X, pady=(0, 10))
        tk.Checkbutton(chk_frame, text="Attiva Subsystem Telecamera nel Sider", variable=self.cam_enabled, font=("Segoe UI", 10, "bold"), fg="#4ade80", bg="#181824", selectcolor="#0f172a", activebackground="#181824", activeforeground="#4ade80").pack(side=tk.LEFT)
        def create_slider(parent, label_text, var, from_val, to_val, resolution, unit=""):
            row = tk.Frame(parent, bg="#181824")
            row.pack(fill=tk.X, pady=6)
            top_line = tk.Frame(row, bg="#181824")
            top_line.pack(fill=tk.X)
            tk.Label(top_line, text=label_text, font=("Segoe UI", 9, "bold"), fg="#e2e8f0", bg="#181824").pack(side=tk.LEFT)
            val_lbl = tk.Label(top_line, text=f"{var.get():.2f}{unit}", font=("Consolas", 10, "bold"), fg="#38bdf8", bg="#181824")
            val_lbl.pack(side=tk.RIGHT)
            scale = tk.Scale(row, from_=from_val, to=to_val, resolution=resolution, variable=var, orient=tk.HORIZONTAL, showvalue=0, bg="#111116", fg="#ffffff", highlightthickness=0, troughcolor="#22222e", activebackground="#0284c7", command=lambda v: val_lbl.config(text=f"{float(v):.2f}{unit}"))
            scale.pack(fill=tk.X, pady=(2, 0))
            return val_lbl
        self.lbl_val_zoom = create_slider(right_col, "🔍 Zoom Telecamera (Ampiezza di Gioco):", self.cam_zoom, 0.20, 2.50, 0.01)
        self.lbl_val_height = create_slider(right_col, "📐 Altezza Telecamera (Elevazione Visuale):", self.cam_height, 0.20, 2.50, 0.01)
        self.lbl_val_angle = create_slider(right_col, "🔄 Angolazione Lens Tilt (Inclinazione):", self.cam_angle, -0.50, 0.50, 0.01)
        self.lbl_val_fov = create_slider(right_col, "🌐 Campo Visivo Ottico FOV:", self.cam_fov, 30.0, 85.0, 0.5, unit="°")
        self.lbl_val_speed = create_slider(right_col, "🚀 Velocità Movimento Freecam 3D:", self.cam_freecam_speed, 0.5, 10.0, 0.1)
        action_bar = tk.Frame(right_col, bg="#181824", pady=14)
        action_bar.pack(fill=tk.X, pady=(14, 0))
        self.btn_save_cam_ini = tk.Button(action_bar, text="💾 SALVA & APPLICA IN SIDER.INI", font=("Segoe UI", 10, "bold"), bg="#10b981", fg="white", relief=tk.FLAT, padx=16, pady=6, command=self.save_camera_to_sider_ini)
        self.btn_save_cam_ini.pack(side=tk.LEFT, padx=(0, 6))
        self.btn_inject_cam_ram = tk.Button(action_bar, text="⚡ INIETTA LIVE NEL PROCESSO", font=("Segoe UI", 10, "bold"), bg="#0284c7", fg="white", relief=tk.FLAT, padx=14, pady=6, command=self.inject_camera_live_ram)
        self.btn_inject_cam_ram.pack(side=tk.LEFT, padx=6)
    def apply_camera_preset(self, preset_name):
        presets = {
            "broadcast": {"zoom": 0.82, "height": 1.32, "angle": -0.12, "fov": 50.0, "desc": "⭐ Broadcast Ultimate TV (Miglior Bilanciamento Realistico)"},
            "tactical": {"zoom": 0.72, "height": 1.45, "angle": -0.15, "fov": 54.0, "desc": "🏟️ Sky Sports Tactical Wide (Visione Panoramica a 360°)"},
            "action": {"zoom": 1.05, "height": 1.15, "angle": 0.00, "fov": 46.0, "desc": "⚽ EA Sports Dynamic TV (Azione Ravvicinata & Dribbling)"},
            "curva": {"zoom": 1.20, "height": 0.95, "angle": 0.10, "fov": 42.0, "desc": "🎮 Curva Fan Cam (Immersiva dagli Spalti)"},
            "default": {"zoom": 1.00, "height": 1.00, "angle": 0.00, "fov": 50.0, "desc": "🔄 Default Konami Standard"}
        }
        if preset_name in presets:
            p = presets[preset_name]
            self.cam_zoom.set(p["zoom"])
            self.cam_height.set(p["height"])
            self.cam_angle.set(p["angle"])
            self.cam_fov.set(p["fov"])
            self.lbl_cam_active_preset.config(text=f"Preset Attivo: {p['desc']}", fg="#38bdf8")
    def save_camera_to_sider_ini(self, show_msg=True):
        if not os.path.exists(self.sider_ini_path):
            logger.error("sider.ini not found: %s", self.sider_ini_path)
            if show_msg:
                messagebox.showerror(self.t("title"), f"File sider.ini non trovato in:\n{self.sider_ini_path}")
            return
        try:
            cfg = configparser.ConfigParser(strict=False)
            cfg.read(self.sider_ini_path, encoding="utf-8")
            if not cfg.has_section("camera"):
                cfg.add_section("camera")
            cfg.set("camera", "enabled", "1" if self.cam_enabled.get() else "0")
            cfg.set("camera", "zoom", f"{self.cam_zoom.get():.2f}")
            cfg.set("camera", "height", f"{self.cam_height.get():.2f}")
            cfg.set("camera", "angle", f"{self.cam_angle.get():.2f}")
            cfg.set("camera", "fov", f"{self.cam_fov.get():.1f}")
            cfg.set("camera", "freecam_speed", f"{self.cam_freecam_speed.get():.1f}")
            with open(self.sider_ini_path, "w", encoding="utf-8") as f:
                cfg.write(f)
            logger.info("Saved camera config to %s via configparser", self.sider_ini_path)
            game_sider_ini = os.path.join(self.game_bin_dir, "sider.ini")
            if os.path.exists(self.game_bin_dir):
                try:
                    with open(game_sider_ini, "w", encoding="utf-8") as f:
                        cfg.write(f)
                    logger.info("Synced camera config to game directory: %s", game_sider_ini)
                except Exception as e:
                    logger.warning("Could not sync sider.ini to game directory: %s", e)
            if show_msg:
                messagebox.showinfo(
                    self.t("title"),
                    f"✅ Configurazione Telecamera salvata con successo in sider.ini!\n\n"
                    f"• Zoom: {self.cam_zoom.get():.2f}\n"
                    f"• Altezza: {self.cam_height.get():.2f}\n"
                    f"• Angolazione: {self.cam_angle.get():.2f}\n"
                    f"• FOV: {self.cam_fov.get():.1f}°\n"
                    f"• Freecam Speed: {self.cam_freecam_speed.get():.1f}\n\n"
                    f"La mod telecamera broadcast è attiva e sincronizzata con il gioco!"
                )
        except Exception as e:
            logger.exception("Failed to save camera config to sider.ini")
            if show_msg:
                messagebox.showerror(self.t("title"), f"Errore durante il salvataggio di sider.ini: {e}")
    def load_camera_from_sider_ini(self):
        if not os.path.exists(self.sider_ini_path):
            return
        try:
            cfg = configparser.ConfigParser(strict=False)
            cfg.read(self.sider_ini_path, encoding="utf-8")
            if cfg.has_section("camera"):
                self.cam_enabled.set(cfg.getboolean("camera", "enabled", fallback=True))
                self.cam_zoom.set(cfg.getfloat("camera", "zoom", fallback=0.82))
                self.cam_height.set(cfg.getfloat("camera", "height", fallback=1.32))
                self.cam_angle.set(cfg.getfloat("camera", "angle", fallback=-0.12))
                self.cam_fov.set(cfg.getfloat("camera", "fov", fallback=50.0))
                self.cam_freecam_speed.set(cfg.getfloat("camera", "freecam_speed", fallback=2.5))
                logger.info("Loaded camera settings from sider.ini successfully")
        except Exception as e:
            logger.warning("Error parsing camera settings from %s: %s", self.sider_ini_path, e)
    def inject_camera_live_ram(self):
        if not self.engine.check_alive():
            self.engine.attach()
            if not self.engine.check_alive():
                messagebox.showwarning(self.t("title"), self.t("msg_game_not_found"))
                return
        self.btn_inject_cam_ram.config(state=tk.DISABLED, text="⏳ Iniezione Live RAM...")
        zoom = float(self.cam_zoom.get())
        height = float(self.cam_height.get())
        angle = float(self.cam_angle.get())
        fov = float(self.cam_fov.get())
        self.save_camera_to_sider_ini(show_msg=False)
        def worker():
            try:
                pack_floats = struct.pack("<ffff", zoom, height, angle, fov)
                found_addrs = []
                mbi = MEMORY_BASIC_INFORMATION64()
                address = 0x10000
                max_chunk = 32 * 1024 * 1024
                buf = (ctypes.c_char * max_chunk)()
                read_b = ctypes.c_size_t(0)
                while True:
                    res = VirtualQueryEx(self.engine.handle, ctypes.c_void_p(address), ctypes.byref(mbi), ctypes.sizeof(mbi))
                    if res == 0:
                        break
                    is_rw = (
                        mbi.State == MEM_COMMIT
                        and (mbi.Protect & PAGE_GUARD == 0)
                        and (mbi.Protect & PAGE_NOACCESS == 0)
                        and bool(mbi.Protect & (PAGE_READWRITE | PAGE_EXECUTE_READWRITE))
                    )
                    if is_rw and 4096 <= mbi.RegionSize <= max_chunk:
                        reg_size = mbi.RegionSize
                        try:
                            if ReadProcessMemory(self.engine.handle, ctypes.c_void_p(mbi.BaseAddress), buf, reg_size, ctypes.byref(read_b)):
                                raw = bytes(buf[:read_b.value])
                                for i in range(0, len(raw) - 16, 4):
                                    cz, ch, ca, cf = struct.unpack_from("<ffff", raw, i)
                                    if 0.1 <= cz <= 5.0 and 0.1 <= ch <= 5.0 and -1.5 <= ca <= 1.5 and 20.0 <= cf <= 120.0:
                                        cand_addr = mbi.BaseAddress + i
                                        found_addrs.append(cand_addr)
                                        if len(found_addrs) >= 30:
                                            break
                                if len(found_addrs) >= 30:
                                    break
                        except Exception as err:
                            logger.error("Errore durante lettura blocco memoria a 0x%X: %s", mbi.BaseAddress, err)
                    next_addr = mbi.BaseAddress + mbi.RegionSize
                    if next_addr <= address or next_addr >= 0x00007FFFFFFFFFF0:
                        break
                    address = next_addr
                written_count = 0
                for addr in found_addrs:
                    if self.engine.write_bytes_safe(addr, pack_floats):
                        written_count += 1
                logger.info("Iniezione camera live in RAM: trovati %d indirizzi, scritti %d con successo", len(found_addrs), written_count)
                def on_finish():
                    self.btn_inject_cam_ram.config(state=tk.NORMAL, text="⚡ INIETTA LIVE NEL PROCESSO")
                    if written_count > 0:
                        messagebox.showinfo(
                            self.t("title"),
                            f"✅ Iniezione Live RAM completata con successo!\n\n"
                            f"• Valori applicati: Zoom={zoom:.2f}, Altezza={height:.2f}, Angolo={angle:.2f}, FOV={fov:.1f}°\n"
                            f"• Indirizzi RAM aggiornati: {written_count} su {len(found_addrs)} trovati\n"
                            f"• Sincronizzato con sider.ini"
                        )
                    elif len(found_addrs) > 0:
                        messagebox.showwarning(
                            self.t("title"),
                            f"⚠️ Rilevati {len(found_addrs)} blocchi candidati per la telecamera in RAM, ma la scrittura protetta è fallita."
                        )
                    else:
                        messagebox.showwarning(
                            self.t("title"),
                            "⚠️ Nessuna struttura telecamera rilevata nella memoria dinamica del gioco.\n\n"
                            "Assicurati che una partita o la modalità allenamento sia avviata in eFootball prima di iniettare i valori in RAM."
                        )
                self.root.after(0, on_finish)
            except Exception as e:
                logger.exception("Errore durante l'iniezione live della telecamera in RAM")
                def on_err(err=e):
                    self.btn_inject_cam_ram.config(state=tk.NORMAL, text="⚡ INIETTA LIVE NEL PROCESSO")
                    messagebox.showerror(self.t("title"), f"Errore iniezione live telecamera in RAM:\n{err}")
                self.root.after(0, on_err)
        threading.Thread(target=worker, daemon=True).start()
    def refresh_all_labels(self):
        self.root.title(self.t("title"))
        self.lbl_title.config(text=f"⚽ {self.t('title')}")
        self.notebook.tab(0, text=self.t("tab_sniffer"))
        self.notebook.tab(1, text=self.t("tab_hex"))
        self.notebook.tab(2, text=self.t("tab_search"))
        self.notebook.tab(3, text=self.t("tab_mods"))
        self.notebook.tab(4, text=self.t("tab_db_injector"))
        self.notebook.tab(5, text=self.t("tab_camera"))
        self.btn_sniffer.config(text=self.t("btn_stop_sniffer") if self.sniffer_running else self.t("btn_start_sniffer"))
        self.btn_clear_sniffer.config(text=self.t("btn_clear_sniffer"))
        self.lbl_sniffer_filter.config(text=self.t("lbl_filter_sniffer"))
        self.lbl_sniffer_info.config(text=self.t("sniffer_info_active") if self.sniffer_running else self.t("sniffer_info_idle"))
        self.tree_sniffer.heading("time", text=self.t("col_time"), command=lambda: self.sort_sniffer_dataset("time"))
        self.tree_sniffer.heading("cat", text=self.t("col_type"), command=lambda: self.sort_sniffer_dataset("cat"))
        self.tree_sniffer.heading("addr", text=self.t("col_addr"), command=lambda: self.sort_sniffer_dataset("addr"))
        self.tree_sniffer.heading("path", text=self.t("col_path"), command=lambda: self.sort_sniffer_dataset("path"))
        self.btn_inspect.config(text=self.t("btn_inspect_hex"))
        self.btn_create_mod.config(text=self.t("btn_make_mod"))
        self.lbl_hex_addr_title.config(text=self.t("lbl_hex_addr"))
        self.btn_read_hex.config(text=self.t("btn_read_hex"))
        self.btn_save_hex.config(text=self.t("btn_save_hex"))
        self.sub_notebook.tab(0, text=self.t("tab_strings"))
        self.sub_notebook.tab(1, text=self.t("tab_structure"))
        self.sub_notebook.tab(2, text=self.t("tab_palette"))
        self.lbl_search_prompt.config(text=self.t("lbl_search_prompt"))
        self.btn_search.config(text=self.t("btn_search"))
        self.btn_stop.config(text=self.t("btn_stop_search"))
        self.chk_case.config(text=self.t("chk_case"))
        self.lbl_search_info.config(text=self.t("search_hint"))
        self.tree_res.heading("addr", text=self.t("col_addr"), command=lambda: sort_treeview_column(self.tree_res, "addr", False))
        self.tree_res.heading("enc", text=self.t("col_encoding"), command=lambda: sort_treeview_column(self.tree_res, "enc", False))
        self.tree_res.heading("cur", text=self.t("col_path"), command=lambda: sort_treeview_column(self.tree_res, "cur", False))
        self.tree_res.heading("type", text=self.t("col_type"), command=lambda: sort_treeview_column(self.tree_res, "type", False))
        self.tree_res.heading("size", text=self.t("col_size"), command=lambda: sort_treeview_column(self.tree_res, "size", False))
        self.lbl_new_val.config(text=self.t("lbl_new_val"))
        self.btn_inject_one.config(text=self.t("btn_inj_sel"))
        self.btn_inject_ui.config(text=self.t("btn_inj_smart"))
        self.btn_zip.config(text=self.t("btn_install_zip"))
        self.btn_folder.config(text=self.t("btn_open_folder"))
        self.btn_delete.config(text=self.t("btn_del_mod"))
        self.btn_reload.config(text=self.t("btn_reload_mods"))
        self.tree_mods.heading("enabled", text=self.t("col_status"), command=lambda: sort_treeview_column(self.tree_mods, "enabled", False))
        self.tree_mods.heading("name", text=self.t("col_mod_name"), command=lambda: sort_treeview_column(self.tree_mods, "name", False))
        self.tree_mods.heading("category", text=self.t("col_mod_cat"), command=lambda: sort_treeview_column(self.tree_mods, "category", False))
        self.tree_mods.heading("author", text=self.t("col_author"), command=lambda: sort_treeview_column(self.tree_mods, "author", False))
        self.tree_mods.heading("folder", text=self.t("col_folder"), command=lambda: sort_treeview_column(self.tree_mods, "folder", False))
        self.btn_toggle.config(text=self.t("btn_toggle_mod"))
        self.btn_apply_live.config(text=self.t("btn_apply_mod_live"))
        self.btn_sync.config(text=self.t("btn_sync_game"))
        self.tree_db.heading("addr", text=self.t("col_db_addr"), command=lambda: sort_treeview_column(self.tree_db, "addr", False))
        self.tree_db.heading("name", text=self.t("col_db_name"), command=lambda: sort_treeview_column(self.tree_db, "name", False))
        self.tree_db.heading("size", text=self.t("col_db_size"), command=lambda: sort_treeview_column(self.tree_db, "size", False))
        self.tree_db.heading("status", text=self.t("col_db_status"), command=lambda: sort_treeview_column(self.tree_db, "status", False))
        self.tree_rec.heading("rec_id", text="# Record", command=lambda: sort_treeview_column(self.tree_rec, "rec_id", False))
        self.tree_rec.heading("offset", text="Offset", command=lambda: sort_treeview_column(self.tree_rec, "offset", False))
        self.tree_rec.heading("id_val", text="ID / Param", command=lambda: sort_treeview_column(self.tree_rec, "id_val", False))
        self.tree_rec.heading("text_val", text="Testo / Identificatore", command=lambda: sort_treeview_column(self.tree_rec, "text_val", False))
        self.tree_rec.heading("hex_preview", text="Anteprima Hex", command=lambda: sort_treeview_column(self.tree_rec, "hex_preview", False))
        self.load_installed_mods()
    def auto_attach_loop(self):
        if self.engine.check_alive():
            self.lbl_status.config(text=self.t("connected", pid=self.engine.pid), fg="#4ade80")
        else:
            pid = self.engine.find_process()
            if pid:
                ok, msg = self.engine.attach()
                if ok:
                    self.lbl_status.config(text=self.t("connected", pid=self.engine.pid), fg="#4ade80")
                else:
                    self.lbl_status.config(text=self.t("attach_err", pid=pid), fg="#f87171")
            else:
                self.lbl_status.config(text=self.t("waiting"), fg="#fbbf24")
        self.root.after(1500, self.auto_attach_loop)
def main():
    root = tk.Tk()
    app = SiderTorigaGUI(root)
    root.mainloop()
if __name__ == "__main__":
    main()
