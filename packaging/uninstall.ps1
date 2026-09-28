# Wireless Limitless 제거 스크립트 (현재 사용자용)
$ErrorActionPreference = 'Stop'

$dst = Join-Path $env:LOCALAPPDATA 'Programs\WirelessLimitless'
$data = Join-Path $env:APPDATA 'WirelessLimitless'

Get-Process -Name 'WirelessLimitless' -ErrorAction SilentlyContinue | ForEach-Object {
    $_.CloseMainWindow() | Out-Null
}
Start-Sleep -Seconds 2
Get-Process -Name 'WirelessLimitless' -ErrorAction SilentlyContinue | Stop-Process -Force

foreach ($folder in @([Environment]::GetFolderPath('Desktop'), [Environment]::GetFolderPath('Programs'))) {
    $lnk = Join-Path $folder 'Wireless Limitless.lnk'
    if (Test-Path $lnk) { Remove-Item $lnk -Force }
}

# 설치 폴더는 이 스크립트가 들어 있는 곳일 수 있으므로 별도 프로세스에서 지운다.
if (Test-Path $dst) {
    Start-Process -FilePath "$env:SystemRoot\System32\cmd.exe" -WindowStyle Hidden `
        -ArgumentList '/d', '/c', "ping -n 3 127.0.0.1 >nul & rmdir /s /q `"$dst`""
}

$answer = Read-Host '앱 설정과 로그(%APPDATA%\WirelessLimitless)도 지울까요? (y/N)'
if ($answer -match '^[yY]') { Remove-Item $data -Recurse -Force -ErrorAction SilentlyContinue }

Write-Host '제거했어요.' -ForegroundColor Green
