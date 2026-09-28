# Build Wireless Limitless: tests -> icon -> PyInstaller (onedir) -> package zip.
#   powershell -ExecutionPolicy Bypass -File tools\build.ps1 [-SkipTests]
param([switch]$SkipTests)
$ErrorActionPreference = 'Stop'

$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$py = Join-Path $root '.venv\Scripts\python.exe'
if (-not (Test-Path $py)) { throw "virtualenv missing: python -m venv .venv; .venv\Scripts\pip install -r requirements-dev.txt" }

if (-not $SkipTests) {
    & $py -m pytest -q
    if ($LASTEXITCODE -ne 0) { throw 'unit tests failed' }
}

& $py tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw 'icon generation failed' }
$version = & $py tools\make_version_info.py (Join-Path $root 'build\version_info.txt')
if ($LASTEXITCODE -ne 0) { throw 'version info failed' }
Write-Host "Building Wireless Limitless $version"

$ui = Join-Path $root 'src\wireless_limitless\ui'
$versionJson = Join-Path $root 'version.json'
& $py -m PyInstaller --noconfirm --clean --log-level WARN `
    --onedir --windowed --name WirelessLimitless `
    --icon (Join-Path $root 'assets\icon.ico') `
    --version-file (Join-Path $root 'build\version_info.txt') `
    --paths (Join-Path $root 'src') `
    --add-data "$ui;ui" `
    --add-data "$versionJson;." `
    --exclude-module pytest --exclude-module PIL --exclude-module tkinter `
    --distpath (Join-Path $root 'build\dist') `
    --workpath (Join-Path $root 'build\work') `
    --specpath (Join-Path $root 'build') `
    (Join-Path $root 'tools\entry.py')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

& $py tools\package.py
if ($LASTEXITCODE -ne 0) { throw 'packaging failed' }
