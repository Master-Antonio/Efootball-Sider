@echo off
setlocal
cd /d "%~dp0"
title Riavvio e Aggiornamento eFootball Sider
color 0A

echo ==============================================================================
echo  Aggiornamento e Riavvio Sider in eFootball (Steam)
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

echo 2. Copia dei file Sider aggiornati...
set "SIDER_DLL=%~dp0dxgi.dll"
if exist "%~dp0rust_sider\target\release\dxgi.dll" set "SIDER_DLL=%~dp0rust_sider\target\release\dxgi.dll"
copy /Y "%SIDER_DLL%" "%GAME_DIR%\dxgi.dll"
copy /Y "sider.ini" "%GAME_DIR%\sider.ini"
if exist "content" (
    xcopy /E /I /Y "content" "%GAME_DIR%\content" >nul 2>&1
)

echo.
echo ==============================================================================
echo  Installazione completata con successo!
echo  Avvio del gioco tramite Steam in corso...
echo ==============================================================================
echo.

start steam://rungameid/1665460
