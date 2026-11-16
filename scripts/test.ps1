$ErrorActionPreference = 'Stop'
$project = Split-Path $PSScriptRoot -Parent
Push-Location $project
try {
    npm test
    if ($LASTEXITCODE -ne 0) { throw '宿主测试失败。' }
    npm run test:native
    if ($LASTEXITCODE -ne 0) { throw '语音状态测试失败。' }
} finally { Pop-Location }
