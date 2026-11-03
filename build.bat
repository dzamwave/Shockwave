@echo off
cd /d "%~dp0"

echo [1/4] Closing any running Shockwave instances...
taskkill /F /IM Shockwave.exe >nul 2>&1

echo [2/4] Activating virtual environment...
call venv\Scripts\activate

echo [3/4] Ensuring PyInstaller is ready...
python -m pip install pyinstaller >nul 2>&1

echo [4/4] Building Shockwave (onedir mode)...
python -m PyInstaller --name Shockwave --onedir --console --icon=icons\icon.ico --paths=src --add-data "icons;icons" --add-data "alert;alert" --add-data "config/prompts;config/prompts" --collect-all faster_whisper --collect-all vosk --copy-metadata faster-whisper --copy-metadata vosk --hidden-import faster_whisper --hidden-import vosk --hidden-import huggingface_hub --hidden-import sounddevice --hidden-import soundfile --hidden-import keyboard --hidden-import tkinter src\launcher.py


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
