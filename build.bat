@echo off
setlocal enabledelayedexpansion

if not exist .venv (
  python -m venv .venv
)

call .venv\Scripts\python.exe -m pip install --upgrade pip
call .venv\Scripts\python.exe -m pip install -r requirements.txt

call .venv\Scripts\python.exe tools\make_icon.py

if exist dist rmdir /s /q dist
if exist build rmdir /s /q build

call .venv\Scripts\pyinstaller.exe ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "JIFFY" ^
  --icon "assets\jiffy.ico" ^
  --add-data "web;web" ^
  --add-data "assets;assets" ^
  client-webview.py

echo.
echo DONE. EXE: dist\JIFFY.exe
pause
