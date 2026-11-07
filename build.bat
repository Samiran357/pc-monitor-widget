@echo off
REM Builds PCMonitorWidget.exe on your own Windows PC.
REM Needs: Python, and the GitHub CLI (https://cli.github.com) signed in once with "gh auth login".
REM Result: dist\PCMonitorWidget.exe  (everything is bundled inside)

echo Downloading sensor helpers...
powershell -NoProfile -ExecutionPolicy Bypass -File get_vendor.ps1
if errorlevel 1 goto :error

echo Installing Python packages...
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 goto :error

echo Building exe...
python -m PyInstaller --onefile --noconsole --name PCMonitorWidget --add-data "vendor;vendor" --hidden-import wmi --hidden-import pythoncom --hidden-import win32com.client pc_widget.py
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
