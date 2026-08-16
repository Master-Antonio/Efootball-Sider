@echo off
setlocal
cd /d "%~dp0"
title Riavvio e Aggiornamento eFootball Mod Studio
color 0A

echo ==============================================================================
echo  Aggiornamento e Riavvio Mod Studio in eFootball (Steam)
echo ==============================================================================
echo.

echo 1. Chiusura del processo eFootball in corso...
taskkill /F /IM eFootball.exe >nul 2>&1

call "%~dp0scripts\resolve_game_dir.bat"

if errorlevel 1 (
    echo ERRORE: installazione eFootball non trovata.
    echo Imposta EFOOTBALL_GAME_DIR sulla cartella principale del gioco e riprova.
    pause
    exit /b 1
)

echo 2. Copia dei file Mod Studio aggiornati...
rem %GAME_DIR% is the Win64 binaries folder; the game root is three levels up.
for %%I in ("%GAME_DIR%\..\..\..") do set "GAME_ROOT=%%~fI"
set "SIDER_DLL=%~dp0dxgi.dll"
if exist "%~dp0rust_sider\target\release\dxgi.dll" set "SIDER_DLL=%~dp0rust_sider\target\release\dxgi.dll"
copy /Y "%SIDER_DLL%" "%GAME_DIR%\dxgi.dll"
if exist "modstudio.ini" copy /Y "modstudio.ini" "%GAME_DIR%\modstudio.ini"
if exist "sider.ini" copy /Y "sider.ini" "%GAME_DIR%\sider.ini"
if exist "content" (
    if not exist "%GAME_ROOT%\content" mkdir "%GAME_ROOT%\content"
    xcopy /E /I /Y "content" "%GAME_ROOT%\content" >nul 2>&1
)
rem Clean up a legacy copy placed under Win64 by older scripts.
if exist "%GAME_DIR%\content" rmdir /S /Q "%GAME_DIR%\content"

echo.
echo ==============================================================================
echo  Installazione completata con successo!
echo  Avvio del gioco tramite Steam in corso...
echo ==============================================================================
echo.

start steam://rungameid/1665460
