@echo off
setlocal
cd /d "%~dp0"
title Efootball Sider by Toriga - Disinstallatore
color 0c

echo ==============================================================================
echo                      Efootball Sider by Toriga - Disinstallatore
echo ==============================================================================
echo.

call "%~dp0scripts\resolve_game_dir.bat"

if errorlevel 1 (
	echo [ERRORE] Installazione eFootball non trovata.
	echo Imposta EFOOTBALL_GAME_DIR sulla cartella principale del gioco e riprova.
	pause
	exit /b 1
)

echo Rimozione modulo Sider (dxgi.dll)...
if exist "%GAME_DIR%\dxgi.dll" del /F /Q "%GAME_DIR%\dxgi.dll"

echo Rimozione configurazione (sider.ini)...
if exist "%GAME_DIR%\sider.ini" del /F /Q "%GAME_DIR%\sider.ini"

echo Rimozione cartella Mod (content)...
if exist "%GAME_DIR%\content" rmdir /S /Q "%GAME_DIR%\content"

echo.
echo ==============================================================================
echo [SUCCESSO] Sider rimosso completamente. Il gioco e tornato originale.
echo ==============================================================================
pause
