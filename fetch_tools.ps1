# Downloads what build_installer.ps1 bundles, pinned and checksum-verified (all git-ignored):
#   - build\runtime\python-embed.zip: the official, signed Python runtime that becomes ScorpionIDM.exe
#   - build\tools: ffmpeg + ffprobe (shared build: the two small exes share the same DLLs) from
#     yt-dlp/FFmpeg-Builds, and QuickJS-ng (qjs.exe), the JavaScript runtime yt-dlp needs for YouTube
# Only missing parts are downloaded. To upgrade one, change its URL and SHA-256 below (published next to
# each release), delete the old copy, then run this script. The Python version must match $pyVersion in
# build_installer.ps1.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$toolsDir = Join-Path $root "build\tools"
$runtimeZip = Join-Path $root "build\runtime\python-embed.zip"

$pythonEmbedUrl = "https://www.python.org/ftp/python/3.14.10/python-3.14.10-embed-amd64.zip"
$pythonEmbedSha = "90905e64a840557d8c1bc4f5b74db3d7ee85e3ffb217611cac1c7813acea4159"
$ffmpegZipUrl = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/autobuild-2026-10-19-19-51/ffmpeg-N-127709-g5993347a1b-win64-gpl-shared.zip"
$ffmpegZipSha = "890302aaaf18c7248ba42a871708df3dc27d327bbd02c1955f1382e7380da56e"
$qjsUrl = "https://github.com/quickjs-ng/quickjs/releases/download/v0.17.0/qjs-windows-x86_64.exe"
$qjsSha = "2aeabf0092c3262d6b2609824418f7dd7ed1f1df939f73b2b15645230cac0d77"

function Get-Verified($url, $sha, $dest) {
    Write-Output "Downloading $url"
    Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
    $actual = (Get-FileHash $dest -Algorithm SHA256).Hash.ToLower()
    if ($actual -ne $sha) {
        Remove-Item $dest -Force
        throw "Checksum mismatch for $url (expected $sha, got $actual)"
    }
}

# 1) Python runtime
if (-not (Test-Path $runtimeZip) -or (Get-FileHash $runtimeZip -Algorithm SHA256).Hash.ToLower() -ne $pythonEmbedSha) {
    New-Item -ItemType Directory -Force -Path (Split-Path $runtimeZip) | Out-Null
    Get-Verified $pythonEmbedUrl $pythonEmbedSha $runtimeZip
}

# 2) Bundled programs
if (@("ffmpeg.exe", "ffprobe.exe", "qjs.exe") | Where-Object { -not (Test-Path (Join-Path $toolsDir $_)) }) {
    $tmp = Join-Path $env:TEMP ("scorpion_tools_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
    New-Item -ItemType Directory -Force -Path $tmp | Out-Null
    try {
        $zip = Join-Path $tmp "ffmpeg.zip"
        Get-Verified $ffmpegZipUrl $ffmpegZipSha $zip
        Get-Verified $qjsUrl $qjsSha (Join-Path $tmp "qjs.exe")
        Expand-Archive $zip -DestinationPath (Join-Path $tmp "ffmpeg") -Force
        $bin = Get-ChildItem (Join-Path $tmp "ffmpeg") -Recurse -Directory -Filter bin | Select-Object -First 1
        if (-not $bin) { throw "bin folder not found in the ffmpeg archive" }

        # Replace build\tools completely so no file from an older set is left behind
        if (Test-Path $toolsDir) { Remove-Item $toolsDir -Recurse -Force }
        New-Item -ItemType Directory -Force -Path $toolsDir | Out-Null
        Get-ChildItem $bin.FullName -File | Where-Object { $_.Name -ne "ffplay.exe" } | Copy-Item -Destination $toolsDir
        Copy-Item (Join-Path $tmp "qjs.exe") $toolsDir
    }
    finally {
        Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
    }
}
Get-ChildItem $toolsDir, (Split-Path $runtimeZip) -File | Select-Object Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}} | Format-Table -AutoSize
