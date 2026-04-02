@echo off
echo === Building Flet File Search App (PyInstaller) ===
echo.
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller
echo.
echo Building exe...
pyinstaller --onefile --windowed --name "FileSearch-Flet" --icon=NONE main.py
echo.
echo Done! Find the exe in: dist\FileSearch-Flet.exe
pause
