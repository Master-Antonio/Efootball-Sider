@echo off
set "GAME_DIR="

if defined EFOOTBALL_GAME_DIR (
    if exist "%EFOOTBALL_GAME_DIR%\eFootball\Binaries\Win64" set "GAME_DIR=%EFOOTBALL_GAME_DIR%\eFootball\Binaries\Win64"
    if exist "%EFOOTBALL_GAME_DIR%\eFootball.exe" set "GAME_DIR=%EFOOTBALL_GAME_DIR%"
)

if not defined GAME_DIR if exist "A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64" set "GAME_DIR=A:\SteamLibrary\steamapps\common\eFootball\eFootball\Binaries\Win64"
if not defined GAME_DIR if exist "C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64" set "GAME_DIR=C:\Program Files (x86)\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64"
if not defined GAME_DIR if exist "C:\Program Files\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64" set "GAME_DIR=C:\Program Files\Steam\steamapps\common\eFootball\eFootball\Binaries\Win64"

if not defined GAME_DIR exit /b 1
exit /b 0