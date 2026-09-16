$packageRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PYTHONIOENCODING = 'utf-8'
$env:RESEARCH_MEMORY_PACKAGE_ROOT = $packageRoot
$forwardArgs = @($args)
if ($forwardArgs.Count -ge 2 -and $forwardArgs[0] -eq '--root') {
    $instanceRoot = $forwardArgs[1]
    $forwardArgs = @($forwardArgs | Select-Object -Skip 2)
} elseif ($env:RESEARCH_MEMORY_ROOT) {
    $instanceRoot = $env:RESEARCH_MEMORY_ROOT
} elseif (Test-Path -LiteralPath (Join-Path $packageRoot 'config.json')) {
    $instanceRoot = $packageRoot
} else {
    $instanceRoot = Join-Path $env:LOCALAPPDATA 'ResearchMemory/instances/default'
}
$pythonPath = Join-Path $instanceRoot 'runtime/venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) { throw '运行环境不存在，请先运行 scripts/install.ps1，或提供正确的 --root 数据目录。' }
& $pythonPath -m research_memory.cli --root $instanceRoot @forwardArgs
exit $LASTEXITCODE
