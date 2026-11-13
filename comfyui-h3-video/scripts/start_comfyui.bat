@echo off
rem ComfyUI 실행 (이 파일은 setup.ps1 이 ComfyUI 폴더에 복사함). 로컬 전용 127.0.0.1:8188
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8
".venv\Scripts\python.exe" main.py --listen 127.0.0.1 --port 8188 --disable-auto-launch
