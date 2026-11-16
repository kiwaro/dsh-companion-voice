$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python)) {
    py -3.13 -m venv (Join-Path $project '.venv')
    if ($LASTEXITCODE -ne 0) { throw '创建 Python 3.13 环境失败。' }
}
& $python -m pip install -r (Join-Path $project 'native\requirements.txt')
if ($LASTEXITCODE -ne 0) { throw '安装语音依赖失败。' }
Write-Host '语音环境已准备完成。'
