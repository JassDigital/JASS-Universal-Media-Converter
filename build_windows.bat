@echo off
cd /d "%~dp0"
py -3 -m pip install -r requirements.txt pyinstaller
py -3 -m PyInstaller --noconfirm --clean --windowed --name "JASS Universal Media Converter" main.py
echo Build completed in dist\
pause
