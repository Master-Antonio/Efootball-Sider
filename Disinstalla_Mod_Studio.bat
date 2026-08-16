@echo off
setlocal
cd /d "%~dp0"
title eFootball Mod Studio - Disinstallatore
color 0c

echo ==============================================================================
echo                      eFootball Mod Studio - Disinstallatore
echo ==============================================================================
echo.

call "%~dp0scripts\resolve_game_dir.bat"

if errorlevel 1 (
	echo [ERRORE] Installazione eFootball non trovata.
	echo Imposta EFOOTBALL_GAME_DIR sulla cartella principale del gioco e riprova.
	pause
	exit /b 1
)

rem %GAME_DIR% is the Win64 binaries folder; the game root is three levels up.
for %%I in ("%GAME_DIR%\..\..\..") do set "GAME_ROOT=%%~fI"

echo Rimozione modulo Mod Studio (dxgi.dll)...
if exist "%GAME_DIR%\dxgi.dll" del /F /Q "%GAME_DIR%\dxgi.dll"

echo Rimozione configurazione (modstudio.ini / sider.ini)...
if exist "%GAME_DIR%\modstudio.ini" del /F /Q "%GAME_DIR%\modstudio.ini"
if exist "%GAME_DIR%\sider.ini" del /F /Q "%GAME_DIR%\sider.ini"

echo Rimozione log di Mod Studio...
if exist "%GAME_DIR%\sider_rust.log" del /F /Q "%GAME_DIR%\sider_rust.log"
if exist "%GAME_ROOT%\sider_rust.log" del /F /Q "%GAME_ROOT%\sider_rust.log"
if exist "%GAME_ROOT%\camera_sentinel.log" del /F /Q "%GAME_ROOT%\camera_sentinel.log"

rem Residuo dei vecchi installer che copiavano content sotto Win64.
if exist "%GAME_DIR%\content" rmdir /S /Q "%GAME_DIR%\content"

if not exist "%GAME_ROOT%\content" goto :content_done
echo.
echo La cartella mod "%GAME_ROOT%\content" contiene i pacchetti installati.
set /p "DEL_CONTENT=Vuoi eliminarla insieme a Mod Studio? [S/N, default N]: "
if /I "%DEL_CONTENT%"=="S" rmdir /S /Q "%GAME_ROOT%\content"
if /I "%DEL_CONTENT%"=="Y" rmdir /S /Q "%GAME_ROOT%\content"
:content_done

echo.
echo ==============================================================================
echo [SUCCESSO] Mod Studio rimosso completamente. Il gioco e tornato originale.
echo ==============================================================================
pause
