$ErrorActionPreference = 'Stop'
foreach ($taskName in @('simple-ui', 'comfyui')) {
    $taskPidFile = Join-Path $PSScriptRoot "logs\$taskName.pid"
    if (-not (Test-Path -LiteralPath $taskPidFile)) { continue }
    $taskProcessId = [int](Get-Content -LiteralPath $taskPidFile)
    $taskProcess = Get-CimInstance Win32_Process -Filter "ProcessId=$taskProcessId"
    if ($null -eq $taskProcess) { continue }
    if ($taskProcess.ExecutablePath -like (Join-Path $PSScriptRoot 'ComfyUI\*')) {
        Get-CimInstance Win32_Process -Filter "ParentProcessId=$taskProcessId" | ForEach-Object { Stop-Process -Id $_.ProcessId }
        Stop-Process -Id $taskProcessId -ErrorAction SilentlyContinue
    }
}
