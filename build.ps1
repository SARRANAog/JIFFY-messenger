$ErrorActionPreference = "Stop"

if (!(Test-Path ".venv")) {
  python -m venv .venv
}

.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt

# генерим ico из web/logo.png
.\.venv\Scripts\python.exe tools\make_icon.py

if (Test-Path "dist") { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }

.\.venv\Scripts\pyinstaller.exe `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "JIFFY" `
  --icon "assets\jiffy.ico" `
  --add-data "web;web" `
  --add-data "assets;assets" `
  client-webview.py

Write-Host ""
Write-Host "DONE. EXE: dist\JIFFY.exe"
