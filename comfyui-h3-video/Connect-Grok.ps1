param([string]$ComfyDir)
$ErrorActionPreference = 'Stop'
$taskComfy = if ($ComfyDir) { $ComfyDir } elseif (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'ComfyUI') -PathType Container) { Join-Path $PSScriptRoot 'ComfyUI' } else { Join-Path $env:USERPROFILE 'ComfyUI' }
$taskHelper = Join-Path (Split-Path -Parent $taskComfy) 'local-prompt-helper'
$taskCli = Join-Path $taskHelper 'grok-cli\bin\grok.exe'
if (-not (Test-Path -LiteralPath $taskCli -PathType Leaf)) {
    & (Join-Path $taskComfy '.venv\Scripts\python.exe') -X utf8 (Join-Path $PSScriptRoot 'scripts\install_grok_cli.py') --comfy $taskComfy
    if ($LASTEXITCODE -ne 0) { throw 'Grok CLI installation failed.' }
}
# The CLI owns login and token refresh. No auth file is read or copied by this script.
$env:GROK_HOME = Join-Path $taskHelper 'grok-account'
$env:GROK_DISABLE_AUTOUPDATER = '1'
Remove-Item Env:XAI_API_KEY -ErrorAction SilentlyContinue
Write-Host 'Sign in with the displayed URL and device code. Do not paste tokens into chat.'
Write-Host 'Check your plan/Build entitlement and privacy settings in Grok before using private text.'
& $taskCli login --device-auth
if ($LASTEXITCODE -ne 0) { throw 'Grok CLI login did not complete.' }
Write-Host 'Login completed. In the H3 prompt helper, select Grok CLI.'
