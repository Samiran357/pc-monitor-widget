@echo off
REM Builds PCMonitorWidget.exe on your own Windows PC.
REM Requires Python. Result: dist\PCMonitorWidget.exe

echo Installing dependencies...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo Building exe...
python -m PyInstaller --onefile --noconsole --name PCMonitorWidget --hidden-import wmi --hidden-import pythoncom --hidden-import win32com.client pc_widget.py
if errorlevel 1 goto :error

echo.
echo Done! Your file is: dist\PCMonitorWidget.exe
pause
exit /b 0

:error
echo.
echo Build failed. See the messages above.
pause
exit /b 1
