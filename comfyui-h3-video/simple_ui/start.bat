@echo off
rem DaSiWa 간단 화면 실행 (ComfyUI 8188 이 먼저 켜져 있어야 함)
cd /d "%~dp0"
start "" http://127.0.0.1:8190
"%~dp0..\.venv\Scripts\python.exe" -X utf8 server.py
