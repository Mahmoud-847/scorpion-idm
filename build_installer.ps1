# Builds the Scorpion IDM app (PyInstaller onedir) and wraps it into a single Setup .exe
$ErrorActionPreference = "Stop"
$root  = $PSScriptRoot
# Python used for the build (yt-dlp needs 3.11+). Change $pyVersion to move the build to another release.
$pyVersion = "3.14"
$py = (& py "-$pyVersion" -c "import sys; print(sys.executable)" 2>$null)
if (-not $py) { $py = Join-Path $env:LOCALAPPDATA ("Programs\Python\Python" + $pyVersion.Replace(".", "") + "\python.exe") }
if (-not (Test-Path $py)) { throw "Python $pyVersion not found (winget install Python.Python.$pyVersion)" }
Write-Output "Building with $(& $py --version)"
$work  = Join-Path $root "native_app\_build"
$out   = Join-Path $root "release"
$repo  = "Mahmoud-847/scorpion-idm"

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work, $out, "$work\setup_dist", "$work\setup_payload" | Out-Null

# 1) The application itself (yt-dlp's YouTube challenge scripts are bundled when installed: pip install yt-dlp-ejs)
$extra = @()
& $py -c "import yt_dlp_ejs" 2>$null
if ($LASTEXITCODE -eq 0) { $extra = @("--collect-all", "yt_dlp_ejs") }
& $py -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name ScorpionIDM `
    --icon "$root\build\icon.ico" `
    --collect-submodules yt_dlp `
    --collect-submodules Cryptodome `
    @extra `
    --distpath "$work\dist" --workpath "$work\build" --specpath "$work" `
    "$root\native_app\scorpion_qt.py"
if ($LASTEXITCODE -ne 0) { throw "App build failed" }

$appDir = Join-Path $work "dist\ScorpionIDM"
Copy-Item "$root\browser-extension" "$appDir\browser-extension" -Recurse -Force
New-Item -ItemType Directory -Force -Path "$appDir\build" | Out-Null
Copy-Item "$root\build\icon.ico", "$root\build\icon.png", "$root\build\tray.png", "$root\build\aria2c.exe" "$appDir\build" -Force

# 2) Bundled programs (ffmpeg + ffprobe with their DLLs, QuickJS) kept in build\tools (git-ignored: too large
#    for the repo). fetch_tools.ps1 downloads the pinned, checksum-verified versions when they are missing.
$toolsDir = Join-Path $root "build\tools"
$requiredTools = @("ffmpeg.exe", "ffprobe.exe", "qjs.exe")
if ($requiredTools | Where-Object { -not (Test-Path (Join-Path $toolsDir $_)) }) {
    & "$root\fetch_tools.ps1"
}
foreach ($tool in $requiredTools) {
    if (-not (Test-Path (Join-Path $toolsDir $tool))) { throw "$tool missing from build\tools (run fetch_tools.ps1)" }
}
# Tools version = fingerprint of every bundled file, so PCs only download the pack when a tool really changes
$toolHashes = (Get-ChildItem $toolsDir -File | Where-Object Name -ne "version.txt" | Sort-Object Name |
    ForEach-Object { "$($_.Name):$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" }) -join ";"
$sha = [System.Security.Cryptography.SHA256]::Create()
$toolsVersion = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($toolHashes))) -replace "-", "").Substring(0, 12).ToLower()
Set-Content -Path (Join-Path $toolsDir "version.txt") -Value $toolsVersion -NoNewline -Encoding ascii

# Tools pack for PCs that update in-app (hosted as a release asset, rebuilt only when the tools change)
$toolsPack = Join-Path $out "Scorpion-Tools.zip"
$toolsStamp = Join-Path $out "Scorpion-Tools.version"
if (-not (Test-Path $toolsPack) -or -not (Test-Path $toolsStamp) -or (Get-Content $toolsStamp -Raw).Trim() -ne $toolsVersion) {
    Compress-Archive -Path (Join-Path $toolsDir "*") -DestinationPath $toolsPack -Force
    Set-Content -Path $toolsStamp -Value $toolsVersion -NoNewline -Encoding ascii
}

# 3) Update payload: the app only, so regular updates stay small (also saved to release\ for in-app updates)
$payload = Join-Path $work "payload.zip"
Compress-Archive -Path "$appDir\*" -DestinationPath $payload -Force
Copy-Item $payload "$out\Scorpion-Update-Payload.zip" -Force

