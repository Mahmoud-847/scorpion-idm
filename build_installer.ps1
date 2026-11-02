# Builds the Scorpion IDM app (PyInstaller onedir) and wraps it into a single Setup .exe
$ErrorActionPreference = "Stop"
$root  = $PSScriptRoot
$py    = "C:\Users\Mahmoud.emad\AppData\Local\Programs\Python\Python310\python.exe"
$work  = Join-Path $root "native_app\_build"
$out   = Join-Path $root "release"

Remove-Item $work -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $work, $out, "$work\setup_dist" | Out-Null

# 1) The application itself
& $py -m PyInstaller --noconfirm --clean --windowed --onedir `
    --name ScorpionIDM `
    --icon "$root\build\icon.ico" `
    --collect-submodules yt_dlp `
    --collect-submodules Cryptodome `
    --distpath "$work\dist" --workpath "$work\build" --specpath "$work" `
    "$root\native_app\scorpion_qt.py"
if ($LASTEXITCODE -ne 0) { throw "App build failed" }

$appDir = Join-Path $work "dist\ScorpionIDM"
Copy-Item "$root\browser-extension" "$appDir\browser-extension" -Recurse -Force
New-Item -ItemType Directory -Force -Path "$appDir\build" | Out-Null
Copy-Item "$root\build\icon.ico", "$root\build\icon.png", "$root\build\tray.png", "$root\build\aria2c.exe" "$appDir\build" -Force

# 2) Payload zip (also saved to release\Scorpion-Update-Payload.zip for in-app updates)
$payload = Join-Path $work "payload.zip"
Compress-Archive -Path "$appDir\*" -DestinationPath $payload -Force
Copy-Item $payload "$out\Scorpion-Update-Payload.zip" -Force

& $py -c "import sys, json; sys.path.insert(0, r'$root\native_app'); import scorpion_qt as sq; h = sq.CHANGELOG_HISTORY[0]; m = {'version': sq.APP_VERSION, 'publishedAt': h['date'], 'packageFile': 'Scorpion-Update-Payload.zip', 'downloadUrl': 'https://github.com/Mahmoud-847/scorpion-idm/raw/main/release/Scorpion-Update-Payload.zip', 'title_ar': h['title_ar'], 'title_en': h['title_en'], 'changelog_ar': h['ar'], 'changelog_en': h['en']}; open(r'$out\update.json', 'w', encoding='utf-8').write(json.dumps(m, ensure_ascii=False, indent=2))"

# 3) Setup wizard (single exe built into staging dir first, then copied atomically)
& $py -m PyInstaller --noconfirm --clean --windowed --onefile `
    --name "Scorpion-Setup-2.0.0" `
    --icon "$root\build\icon.ico" `
    --add-data "$payload;." --add-data "$root\build\icon.ico;." `
    --distpath "$work\setup_dist" --workpath "$work\setup_build" --specpath "$work" `
    "$root\native_app\installer\scorpion_setup.py"
if ($LASTEXITCODE -ne 0) { throw "Setup build failed" }

$stagedSetup = Join-Path "$work\setup_dist" "Scorpion-Setup-2.0.0.exe"

Copy-Item $stagedSetup "$out\Scorpion-Setup-2.0.0.exe" -Force
Copy-Item $stagedSetup "C:\Users\Mahmoud.emad\Desktop\Scorpion-Setup-2.0.0.exe" -Force -ErrorAction SilentlyContinue
Copy-Item $stagedSetup "C:\Users\Mahmoud.emad\Downloads\Scorpion-Setup-2.0.0.exe" -Force -ErrorAction SilentlyContinue

Get-Item "$out\Scorpion-Setup-2.0.0.exe", "C:\Users\Mahmoud.emad\Desktop\Scorpion-Setup-2.0.0.exe", "C:\Users\Mahmoud.emad\Downloads\Scorpion-Setup-2.0.0.exe" -ErrorAction SilentlyContinue | Select-Object FullName, @{N='MB';E={[math]::Round($_.Length/1MB,1)}}
