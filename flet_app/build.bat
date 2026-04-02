@echo off
echo === Building Flet File Search App ===
echo.
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Building exe...
flet build windows
echo.
echo Done! Find the exe in: build\windows\
pause
