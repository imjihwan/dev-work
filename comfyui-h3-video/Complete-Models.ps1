$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot 'ComfyUI\.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
& $taskPython (Join-Path $PSScriptRoot 'scripts\get_models.py') --comfy (Join-Path $PSScriptRoot 'ComfyUI') --all
if ($LASTEXITCODE -ne 0) { throw 'Some required models are still missing or failed SHA256 verification.' }
Write-Host 'All required models passed SHA256 verification. Run Start-H3-Video.ps1.'
