param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
New-Item -ItemType Directory -Path (Join-Path $taskRoot 'logs') -Force | Out-Null
$taskComfy = Join-Path $taskRoot 'ComfyUI'
$taskPython = Join-Path $taskComfy '.venv\Scripts\python.exe'
$taskSpecs = (Get-Content (Join-Path $taskRoot 'models.json') -Raw -Encoding UTF8 | ConvertFrom-Json).files
$taskMissing = @($taskSpecs | Where-Object {
    if (-not $_.required) { return $false }
    $taskPath = Join-Path (Join-Path $taskComfy $_.dest) $_.filename
    -not (Test-Path -LiteralPath $taskPath) -or (Get-Item -LiteralPath $taskPath).Length -ne $_.size
})
if ($taskMissing.Count) {
    $taskMissing | ForEach-Object { Write-Host ('Missing model: ' + $_.filename) -ForegroundColor Yellow }
    throw 'Download the missing model into Downloads, then run Complete-Models.ps1.'
}
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
foreach ($taskPort in @(8188, 8190)) {
    $taskListener = Get-NetTCPConnection -LocalPort $taskPort -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($null -eq $taskListener) { continue }
    $taskOwner = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)"
    $taskParent = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskOwner.ParentProcessId)"
    if ($taskOwner.ExecutablePath -notlike "$taskComfy\*" -and $taskParent.ExecutablePath -notlike "$taskComfy\*") {
        throw "Port $taskPort is used by another application. Stop that application first."
    }
}
$taskReady = $false
try { $taskReady = (Invoke-RestMethod 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2).system.comfyui_version -eq '0.45.0' } catch {}
if (-not $taskReady) {
    $taskArguments = @('main.py', '--listen', '127.0.0.1', '--port', '8188', '--disable-auto-launch')
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $taskComfy -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot 'logs\comfyui.log') -RedirectStandardError (Join-Path $taskRoot 'logs\comfyui-error.log') -PassThru
    $taskProcess.Id | Set-Content (Join-Path $taskRoot 'logs\comfyui.pid')
    for ($taskAttempt = 0; $taskAttempt -lt 120; $taskAttempt++) {
        Start-Sleep -Seconds 1
        if ($taskProcess.HasExited) { throw 'ComfyUI stopped. See logs\comfyui-error.log.' }
        try { $taskReady = (Invoke-RestMethod 'http://127.0.0.1:8188/system_stats' -TimeoutSec 2).system.comfyui_version -eq '0.45.0' } catch {}
        if ($taskReady) { break }
    }
    if (-not $taskReady) { throw 'ComfyUI is still starting. See logs\comfyui-error.log.' }
}
$taskUiReady = $false
try { $taskUiReady = (Invoke-WebRequest 'http://127.0.0.1:8190/' -UseBasicParsing -TimeoutSec 2).StatusCode -eq 200 } catch {}
if (-not $taskUiReady) {
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-X', 'utf8', 'server.py') -WorkingDirectory (Join-Path $taskComfy 'simple_ui') -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot 'logs\simple-ui.log') -RedirectStandardError (Join-Path $taskRoot 'logs\simple-ui-error.log') -PassThru
    $taskProcess.Id | Set-Content (Join-Path $taskRoot 'logs\simple-ui.pid')
}
if (-not $NoBrowser) { Start-Process 'http://127.0.0.1:8190/' }
Write-Output 'H3 Video: http://127.0.0.1:8190/'
