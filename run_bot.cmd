@echo off
setlocal

cd /d "%~dp0"
".\.venv\Scripts\python.exe" -u -m src.main
