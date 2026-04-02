@echo off
echo === Building PySide6 File Search App ===
echo.
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller
echo.
echo Building exe...
pyinstaller --onefile --windowed --name "FileSearch-Qt" --icon=NONE main.py
echo.
echo Done! Find the exe in: dist\FileSearch-Qt.exe
pause
