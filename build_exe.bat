@echo off
setlocal
set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

"%PY%" -m pip install --upgrade pyinstaller
if errorlevel 1 exit /b 1

"%PY%" -m PyInstaller ^
  --noconfirm --clean --onefile --windowed ^
  --name TAOS ^
  --icon assets\icon.ico ^
  --add-data "html.html;." ^
  --collect-all webview ^
  --collect-all pythonnet ^
  --collect-all clr_loader ^
  --hidden-import webview.platforms.edgechromium ^
  --hidden-import webview.platforms.winforms ^
  main.py
if errorlevel 1 exit /b 1

if not exist dist\TAOS.exe (
  echo Build failed: dist\TAOS.exe missing.
  exit /b 1
)

echo.
echo Built dist\TAOS.exe
