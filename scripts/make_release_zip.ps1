param(
    [string]$Version = "v1.0.0"
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ReleaseDir = Join-Path $ProjectRoot "dist_release\ClipDis"
$ExePath = Join-Path $ReleaseDir "ClipDis.exe"
$InternalDir = Join-Path $ReleaseDir "_internal"
$ReleasesDir = Join-Path $ProjectRoot "releases"
$ZipName = "ClipDis-$Version-windows-x64.zip"
$ZipPath = Join-Path $ReleasesDir $ZipName

if (-not (Test-Path $ExePath -PathType Leaf)) {
    throw "Missing release executable: $ExePath. Run build.bat release first."
}
if (-not (Test-Path $InternalDir -PathType Container)) {
    throw "Missing packaged _internal directory: $InternalDir. The release folder is incomplete."
}

$FfmpegExe = Join-Path $InternalDir "app\ffmpeg\bin\ffmpeg.exe"
$FfprobeExe = Join-Path $InternalDir "app\ffmpeg\bin\ffprobe.exe"
if (Test-Path $FfmpegExe -PathType Leaf) {
    $LicenseCandidates = @(
        Join-Path $InternalDir "app\ffmpeg\bin\LICENSE*"
        Join-Path $InternalDir "app\ffmpeg\bin\NOTICE*"
        Join-Path $InternalDir "app\ffmpeg\bin\COPYING*"
        Join-Path $InternalDir "app\ffmpeg\LICENSE*"
        Join-Path $InternalDir "app\ffmpeg\NOTICE*"
        Join-Path $InternalDir "app\ffmpeg\COPYING*"
    )
    $Licenses = @()
    foreach ($Pattern in $LicenseCandidates) {
        $Licenses += Get-ChildItem -Path $Pattern -File -ErrorAction SilentlyContinue
    }
    if ($Licenses.Count -eq 0) {
        throw "Bundled FFmpeg was found but no FFmpeg license/notice file was found in packaged output."
    }
}
if (-not (Test-Path $FfprobeExe -PathType Leaf)) {
    throw "Missing bundled ffprobe executable: $FfprobeExe"
}

New-Item -ItemType Directory -Force -Path $ReleasesDir | Out-Null
if (Test-Path $ZipPath -PathType Leaf) {
    Remove-Item -LiteralPath $ZipPath -Force
}

Push-Location $ReleaseDir
try {
    Compress-Archive -Path @("ClipDis.exe", "_internal") -DestinationPath $ZipPath -CompressionLevel Optimal
}
finally {
    Pop-Location
}

Write-Host "Release artifact: $ZipPath"
