$ErrorActionPreference = 'Stop'
$assetPath = Join-Path $PSScriptRoot 'assets'
$buildPath = Join-Path $PSScriptRoot 'build'
$distPath = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $buildPath,$distPath -Force | Out-Null
python -m PyInstaller --noconfirm --onefile --windowed --name Shiyin --add-data "$assetPath;assets" --distpath $distPath --workpath $buildPath --specpath $buildPath (Join-Path $PSScriptRoot 'music_collector.pyw')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Get-ChildItem -LiteralPath $PSScriptRoot -File -Filter '*.html' | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $distPath -Force }
Write-Output "Build complete: $distPath"
