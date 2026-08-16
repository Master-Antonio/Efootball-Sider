@echo off
setlocal
cd /d "%~dp0"
title Efootball Sider by Toriga - Installer
color 0a

echo ==============================================================================
echo                      Efootball Sider by Toriga - Installer
echo ==============================================================================
echo.

set "GAME_DIR=A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64"

if not exist "%GAME_DIR%" (
    echo [ERRORE] Cartella di gioco non trovata in:
    echo %GAME_DIR%
    pause
    exit /b 1
)

echo [1/3] Installazione modulo DirectX (dxgi.dll)...
copy /Y "%~dp0dxgi.dll" "%GAME_DIR%\dxgi.dll" >nul

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
