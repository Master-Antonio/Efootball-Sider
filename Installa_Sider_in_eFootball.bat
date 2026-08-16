@echo off
setlocal
cd /d "%~dp0"
title Efootball Sider by Toriga - Installer
color 0a

echo ==============================================================================
echo                      Efootball Sider by Toriga - Installer
echo ==============================================================================
echo.

call "%~dp0scripts\resolve_game_dir.bat"

if errorlevel 1 (
    echo [ERRORE] Installazione eFootball non trovata.
    echo Imposta EFOOTBALL_GAME_DIR sulla cartella principale del gioco e riprova.
    pause
    exit /b 1
)

echo [1/3] Installazione modulo DirectX (dxgi.dll)...
set "SIDER_DLL=%~dp0dxgi.dll"
if exist "%~dp0rust_sider\target\release\dxgi.dll" set "SIDER_DLL=%~dp0rust_sider\target\release\dxgi.dll"
if not exist "%SIDER_DLL%" (
    echo [ERRORE] dxgi.dll non trovato. Esegui cargo build --release in rust_sider.
    pause
    exit /b 1
)
copy /Y "%SIDER_DLL%" "%GAME_DIR%\dxgi.dll" >nul

echo [2/3] Sincronizzazione configurazione (sider.ini)...
copy /Y "%~dp0sider.ini" "%GAME_DIR%\sider.ini" >nul

echo [3/3] Sincronizzazione pacchetti Mod (content)...
if not exist "%GAME_DIR%\content" mkdir "%GAME_DIR%\content"
xcopy "%~dp0content" "%GAME_DIR%\content" /E /I /Y /Q >nul

echo.
echo ==============================================================================
echo [SUCCESSO] Sider e Mod installati correttamente in eFootball!
echo Avvia il gioco normalmente da Steam.
echo ==============================================================================
pause
