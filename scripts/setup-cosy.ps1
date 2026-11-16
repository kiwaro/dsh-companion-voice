$ErrorActionPreference = 'Stop'
$env:UV_HTTP_TIMEOUT = '180'
$env:UV_HTTP_RETRIES = '5'
$systemProxy = Get-ItemProperty 'HKCU:/Software/Microsoft/Windows/CurrentVersion/Internet Settings' -ErrorAction SilentlyContinue
if (-not $env:HTTPS_PROXY -and $systemProxy.ProxyEnable -eq 1 -and $systemProxy.ProxyServer -match '^127\.0\.0\.1:\d+$') {
    $env:HTTP_PROXY = 'http://' + $systemProxy.ProxyServer
    $env:HTTPS_PROXY = $env:HTTP_PROXY
    $env:ALL_PROXY = $env:HTTP_PROXY
}
$env:NO_PROXY = 'localhost,127.0.0.1,::1'
$projectRoot = Split-Path -Parent $PSScriptRoot
Push-Location $projectRoot
try {
    function Invoke-Checked([scriptblock]$Action) {
        & $Action
        if ($LASTEXITCODE -ne 0) { throw 'CosyVoice 部署命令执行失败。' }
    }
    if (-not (Test-Path '.venv/Scripts/python.exe')) { throw '请先运行 scripts/setup.ps1。' }
    if (-not (Test-Path '.venv/Scripts/uv.exe')) {
        Invoke-Checked { .venv/Scripts/python.exe -m pip install uv==0.9.9 }
    }
    Invoke-Checked { .venv/Scripts/uv.exe python install 3.10 }
    # DSH may not have access to uv's private user directory. Keep the base runtime in this project.
    if (-not (Test-Path 'runtime/python310/python.exe')) {
        $cosyPythonPath = & .venv/Scripts/uv.exe python find --managed-python 3.10
        if ($LASTEXITCODE -ne 0) { throw '未找到 Python 3.10 运行时。' }
        New-Item -ItemType Directory -Path runtime -Force | Out-Null
        Copy-Item -LiteralPath (Split-Path -Parent $cosyPythonPath) -Destination 'runtime/python310' -Recurse
    }
    if (-not (Test-Path '.cosyvenv/Scripts/python.exe')) {
        Invoke-Checked { .venv/Scripts/uv.exe venv --python runtime/python310/python.exe .cosyvenv }
    }
    $cosyVenvConfig = Get-Content '.cosyvenv/pyvenv.cfg' -Raw
    $cosyVenvConfig = $cosyVenvConfig -replace '(?m)^home = .*$', ('home = ' + (Join-Path $projectRoot 'runtime/python310'))
    Set-Content -LiteralPath '.cosyvenv/pyvenv.cfg' -Value $cosyVenvConfig -NoNewline
    if (-not (Test-Path 'runtime/CosyVoice/.git')) {
        Invoke-Checked { git clone --recursive https://github.com/FunAudioLLM/CosyVoice.git runtime/CosyVoice }
        Invoke-Checked { git -C runtime/CosyVoice checkout 074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc }
        Invoke-Checked { git -C runtime/CosyVoice submodule update --init --recursive }
    }
    Invoke-Checked { .venv/Scripts/python.exe -X utf8 scripts/download-cuda.py }
    Invoke-Checked { .venv/Scripts/uv.exe pip install --python .cosyvenv/Scripts/python.exe --no-deps --reinstall-package torch --reinstall-package torchaudio 'runtime/wheels/torch-2.8.0+cu128-cp310-cp310-win_amd64.whl' 'https://download.pytorch.org/whl/cu128/torchaudio-2.8.0%2Bcu128-cp310-cp310-win_amd64.whl' }
    Invoke-Checked { .venv/Scripts/uv.exe pip install --python .cosyvenv/Scripts/python.exe -r native/requirements-cosy.txt -b native/requirements-cosy-build.txt --index-url https://mirrors.aliyun.com/pypi/simple/ }
    Invoke-Checked { .venv/Scripts/python.exe -X utf8 scripts/download-cosy.py }
    Write-Host 'CosyVoice 环境和官方模型已就绪。开启宠物语音后后台会加载模型。'
} finally { Pop-Location }
