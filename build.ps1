# RIFF.exe build: testler -> ikon -> PyInstaller -> Songs kopyasi
# Kullanim:  powershell -ExecutionPolicy Bypass -File build.ps1   (-SkipTests ile testleri atla)
param([switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

if (-not $SkipTests) {
    & $py -m pytest tests -q
    if ($LASTEXITCODE -ne 0) { throw "Testler basarisiz, build durduruldu." }
}

if (-not (Test-Path "Songs")) {
    & $py tools\make_demo_songs.py
    if ($LASTEXITCODE -ne 0) { throw "Demo sarkilar uretilemedi." }
}

& $py tools\make_icon.py
if ($LASTEXITCODE -ne 0) { throw "Ikon uretilemedi." }

& $py -m PyInstaller RIFF.spec --noconfirm --clean
if ($LASTEXITCODE -ne 0) { throw "PyInstaller basarisiz." }

$dest = "dist\RIFF\Songs"
if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
Copy-Item "Songs" $dest -Recurse
Write-Host "Hazir: dist\RIFF\RIFF.exe"
