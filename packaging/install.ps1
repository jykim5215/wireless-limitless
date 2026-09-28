# Wireless Limitless 설치 스크립트 (현재 사용자용, 관리자 권한 불필요)
# - %LOCALAPPDATA%\Programs\WirelessLimitless 로 복사
# - 바탕화면 / 시작 메뉴 바로가기 생성 후 앱 실행
$ErrorActionPreference = 'Stop'

$src = $PSScriptRoot
$dst = Join-Path $env:LOCALAPPDATA 'Programs\WirelessLimitless'
$exe = 'WirelessLimitless.exe'

if (-not (Test-Path (Join-Path $src $exe))) {
    Write-Host "설치 파일을 찾을 수 없어요: $exe" -ForegroundColor Red
    exit 1
}

$running = Get-Process -Name 'WirelessLimitless' -ErrorAction SilentlyContinue
if ($running) {
    Write-Host '실행 중인 Wireless Limitless 를 종료할게요...'
    $running | ForEach-Object { $_.CloseMainWindow() | Out-Null }
    Start-Sleep -Seconds 3
    Get-Process -Name 'WirelessLimitless' -ErrorAction SilentlyContinue | Stop-Process -Force
}

$srcFull = (Resolve-Path $src).Path.TrimEnd('\')
if ($srcFull -ne $dst.TrimEnd('\')) {
    New-Item -ItemType Directory -Force -Path $dst | Out-Null
    robocopy $srcFull $dst /MIR /R:3 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null
    if ($LASTEXITCODE -ge 8) { Write-Host '파일 복사에 실패했어요.' -ForegroundColor Red; exit 1 }
}

$target = Join-Path $dst $exe
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = $shell.CreateShortcut((Join-Path $folder 'Wireless Limitless.lnk'))
    $lnk.TargetPath = $target
    $lnk.WorkingDirectory = $dst
    $lnk.IconLocation = "$target,0"
    $lnk.Description = 'QCY 이어버드 컨트롤러'
    $lnk.Save()
}

Write-Host "설치 완료: $dst" -ForegroundColor Green
Write-Host '바탕화면과 시작 메뉴에 "Wireless Limitless" 바로가기를 만들었어요.'
Start-Process -FilePath $target -WorkingDirectory $dst
