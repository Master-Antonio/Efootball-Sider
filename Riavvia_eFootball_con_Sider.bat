@echo off
title Riavvio e Aggiornamento eFootball Sider
color 0A

echo ==============================================================================
echo  Aggiornamento e Riavvio Sider in eFootball (Steam)
echo ==============================================================================
echo.

echo 1. Chiusura del processo eFootball in corso...
taskkill /F /IM eFootball.exe >nul 2>&1
timeout /t 2 /nobreak >nul

set "GAME_DIR=A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64"

if not exist "%GAME_DIR%" (
    echo ERRORE: Cartella di gioco non trovata in:
    echo %GAME_DIR%
    pause
    exit /b 1
)

echo 2. Copia dei file Sider aggiornati...
copy /Y "rust_sider\target\release\dxgi.dll" "%GAME_DIR%\dxgi.dll"
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
