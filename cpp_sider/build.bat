@echo off
echo ========================================================
echo Compiling C++ DXGI Side Loader for eFootball (x64)
echo ========================================================

where cl >nul 2>nul
if %errorlevel% equ 0 (
    echo [MSVC Detected] Compiling with cl.exe...
    cl /O2 /LD /std:c++17 dxgi.cpp /DEF:dxgi.def /Fe:dxgi.dll /link /MACHINE:X64
    goto done
)

where g++ >nul 2>nul
if %errorlevel% equ 0 (
    echo [MinGW Detected] Compiling with g++...
    g++ -O3 -shared -m64 dxgi.cpp dxgi.def -o dxgi.dll -static -lkernel32
    goto done
)

echo [!] No MSVC (cl.exe) or MinGW (g++) found in PATH.
echo [!] Use the precompiled Rust Sider in ../rust_sider/ or Python Live Sider in ../python_live_sider/

:done
echo Compilation finished.