$env:SCORP_OUT = $out
$env:SCORP_ROOT = $root
$env:SCORP_TOOLS_VERSION = $toolsVersion
$env:SCORP_TOOLS_URL = "https://github.com/$repo/releases/download/tools-$toolsVersion/Scorpion-Tools.zip"
$manifestScript = @'
import hashlib, json, os, sys
out, root = os.environ["SCORP_OUT"], os.environ["SCORP_ROOT"]
sys.path.insert(0, os.path.join(root, "native_app"))
import scorpion_qt as sq

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

h = sq.CHANGELOG_HISTORY[0]
pack = os.path.join(out, "Scorpion-Tools.zip")
m = {
    "version": sq.APP_VERSION,
    "publishedAt": h["date"],
    "packageFile": "Scorpion-Update-Payload.zip",
    "sha256": sha256(os.path.join(out, "Scorpion-Update-Payload.zip")),
    "downloadUrl": "https://github.com/Mahmoud-847/scorpion-idm/raw/main/release/Scorpion-Update-Payload.zip",
    "title_ar": h["title_ar"],
    "title_en": h["title_en"],
    "changelog_ar": h["ar"],
    "changelog_en": h["en"],
    "tools": {
        "version": os.environ["SCORP_TOOLS_VERSION"],
        "url": os.environ["SCORP_TOOLS_URL"],
        "sha256": sha256(pack),
        "size": os.path.getsize(pack),
    },
}
with open(os.path.join(out, "update.json"), "w", encoding="utf-8") as f:
    f.write(json.dumps(m, ensure_ascii=False, indent=2))
'@
$manifestPy = Join-Path $work "write_manifest.py"
Set-Content -Path $manifestPy -Value $manifestScript -Encoding utf8
& $py $manifestPy
if ($LASTEXITCODE -ne 0) { throw "Writing update.json failed" }

# 4) Setup payload: the app plus the bundled programs, so a fresh install needs nothing else
$setupApp = Join-Path $work "setup_app"
Copy-Item $appDir $setupApp -Recurse -Force
Copy-Item $toolsDir (Join-Path $setupApp "tools") -Recurse -Force
$setupPayload = Join-Path $work "setup_payload\payload.zip"
Compress-Archive -Path "$setupApp\*" -DestinationPath $setupPayload -Force

# 5) Setup wizard named after the app version (single exe built into staging dir first, then copied atomically)
$appVersion = (Select-String -Path "$root\native_app\scorpion_qt.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' |
    Select-Object -First 1).Matches[0].Groups[1].Value
if (-not $appVersion) { throw "APP_VERSION not found in scorpion_qt.py" }
$setupName = "Scorpion-Setup-$appVersion"

& $py -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name $setupName `
    --icon "$root\build\icon.ico" `
    --add-data "$setupPayload;." --add-data "$root\build\icon.ico;." `
    --distpath "$work\setup_dist" --workpath "$work\setup_build" --specpath "$work" `
    "$root\native_app\installer\scorpion_setup.py"
if ($LASTEXITCODE -ne 0) { throw "Setup build failed" }

$stagedSetup = Join-Path "$work\setup_dist" "$setupName.exe"

# release\ keeps only the latest setup (git-ignored); Downloads keeps one per version
Get-ChildItem $out -Filter "Scorpion-Setup-*.exe" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Copy-Item $stagedSetup "$out\$setupName.exe" -Force

# The user's real Downloads folder (it can be moved away from %USERPROFILE%\Downloads)
$downloads = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path
if (-not $downloads -or -not (Test-Path $downloads)) { $downloads = Join-Path $env:USERPROFILE "Downloads" }
$dlSetup = Join-Path $downloads "$setupName.exe"
Copy-Item $stagedSetup $dlSetup -Force -ErrorAction Stop

Get-Item "$out\$setupName.exe", $dlSetup, $toolsPack | Select-Object FullName, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}
# Read by auto_publish.py: where the new setup was saved, and which tools pack update.json points to
Write-Output "SETUP_PATH=$dlSetup"
Write-Output "TOOLS_VERSION=$toolsVersion"
Write-Output "TOOLS_PACK=$toolsPack"
