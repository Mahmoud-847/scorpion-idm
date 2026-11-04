# Builds the Scorpion IDM app on the official, signed Python 3.14 runtime and packages it with Inno Setup 6
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
$pyVersion = "3.14"
$pyNoDot = $pyVersion.Replace(".", "")
$py = (& py "-$pyVersion" -c "import sys; print(sys.executable)" 2>$null)
if (-not $py) { $py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python$pyNoDot\python.exe" }
if (-not (Test-Path $py)) { throw "Python $pyVersion not found (winget install Python.Python.$pyVersion)" }

$iscc = @(
    (Get-Command ISCC.exe -ErrorAction SilentlyContinue).Source,
    (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe"),
    "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
    "C:\Program Files\Inno Setup 6\ISCC.exe"
) | Where-Object { $_ -and (Test-Path $_) } | Select-Object -First 1
if (-not $iscc) { throw "Inno Setup 6 (ISCC.exe) not found (winget install JRSoftware.InnoSetup)" }

Write-Output "Building with $(& $py --version) + Inno Setup ($iscc)"
$work = Join-Path $root "native_app\_build"
$out  = Join-Path $root "release"
$repo = "Mahmoud-847/scorpion-idm"

if ([IO.Path]::GetFullPath($work) -ne [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'native_app\_build'))) {
    throw "Refusing to remove a build directory outside the project workspace"
}
Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work, $out, "$work\setup_dist" | Out-Null

# Publish the same extension files bundled in the installer, including shared media helpers.
Compress-Archive -Path "$root\browser-extension\*" -DestinationPath "$out\Scorpion-Browser-Extension.zip" -Force

# 1) Ensure pinned, checksum-verified Python runtime & tools exist
$runtimeZip = Join-Path $root "build\runtime\python-embed.zip"
$toolsDir   = Join-Path $root "build\tools"
$requiredTools = @("ffmpeg.exe", "ffprobe.exe", "qjs.exe")
if (-not (Test-Path $runtimeZip) -or ($requiredTools | Where-Object { -not (Test-Path (Join-Path $toolsDir $_)) })) {
    & "$root\fetch_tools.ps1"
}
if (-not (Test-Path $runtimeZip)) { throw "Signed Python runtime missing at $runtimeZip (run fetch_tools.ps1)" }
foreach ($tool in $requiredTools) {
    if (-not (Test-Path (Join-Path $toolsDir $tool))) { throw "$tool missing from build\tools (run fetch_tools.ps1)" }
}

# 2) Assemble the application on the official signed Python embeddable runtime (no PyInstaller bootloader)
$appDir = Join-Path $work "dist\ScorpionIDM"
New-Item -ItemType Directory -Force -Path $appDir, "$appDir\app", "$appDir\site-packages", "$appDir\build" | Out-Null
Expand-Archive -Path $runtimeZip -DestinationPath $appDir -Force

# Rename signed pythonw.exe -> ScorpionIDM.exe without touching a single byte (preserves PSF Authenticode signature)
Move-Item (Join-Path $appDir "pythonw.exe") (Join-Path $appDir "ScorpionIDM.exe") -Force
Remove-Item (Join-Path $appDir "python.exe") -Force -ErrorAction SilentlyContinue
$sig = Get-AuthenticodeSignature (Join-Path $appDir "ScorpionIDM.exe")
if ($sig.Status -ne "Valid") {
    throw "ScorpionIDM.exe digital signature is invalid ($($sig.Status))"
}
Write-Output "Verified ScorpionIDM.exe signature: $($sig.Status) ($($sig.SignerCertificate.Subject))"

$pthContent = @(
    "python$pyNoDot.zip",
    ".",
    "app",
    "site-packages",
    "import site"
) -join "`r`n"
Set-Content -Path (Join-Path $appDir "python$pyNoDot._pth") -Value $pthContent -Encoding ascii

Copy-Item "$root\native_app\scorpion_qt.py", "$root\native_app\sitecustomize.py", "$root\native_app\media_transfer.py" "$appDir\app" -Force
Copy-Item "$root\browser-extension" "$appDir\browser-extension" -Recurse -Force
Copy-Item "$root\build\icon.ico", "$root\build\icon.png", "$root\build\tray.png", "$root\build\aria2c.exe" "$appDir\build" -Force

# Install pinned dependencies into site-packages
& $py -m pip install --quiet --disable-pip-version-check --no-compile --no-deps `
    -r "$root\requirements.txt" --target "$appDir\site-packages"
if ($LASTEXITCODE -ne 0) { throw "Installing dependencies into site-packages failed" }

# Trim unused Qt6 modules (QML, Quick3D, Designer, Multimedia, translations) so update payload stays compact (~35 MB)
$qtRoot = Join-Path $appDir "site-packages\PyQt6"
foreach ($dir in @("bindings", "lupdate", "uic", "Qt6\qml", "Qt6\qsci", "Qt6\translations")) {
    Remove-Item (Join-Path $qtRoot $dir) -Recurse -Force -ErrorAction SilentlyContinue
}
$keepQtPyd = @("QtCore.pyd", "QtGui.pyd", "QtWidgets.pyd", "QtSvg.pyd", "QtNetwork.pyd")
Get-ChildItem $qtRoot -Filter "Qt*.pyd" -File -ErrorAction SilentlyContinue |
    Where-Object { $keepQtPyd -notcontains $_.Name } |
    Remove-Item -Force
Get-ChildItem $qtRoot -Filter "*.pyi" -File -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force

$keepQtDll = @(
    "Qt6Core.dll", "Qt6Gui.dll", "Qt6Widgets.dll", "Qt6Svg.dll", "Qt6Network.dll",
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
    "vcruntime140.dll", "vcruntime140_1.dll", "vcruntime140_threads.dll", "concrt140.dll", "vccorlib140.dll"
)
Get-ChildItem (Join-Path $qtRoot "Qt6\bin") -File -ErrorAction SilentlyContinue |
    Where-Object { $keepQtDll -notcontains $_.Name } |
    Remove-Item -Force

$keepPlugins = @("platforms", "styles", "imageformats", "iconengines", "tls")
Get-ChildItem (Join-Path $qtRoot "Qt6\plugins") -Directory -ErrorAction SilentlyContinue |
    Where-Object { $keepPlugins -notcontains $_.Name } |
    Remove-Item -Recurse -Force

Get-ChildItem (Join-Path $appDir "site-packages") -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

# 3) Tools pack for PCs that update in-app (hosted as a release asset, rebuilt only when the tools change)
$toolHashes = (Get-ChildItem $toolsDir -File | Where-Object Name -ne "version.txt" | Sort-Object Name |
    ForEach-Object { "$($_.Name):$((Get-FileHash $_.FullName -Algorithm SHA256).Hash)" }) -join ";"
$sha = [System.Security.Cryptography.SHA256]::Create()
$toolsVersion = ([BitConverter]::ToString($sha.ComputeHash([Text.Encoding]::ASCII.GetBytes($toolHashes))) -replace "-", "").Substring(0, 12).ToLower()
Set-Content -Path (Join-Path $toolsDir "version.txt") -Value $toolsVersion -NoNewline -Encoding ascii

$toolsPack  = Join-Path $out "Scorpion-Tools.zip"
$toolsStamp = Join-Path $out "Scorpion-Tools.version"
if (-not (Test-Path $toolsPack) -or -not (Test-Path $toolsStamp) -or (Get-Content $toolsStamp -Raw).Trim() -ne $toolsVersion) {
    Compress-Archive -Path (Join-Path $toolsDir "*") -DestinationPath $toolsPack -Force
    Set-Content -Path $toolsStamp -Value $toolsVersion -NoNewline -Encoding ascii
}

# 4) Update payload: the app only, so regular updates stay small (also saved to release\ for in-app updates)
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

# 5) Setup installer compiled with Inno Setup 6 (no PyInstaller --onefile self-extractor)
$appVersion = (Select-String -Path "$root\native_app\scorpion_qt.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' |
    Select-Object -First 1).Matches[0].Groups[1].Value
if (-not $appVersion) { throw "APP_VERSION not found in scorpion_qt.py" }
$setupName = "Scorpion-Setup-$appVersion"

& $iscc /Q `
    "/DAppVersion=$appVersion" `
    "/DAppDir=$appDir" `
    "/DToolsDir=$toolsDir" `
    "/DRepoRoot=$root" `
    "/DOutputDir=$work\setup_dist" `
    "/DOutputBaseName=$setupName" `
    "$root\native_app\installer\scorpion_setup.iss"
if ($LASTEXITCODE -ne 0) { throw "Inno Setup build failed" }

$stagedSetup = Join-Path "$work\setup_dist" "$setupName.exe"

# release\ keeps only the latest setup (git-ignored); Downloads keeps one per version
Get-ChildItem $out -Filter "Scorpion-Setup-*.exe" -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
Copy-Item $stagedSetup "$out\$setupName.exe" -Force

# The user's real Downloads folder (it can be moved away from %USERPROFILE%\Downloads)
$downloads = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path
if (-not $downloads -or -not (Test-Path $downloads)) { $downloads = Join-Path $env:USERPROFILE "Downloads" }
$dlSetup = Join-Path $downloads "$setupName.exe"
Copy-Item $stagedSetup $dlSetup -Force -ErrorAction Stop

Get-Item "$out\$setupName.exe", $dlSetup, "$out\Scorpion-Update-Payload.zip", $toolsPack |
    Select-Object FullName, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}
# Read by auto_publish.py: where the new setup was saved, and which tools pack update.json points to
Write-Output "SETUP_PATH=$dlSetup"
Write-Output "TOOLS_VERSION=$toolsVersion"
Write-Output "TOOLS_PACK=$toolsPack"
