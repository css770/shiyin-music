$ErrorActionPreference = 'Stop'
$assetPath = Join-Path $PSScriptRoot 'assets'
$buildPath = Join-Path $PSScriptRoot 'build'
$distPath = Join-Path $PSScriptRoot 'dist'
New-Item -ItemType Directory -Path $buildPath,$distPath -Force | Out-Null
python -m PyInstaller --noconfirm --onefile --windowed --name Shiyin --add-data "$assetPath;assets" --distpath $distPath --workpath $buildPath --specpath $buildPath (Join-Path $PSScriptRoot 'music_collector.pyw')
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller build failed.' }
Copy-Item -LiteralPath (Join-Path $PSScriptRoot '浏览器采集助手.html') -Destination $distPath -Force
Write-Output "Build complete: $distPath"
