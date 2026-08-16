#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fstream>
#include <string>
#include <vector>
#include <thread>
#include <chrono>

static HMODULE g_real_dxgi = NULL;
static uintptr_t g_my_base = 0;
static uintptr_t g_my_size = 0x400000;

void LogMsg(const std::string& msg) {
    std::ofstream ofs("sider_dxgi.log", std::ios::app);
    if (ofs.is_open()) {
        ofs << "[CPP_SIDER] " << msg << "\n";
    }
}

HMODULE GetRealDXGI() {
    if (!g_real_dxgi) {
        g_real_dxgi = LoadLibraryA("C:\\Windows\\System32\\dxgi.dll");
        LogMsg("Loaded real System32 dxgi.dll");
    }
    return g_real_dxgi;
}

FARPROC GetProc(const char* name) {
    return GetProcAddress(GetRealDXGI(), name);
}

// DirectX exports
extern "C" {
    HRESULT WINAPI CreateDXGIFactory(REFIID riid, void** ppFactory) {
        typedef HRESULT(WINAPI* Func)(REFIID, void**);
        Func f = (Func)GetProc("CreateDXGIFactory");
        return f ? f(riid, ppFactory) : E_FAIL;
    }
    HRESULT WINAPI CreateDXGIFactory1(REFIID riid, void** ppFactory) {
        typedef HRESULT(WINAPI* Func)(REFIID, void**);
        Func f = (Func)GetProc("CreateDXGIFactory1");
        return f ? f(riid, ppFactory) : E_FAIL;
    }
    HRESULT WINAPI CreateDXGIFactory2(UINT Flags, REFIID riid, void** ppFactory) {
        typedef HRESULT(WINAPI* Func)(UINT, REFIID, void**);
        Func f = (Func)GetProc("CreateDXGIFactory2");
        return f ? f(Flags, riid, ppFactory) : E_FAIL;
    }
}

struct Replacement {
    std::string from_ascii;
    std::string to_ascii;
    std::wstring from_utf16;
    std::wstring to_utf16;
    std::string name;
};

std::vector<Replacement> GetReplacements() {
    std::vector<std::pair<std::string, std::string>> raw = {
        {"PIEMONTE BN", "JUVENTUS FC"},
        {"Piemonte BN", "Juventus FC"},
        {"PIEMONTE", "JUVENTUS"},
        {"Piemonte", "Juventus"},
        {"PM BLACK WHITE", "JUVENTUS FC   "},
        {"MADRID CHAMARTIN B", "REAL MADRID CF    "},
        {"Madrid Chamartin B", "Real Madrid CF    "},
        {"MADRID CHAMARTIN", "REAL MADRID CF  "},
        {"MADRID ROSAS RB", "ATLETICO MADRID"},
        {"LONDON FC", "CHELSEA  "},
        {"MAN BLUE", "MAN CITY"},
        {"LOMBARDIA NA", "INTER MILAN "},
        {"BERGAMO NA", "ATALANTA  "},
        {"PIEDMONT MAROON", "TORINO FC      "},
        {"TORINO G", "TORINO FC"},
        {"TUSCANY PURPLE", "FIORENTINA    "},
        {"EMILIA RED", "BOLOGNA FC"},
        {"EMILIA GREEN", "SASSUOLO    "},
        {"BRIANZA RED", "AC MONZA   "},
        {"LIGURIA RED BLUE", "GENOA CFC       "},
        {"FRIULI BLACK WHITE", "UDINESE           "},
        {"SARDEGNA RED BLUE", "CAGLIARI         "},
        {"TUSCANY BLUE", "EMPOLI FC   "},
        {"VENETO YELLOW BLUE", "HELLAS VERONA     "},
        {"CIOCIARIA YELLOW BLUE", "FROSINONE            "},
        {"CAMPANIA MAROON", "SALERNITANA    "},
        {"SALENTO YELLOW RED", "US LECCE          "}
    };

    std::vector<Replacement> result;
    for (const auto& p : raw) {
        Replacement r;
        r.from_ascii = p.first;
        size_t len = p.first.length();
        std::string t = p.second;
        if (t.length() < len) t.append(len - t.length(), ' ');
        else if (t.length() > len) t = t.substr(0, len);
        r.to_ascii = t;

        r.from_utf16 = std::wstring(p.first.begin(), p.first.end());
        r.to_utf16 = std::wstring(t.begin(), t.end());
        r.name = p.first + " -> " + t;
        result.push_back(r);
    }
    return result;
}

void ScanAndPatchMemory(const std::vector<Replacement>& reps) {
    uintptr_t address = 0x10000;
    MEMORY_BASIC_INFORMATION mbi;
    int patched = 0;

    while (VirtualQuery((LPCVOID)address, &mbi, sizeof(mbi))) {
        uintptr_t base = (uintptr_t)mbi.BaseAddress;
        bool in_proxy = (g_my_base > 0 && base >= g_my_base && base < (g_my_base + g_my_size));

        bool is_readable = !in_proxy && (mbi.State == MEM_COMMIT)
            && !(mbi.Protect & PAGE_GUARD)
            && !(mbi.Protect & PAGE_NOACCESS)
            && ((mbi.Protect & (PAGE_READONLY | PAGE_READWRITE | PAGE_WRITECOPY | PAGE_EXECUTE_READ | PAGE_EXECUTE_READWRITE | PAGE_EXECUTE_WRITECOPY)) != 0);

        if (is_readable && mbi.RegionSize > 0 && mbi.RegionSize <= 512 * 1024 * 1024) {
            uint8_t* p = (uint8_t*)mbi.BaseAddress;
            size_t size = mbi.RegionSize;

            for (const auto& rep : reps) {
                // ASCII
                size_t flen = rep.from_ascii.size();
                if (size >= flen) {
                    for (size_t i = 0; i + flen <= size; ) {
                        if (memcmp(p + i, rep.from_ascii.data(), flen) == 0) {
                            DWORD oldProtect;
                            if (VirtualProtect(p + i, flen, PAGE_EXECUTE_READWRITE, &oldProtect)) {
                                memcpy(p + i, rep.to_ascii.data(), flen);
                                VirtualProtect(p + i, flen, oldProtect, &oldProtect);
                                patched++;
                            }
                            i += flen;
                        } else {
                            i++;
                        }
                    }
                }
            }
        }

        uintptr_t next = base + mbi.RegionSize;
        if (next <= address || next >= 0x00007FFFFFFFFFF0) break;
        address = next;
    }
}

void WorkerThread() {
    LogMsg("Worker thread started.");
    auto reps = GetReplacements();
    std::this_thread::sleep_for(std::chrono::seconds(2));

    while (true) {
        ScanAndPatchMemory(reps);
        std::this_thread::sleep_for(std::chrono::milliseconds(1000));
    }
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        g_my_base = (uintptr_t)hinstDLL;
        LogMsg("CPP Sider DLL_PROCESS_ATTACH");
        std::thread(WorkerThread).detach();
    }
    return TRUE;
}
