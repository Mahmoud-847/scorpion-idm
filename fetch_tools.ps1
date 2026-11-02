# Downloads the programs bundled with Scorpion IDM into build\tools (git-ignored), pinned and checksum-verified:
#   - ffmpeg + ffprobe (shared build: the two small exes share the same DLLs) from yt-dlp/FFmpeg-Builds
#   - QuickJS-ng (qjs.exe), the JavaScript runtime yt-dlp needs for YouTube
# To upgrade a tool, change its URL and SHA-256 below (published next to each release), then run this script.
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$toolsDir = Join-Path $root "build\tools"

$ffmpegZipUrl = "https://github.com/yt-dlp/FFmpeg-Builds/releases/download/autobuild-2026-10-19-19-51/ffmpeg-N-127709-g5993347a1b-win64-gpl-shared.zip"
$ffmpegZipSha = "890302aaaf18c7248ba42a871708df3dc27d327bbd02c1955f1382e7380da56e"
$qjsUrl = "https://github.com/quickjs-ng/quickjs/releases/download/v0.17.0/qjs-windows-x86_64.exe"
$qjsSha = "2aeabf0092c3262d6b2609824418f7dd7ed1f1df939f73b2b15645230cac0d77"

$tmp = Join-Path $env:TEMP ("scorpion_tools_" + [guid]::NewGuid().ToString("N").Substring(0, 8))
New-Item -ItemType Directory -Force -Path $tmp | Out-Null
try {
    function Get-Verified($url, $sha, $dest) {
        Write-Output "Downloading $url"
        Invoke-WebRequest -Uri $url -OutFile $dest -UseBasicParsing
        $actual = (Get-FileHash $dest -Algorithm SHA256).Hash.ToLower()
        if ($actual -ne $sha) { throw "Checksum mismatch for $url (expected $sha, got $actual)" }
    }
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
    Get-ChildItem $toolsDir | Select-Object Name, @{N='MB';E={[math]::Round($_.Length/1MB,1)}} | Format-Table -AutoSize
}
finally {
    Remove-Item $tmp -Recurse -Force -ErrorAction SilentlyContinue
}
