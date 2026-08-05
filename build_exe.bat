@echo off
title FoxBox Build
echo Building standalone FoxBox.exe (Python + all libraries bundled)...

python -m pip install --quiet pyinstaller pillow hachoir
python -m PyInstaller --noconfirm --onefile --windowed --name FoxBox --icon foxbox.ico --add-data "foxbox.ico;." camera_ingest.py

echo.
echo Done. The standalone app is at: dist\FoxBox.exe
pause
