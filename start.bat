@echo off
chcp 65001 >nul
cd /d "%~dp0"
call venv\Scripts\activate
set PYTHONPATH=%~dp0src;%PYTHONPATH%
python src\launcher.py
pause
