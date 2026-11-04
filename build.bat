@echo off
cd /d "%~dp0"

echo [1/4] Closing any running Shockwave instances...
taskkill /F /IM Shockwave.exe >nul 2>&1

echo [2/4] Activating virtual environment...
call venv\Scripts\activate
if not exist "venv\Scripts\python.exe" (
    echo ERROR: venv\Scripts\python.exe was not found.
    pause
    exit /b 1
)

echo [3/4] Ensuring PyInstaller is ready...
venv\Scripts\python.exe -m pip install pyinstaller >nul 2>&1

echo [4/4] Building Shockwave (onedir mode)...
venv\Scripts\python.exe -m PyInstaller --noconfirm Shockwave.spec


echo.
if exist "dist\Shockwave\Shockwave.exe" (
    python make_shortcuts.py
    echo =======================================================================
    echo SUCCESS: Build completed! Shortcut is ready in the root:
    echo  - Shockwave.lnk : Control Panel with system tray minimization
    echo =======================================================================
) else (
    echo ERROR: Build failed. Please check the logs above.
)
pause
