param()
$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskComfy = Join-Path $taskRoot 'ComfyUI'
$taskUi = Join-Path $taskComfy 'simple_ui'
$taskPython = Join-Path $taskComfy '.venv\Scripts\python.exe'
& $taskPython (Join-Path $taskRoot 'scripts\prepare_ui_restart.py')
if ($LASTEXITCODE -ne 0) { throw 'UI restart preparation failed; no process was stopped.' }
$taskListener = Get-NetTCPConnection -LocalPort 8190 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if ($taskListener) {
    $taskOwner = Get-CimInstance Win32_Process -Filter "ProcessId=$($taskListener.OwningProcess)"
    if ($taskOwner.CommandLine -notmatch 'server\.py') { throw 'Port 8190 is not the UI server.' }
    Stop-Process -Id $taskListener.OwningProcess
    for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
        if (-not (Get-NetTCPConnection -LocalPort 8190 -State Listen -ErrorAction SilentlyContinue)) { break }
        Start-Sleep -Milliseconds 100
    }
}
$taskPreviousRestartState = $env:SIMPLEUI_RESTART_STATE
$env:SIMPLEUI_RESTART_STATE = Join-Path $taskUi 'ui-restart-state.tmp'
$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
New-Item -ItemType Directory -Force -Path (Join-Path $taskRoot 'logs') | Out-Null
try {
    $taskProcess = Start-Process -FilePath $taskPython -ArgumentList @('-X', 'utf8', 'server.py') -WorkingDirectory $taskUi -WindowStyle Hidden -RedirectStandardOutput (Join-Path $taskRoot 'logs\simple-ui-face-crop.log') -RedirectStandardError (Join-Path $taskRoot 'logs\simple-ui-face-crop-error.log') -PassThru
    $taskProcess.Id | Set-Content -LiteralPath (Join-Path $taskRoot 'logs\simple-ui.pid')
} finally {
    if ($null -eq $taskPreviousRestartState) { Remove-Item Env:SIMPLEUI_RESTART_STATE -ErrorAction SilentlyContinue }
    else { $env:SIMPLEUI_RESTART_STATE = $taskPreviousRestartState }
}
for ($taskAttempt = 0; $taskAttempt -lt 30; $taskAttempt++) {
    Start-Sleep -Milliseconds 500
    try {
        $taskHealth = Invoke-RestMethod 'http://127.0.0.1:8190/api/health' -TimeoutSec 2
        if ($taskHealth.ok -and $taskHealth.sequence_face_crop) {
            Write-Output 'UI updated. Refresh the existing page. ComfyUI and its queue were not restarted.'
            exit 0
        }
    } catch {}
}
throw 'UI health check failed.'
