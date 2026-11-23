param([string]$ComfyDir, [switch]$All)
$ErrorActionPreference = 'Stop'
$taskComfy = if ($ComfyDir) { $ComfyDir } elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'ComfyUI') -PathType Container) { Join-Path $PSScriptRoot 'ComfyUI' } else { Join-Path $env:USERPROFILE 'ComfyUI' }
$taskPython = Join-Path $taskComfy '.venv\Scripts\python.exe'
$env:PYTHONIOENCODING = 'utf-8'
$taskArguments = @((Join-Path $PSScriptRoot 'scripts\get_models.py'), '--comfy', $taskComfy)
if ($All) { $taskArguments += '--all' }
& $taskPython @taskArguments
if ($LASTEXITCODE -ne 0) { throw 'Some required models are still missing or failed SHA256 verification.' }
Write-Host 'All required models passed SHA256 verification. Run Start-H3-Video.ps1.'
