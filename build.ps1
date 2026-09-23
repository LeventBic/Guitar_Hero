# RIFF.exe build: testler -> ikon -> PyInstaller -> Songs kopyasi
# Kullanim:  powershell -ExecutionPolicy Bypass -File build.ps1   (-SkipTests ile testleri atla)
#            -Zip: dagitim icin dist\RIFF-windows.zip (yalniz demo sarkilar; Songs\ icindeki diger sarkilar girmez)
param([switch]$SkipTests, [switch]$Zip)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"

$running = Get-Process RIFF -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$PSScriptRoot\dist\*" }
if ($running) { throw "dist\RIFF\RIFF.exe su an acik; once oyunu kapatin." }

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
Copy-Item "THIRD_PARTY_NOTICES.md" "dist\RIFF\"
Write-Host "Hazir: dist\RIFF\RIFF.exe"

if ($Zip) {
    # dagitim paketi: program + demo sarkilar (kullanicinin ekledigi / indirdigi telifli sarkilar haric)
    $stage = "dist\_zip\RIFF"
    if (Test-Path "dist\_zip") { Remove-Item -Recurse -Force "dist\_zip" }
    New-Item -ItemType Directory -Force "$stage\Songs\_Import" | Out-Null
    Copy-Item "dist\RIFF\RIFF.exe", "dist\RIFF\THIRD_PARTY_NOTICES.md" $stage
    Copy-Item "dist\RIFF\_internal" $stage -Recurse
    Get-ChildItem "Songs" -Directory -Filter "RIFF Demo Band - *" | ForEach-Object { Copy-Item $_.FullName "$stage\Songs" -Recurse }
    $zipPath = "dist\RIFF-windows.zip"
    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }
    # Compress-Archive (PS 5.1) yollari '\' ile yazar; standart zip icin Python
    & $py -c "import shutil; shutil.make_archive('dist/RIFF-windows', 'zip', 'dist/_zip', 'RIFF')"
    if ($LASTEXITCODE -ne 0) { throw "Zip olusturulamadi." }
    Remove-Item -Recurse -Force "dist\_zip"
    Write-Host ("Hazir: {0} ({1:N0} MB)" -f $zipPath, ((Get-Item $zipPath).Length / 1MB))
}
