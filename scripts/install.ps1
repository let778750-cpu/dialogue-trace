param(
    [Parameter(Mandatory=$true)][string]$Workspace,
    [string]$DataDir = (Join-Path $env:LOCALAPPDATA 'ResearchMemory/instances/default'),
    [switch]$WithObsidian,
    [switch]$Upgrade
)
$ErrorActionPreference = 'Stop'
$packageRoot = Split-Path -Parent $PSScriptRoot
$instanceRoot = [IO.Path]::GetFullPath($DataDir)
$packageAbsolute = [IO.Path]::GetFullPath($packageRoot)
if ($instanceRoot.Equals($packageAbsolute, [StringComparison]::OrdinalIgnoreCase) -or $instanceRoot.StartsWith($packageAbsolute + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) {
    throw '研究数据目录必须位于 skill 安装目录之外。'
}
if (!(Test-Path -LiteralPath $Workspace -PathType Container)) { throw '工作区不存在。' }
$env:PYTHONUTF8='1'
$env:PYTHONIOENCODING='utf-8'
$env:RESEARCH_MEMORY_PACKAGE_ROOT=$packageRoot
$env:RESEARCH_MEMORY_ROOT=$instanceRoot
$runtimeRoot=Join-Path $instanceRoot 'runtime'
foreach ($folder in @('tmp','cache/pip','cache/uv','models')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $runtimeRoot $folder) | Out-Null
}
$env:TEMP=Join-Path $runtimeRoot 'tmp'
$env:TMP=$env:TEMP
$env:PIP_CACHE_DIR=Join-Path $runtimeRoot 'cache/pip'
$env:UV_CACHE_DIR=Join-Path $runtimeRoot 'cache/uv'
$env:UV_PYTHON_INSTALL_DIR=Join-Path $runtimeRoot 'python'
$env:UV_NATIVE_TLS='true'
$env:UV_HTTP_TIMEOUT='90'
$env:UV_CONCURRENT_DOWNLOADS='4'
$env:HF_HOME=Join-Path $runtimeRoot 'models/huggingface'
$env:FASTEMBED_CACHE_PATH=Join-Path $runtimeRoot 'models/fastembed'
# A bootstrap interpreter only downloads uv. The research runtime uses a pinned
# managed CPython, so an existing Anaconda installation cannot change DLL loading.
$uvPath=Join-Path $runtimeRoot 'tools/uv.exe'
if (!(Test-Path -LiteralPath $uvPath)) {
    $bootstrapPython=Join-Path $runtimeRoot 'bootstrap/Scripts/python.exe'
    if (!(Test-Path -LiteralPath $bootstrapPython)) {
        & python -m venv (Join-Path $runtimeRoot 'bootstrap')
        if ($LASTEXITCODE -ne 0) { throw '创建下载工具环境失败；请安装 Python 3.12+ 后重试。' }
    }
    & $bootstrapPython -m pip install 'uv==0.8.22'
    if ($LASTEXITCODE -ne 0) { throw '依赖工具下载失败；数据保留，可使用同一命令重试。' }
    New-Item -ItemType Directory -Force -Path (Split-Path $uvPath) | Out-Null
    Copy-Item -LiteralPath (Join-Path $runtimeRoot 'bootstrap/Scripts/uv.exe') -Destination $uvPath
}
$uvVersion=& $uvPath --version
if ($uvVersion -notmatch '^uv 0\.8\.22(?:\s|$)') { throw '本地下载工具版本与发行清单不一致。' }
& $uvPath python install '3.12.11'
if ($LASTEXITCODE -ne 0) { throw 'CPython 下载未完成；数据保留，重试会复用已下载内容。' }
$pythonPath=Join-Path $runtimeRoot 'venv/Scripts/python.exe'
if (!(Test-Path -LiteralPath $pythonPath)) {
    & $uvPath venv --python '3.12.11' (Join-Path $runtimeRoot 'venv')
    if ($LASTEXITCODE -ne 0) { throw '创建本地 Python 环境失败。' }
}
if ($Upgrade -and (Test-Path -LiteralPath (Join-Path $instanceRoot 'config.json'))) {
    & $pythonPath (Join-Path $packageRoot 'scripts/update_instance.py') --root $instanceRoot --snapshot
    if ($LASTEXITCODE -ne 0) { throw '升级前备份失败，未替换依赖。' }
}
& $uvPath pip sync --python $pythonPath (Join-Path $packageRoot 'integrations/release-requirements.lock.txt')
if ($LASTEXITCODE -ne 0) { throw '固定依赖安装失败；数据保留，使用同一命令重试，不改写版本清单。' }
& $uvPath pip install --python $pythonPath --no-deps --no-build-isolation $packageRoot
if ($LASTEXITCODE -ne 0) { throw 'Research Memory 安装失败。' }
if ($Upgrade) {
    & $pythonPath (Join-Path $packageRoot 'scripts/update_instance.py') --root $instanceRoot --package $packageRoot
    if ($LASTEXITCODE -ne 0) { throw '程序位置更新失败；按备份记录恢复。' }
}
$setupArgs=@('-m','research_memory.cli','--root',$instanceRoot,'setup','--workspace',$Workspace)
if ($WithObsidian) {$setupArgs+='--with-obsidian'}
& $pythonPath @setupArgs
if ($LASTEXITCODE -ne 0) { throw '初始化尚未完成，请按具体错误核对；已有配置和研究数据保留。' }
& $pythonPath -m research_memory.cli --root $instanceRoot doctor
exit $LASTEXITCODE
