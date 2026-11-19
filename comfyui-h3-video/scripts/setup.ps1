# ComfyUI + DaSiWa MiniMax H3 + 간단 화면 설치 (Windows, NVIDIA GPU)
#
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1                     # 기본: %USERPROFILE%\ComfyUI
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -ComfyDir D:\ComfyUI
#
# 하는 일: ComfyUI 를 versions.json 의 커밋으로 받기 → .venv(Python 3.12) → PyTorch cu130 →
#          ComfyUI 요구 패키지 → 커스텀 노드 3개(고정 커밋) → simple_ui 복사 → 실행 파일 복사.
# 모델은 받지 않는다(다음 단계: python scripts\get_models.py --comfy <ComfyDir>).
# 이미 있는 폴더는 지우지 않고 커밋만 맞춘다. 사용자 데이터(cards.json·presets.json)는 덮어쓰지 않는다.
param(
    [string]$ComfyDir = "$env:USERPROFILE\ComfyUI",
    [switch]$SkipTorch
)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$V = Get-Content "$Root\versions.json" -Raw -Encoding UTF8 | ConvertFrom-Json

function Step($t) { Write-Host "`n== $t" -ForegroundColor Cyan }
function Need($cmd, $hint) { if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) { throw "$cmd 가 없습니다. $hint" } }
function Invoke-Git { & git.exe @args; if ($LASTEXITCODE -ne 0) { throw "git $args 실패" } }

Need git "https://git-scm.com 에서 설치하세요."
$UseUv = [bool](Get-Command uv -ErrorAction SilentlyContinue)
if (-not $UseUv) { Need py "Python 3.12 (python.org, 'py launcher' 포함) 또는 uv 를 설치하세요." }

Step "ComfyUI 받기 ($($V.comfyui.commit.Substring(0,10)))"
if (-not (Test-Path "$ComfyDir\.git")) { Invoke-Git clone $V.comfyui.repo $ComfyDir }
Invoke-Git -C $ComfyDir fetch --quiet origin
Invoke-Git -C $ComfyDir checkout --quiet $V.comfyui.commit

Step "가상환경 (.venv, Python $($V.python))"
$Py = "$ComfyDir\.venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    if ($UseUv) { & uv venv --python $V.python "$ComfyDir\.venv" } else { & py "-$($V.python)" -m venv "$ComfyDir\.venv" }
    if (-not (Test-Path $Py)) { throw "가상환경을 만들지 못했습니다." }
}
function Pip { if ($UseUv) { & uv pip install --python $Py @args } else { & $Py -m pip install @args }; if ($LASTEXITCODE -ne 0) { throw "pip install $args 실패" } }
if (-not $UseUv) { & $Py -m pip install --upgrade pip | Out-Null }

if (-not $SkipTorch) {
    Step "PyTorch ($($V.torch.packages -join ', '))"
    $torchArgs = @($V.torch.packages) + @("--index-url", $V.torch.index_url)
    Pip @torchArgs
}

Step "ComfyUI 요구 패키지"
Pip -r "$ComfyDir\requirements.txt"

foreach ($n in $V.custom_nodes) {
    Step "커스텀 노드 $($n.name) ($($n.commit.Substring(0,7)))"
    $d = "$ComfyDir\custom_nodes\$($n.name)"
    if (-not (Test-Path "$d\.git")) { Invoke-Git clone $n.repo $d }
    Invoke-Git -C $d fetch --quiet origin
    Invoke-Git -C $d checkout --quiet $n.commit
    $req = "$d\requirements.txt"
    if (Test-Path $req) {
        $skip = @($n.skip_requirements | Where-Object { $_ })
        $lines = Get-Content $req | Where-Object { $_.Trim() -and -not $_.Trim().StartsWith("#") } |
                 Where-Object { $l = $_; -not ($skip | Where-Object { $l -match "^\s*$([regex]::Escape($_))" }) }
        $tmp = (New-TemporaryFile).FullName
        $lines | Set-Content $tmp -Encoding ASCII
        Pip -r $tmp
        Remove-Item $tmp
    }
}

Step "CPU 얼굴 검출 준비"
Pip "opencv-python>=5,<6"
& $Py "$Root\scripts\install_face_detector.py" --comfy $ComfyDir
if ($LASTEXITCODE -ne 0) { throw "CPU 얼굴 검출 모델 설치 실패" }

Step "간단 화면(simple_ui) 복사"
& $Py "$Root\scripts\install_queue_pause.py" --comfy $ComfyDir
if ($LASTEXITCODE -ne 0) { throw "대기열 일시정지 확장 설치 실패" }
$ui = "$ComfyDir\simple_ui"
New-Item -ItemType Directory -Force $ui | Out-Null
$publicUiFiles = @(
    'server.py', 'index.html', 'start.bat', 'template_api.json', 'queue-pause.js',
    'bulk_progress.py', 'bulk-progress.js', 'queue_bulk.py', 'person_framing.py',
    'cards.seed.json', 'presets.seed.json', 'prompt_helper.py', 'grok_cli.py',
    'production_assistant.py', 'production_assistant.js', 'local_translate.py', 'translation_worker.py',
    'story.py', 'story_workflow.py', 'story.html', 'gallery.py', 'gallery.html', 'face_references.py'
)
foreach ($publicUiFile in $publicUiFiles) {
    Copy-Item -LiteralPath (Join-Path "$Root\simple_ui" $publicUiFile) -Destination $ui -Force
}
Copy-Item "$Root\scripts\start_comfyui.bat" $ComfyDir -Force

Step "끝"
Write-Host @"
다음 순서:
  1) 모델 받기:   python "$Root\scripts\get_models.py" --comfy "$ComfyDir"
     (Civitai 파일은 출력되는 링크로 브라우저에서 받은 뒤 같은 명령을 다시 실행)
  2) ComfyUI 켜기: "$ComfyDir\start_comfyui.bat"
  3) 간단 화면:    "$ComfyDir\simple_ui\start.bat"  → http://127.0.0.1:8190
"@
