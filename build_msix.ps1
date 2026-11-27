param(
    [string]$OutputDirectory
)

$ErrorActionPreference = "Stop"
# Windows PowerShell's download progress bar slows Invoke-WebRequest down to a crawl
$ProgressPreference = "SilentlyContinue"
# Windows PowerShell 5.1 may not offer TLS 1.2 by default; nuget.org requires it
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12

# Build a Microsoft Store-ready unsigned MSIX package (Microsoft signs it cleanly on Store certification).
$root = $PSScriptRoot
$work = Join-Path $root "native_app\_build"
$out  = if ($OutputDirectory) { [IO.Path]::GetFullPath($OutputDirectory) } else { Join-Path $root "release" }

$py = (Get-Command py -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Source)
if (-not $py) { throw "Python launcher (py) is required" }

$appVersion = (Select-String -Path "$root\native_app\scorpion_qt.py" -Pattern 'APP_VERSION\s*=\s*"([^"]+)"' |
    Select-Object -First 1).Matches[0].Groups[1].Value
if (-not $appVersion) { throw "APP_VERSION not found in scorpion_qt.py" }
$verParts = $appVersion.Split(".")
while ($verParts.Count -lt 4) { $verParts += "0" }
$msixVersion = ($verParts[0..3]) -join "."
$minimumStoreVersion = [version]"2.1.31.0"
if ([version]$msixVersion -lt $minimumStoreVersion) {
    $msixVersion = $minimumStoreVersion.ToString(4)
}

# 1) Ensure MakeAppx.exe + MakePri.exe from official Microsoft Windows SDK BuildTools
# Outside native_app\_build: build_installer.ps1 wipes that folder on every release
$sdkRoot = Join-Path $root "build\sdk_tools"
$makeAppx = Get-ChildItem "C:\Program Files (x86)\Windows Kits\10\bin" -Filter "makeappx.exe" -Recurse -ErrorAction SilentlyContinue |
    Where-Object { $_.FullName -match "\\x64\\makeappx\.exe$" } |
    Select-Object -Last 1 -ExpandProperty FullName
$makePri = if ($makeAppx) { Join-Path (Split-Path $makeAppx) "makepri.exe" } else { $null }

if (-not $makeAppx -or -not (Test-Path $makePri)) {
    $cachedMakeAppx = Get-ChildItem $sdkRoot -Filter "makeappx.exe" -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\makeappx\.exe$" } |
        Select-Object -Last 1 -ExpandProperty FullName
    $cachedMakePri = if ($cachedMakeAppx) { Join-Path (Split-Path $cachedMakeAppx) "makepri.exe" } else { $null }

    if (-not $cachedMakeAppx -or -not (Test-Path $cachedMakePri)) {
        Write-Host "Fetching official Microsoft.Windows.SDK.BuildTools package..."
        New-Item -ItemType Directory -Force -Path $sdkRoot | Out-Null
        $idx = Invoke-RestMethod -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/index.json" -TimeoutSec 20
        $sdkVer = ($idx.versions | Where-Object { $_ -notmatch "-" -and $_ -match "^10\.0\.(22621|26100|28000)\." } | Select-Object -Last 1)
        if (-not $sdkVer) {
            $sdkVer = ($idx.versions | Where-Object { $_ -notmatch "-" } | Select-Object -Last 1)
        }
        $nupkg = Join-Path $sdkRoot "sdk_buildtools.zip"
        Invoke-WebRequest -Uri "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/$sdkVer/microsoft.windows.sdk.buildtools.$sdkVer.nupkg" -OutFile $nupkg -UseBasicParsing
        Expand-Archive -Path $nupkg -DestinationPath $sdkRoot -Force
        Remove-Item $nupkg -Force -ErrorAction SilentlyContinue

        $cachedMakeAppx = Get-ChildItem $sdkRoot -Filter "makeappx.exe" -Recurse |
            Where-Object { $_.FullName -match "\\x64\\makeappx\.exe$" } |
            Select-Object -Last 1 -ExpandProperty FullName
        $cachedMakePri = if ($cachedMakeAppx) { Join-Path (Split-Path $cachedMakeAppx) "makepri.exe" } else { $null }
    }

    $makeAppx = $cachedMakeAppx
    $makePri = $cachedMakePri
}

if (-not $makeAppx -or -not (Test-Path $makePri)) {
    throw "Failed to locate MakeAppx.exe and MakePri.exe"
}
foreach ($toolExe in @($makeAppx, $makePri)) {
    $sig = Get-AuthenticodeSignature $toolExe
    if ($sig.Status -ne "Valid" -or $sig.SignerCertificate.Subject -notmatch "Microsoft") {
        throw "Invalid Microsoft digital signature on SDK tool: $toolExe ($($sig.Status))"
    }
}
Write-Host "Using Microsoft-signed SDK tools: $makeAppx"

# 2) Ensure staged desktop runtime exists cleanly (and always refresh latest app & extension sources)
$appDist = Join-Path $work "dist\ScorpionIDM"
$toolsDir = Join-Path $root "build\tools"
if (-not (Test-Path "$appDist\ScorpionIDM.exe") -or -not (Test-Path "$toolsDir\ffmpeg.exe")) {
    & "$root\build_installer.ps1"
    if ($LASTEXITCODE -ne 0) { throw "Prerequisite build_installer.ps1 failed" }
}

$msixStage = Join-Path $work "msix_stage"
Remove-Item $msixStage -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path $msixStage, $out | Out-Null

Copy-Item "$appDist\*" $msixStage -Recurse -Force
# Refresh Python sources, icons, and extension assets directly from repo so MSIX matches HEAD even if dist was cached
Copy-Item "$root\native_app\scorpion_qt.py", "$root\native_app\sitecustomize.py", "$root\native_app\media_transfer.py", "$root\native_app\scorpion_brand.py", "$root\native_app\scorpion_cards.py" "$msixStage\app" -Force
Remove-Item "$msixStage\browser-extension" -Recurse -Force -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force -Path "$msixStage\browser-extension" | Out-Null
Get-ChildItem "$root\browser-extension" -Force | Where-Object { $_.Name -ne "bridge-auth.json" } | ForEach-Object {
    Copy-Item $_.FullName (Join-Path "$msixStage\browser-extension" $_.Name) -Recurse -Force
}

New-Item -ItemType Directory -Force -Path "$msixStage\tools" | Out-Null
Copy-Item "$toolsDir\*" "$msixStage\tools" -Recurse -Force

Get-ChildItem $msixStage -Directory -Recurse -Filter "__pycache__" -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force
Get-ChildItem $msixStage -Filter "bridge-auth.json" -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force
Get-ChildItem $msixStage -Filter "*.pyc" -Recurse -ErrorAction SilentlyContinue | Remove-Item -Force

# 3) Generate MSIX visual assets + manifest + PRI resource index
& $py -3.14 "$root\native_app\msix\generate_msix_assets.py" "$msixStage\Assets"
if ($LASTEXITCODE -ne 0) { throw "Generating MSIX visual assets failed" }

$manifestTpl = Get-Content "$root\native_app\msix\AppxManifest.xml.template" -Raw -Encoding utf8
$manifestXml = $manifestTpl.Replace("__MSIX_VERSION__", $msixVersion)
Set-Content -Path "$msixStage\AppxManifest.xml" -Value $manifestXml -Encoding utf8

$priCfg = Join-Path $work "priconfig.xml"
Remove-Item $priCfg -Force -ErrorAction SilentlyContinue
& $makePri createconfig /cf "$priCfg" /dq "en-US" /o | Out-Null
if ($LASTEXITCODE -ne 0) { throw "MakePri createconfig failed" }
& $makePri new /pr "$msixStage" /cf "$priCfg" /of "$msixStage\resources.pri" /o | Out-Null
if ($LASTEXITCODE -ne 0) { throw "MakePri new failed" }

# 4) Pack MSIX package
$msixName = "Scorpion-Download-Manager-$msixVersion-x64.msix"
$outMsix = Join-Path $out $msixName
& $makeAppx pack /o /d "$msixStage" /p "$outMsix"
if ($LASTEXITCODE -ne 0) { throw "MakeAppx pack failed" }

$dlMsix = $outMsix
if (-not $OutputDirectory) {
    $downloads = (New-Object -ComObject Shell.Application).NameSpace('shell:Downloads').Self.Path
    if (-not $downloads -or -not (Test-Path $downloads)) { $downloads = Join-Path $env:USERPROFILE "Downloads" }
    $dlMsix = Join-Path $downloads $msixName
    Copy-Item $outMsix $dlMsix -Force
}

$hash = (Get-FileHash $dlMsix -Algorithm SHA256).Hash.ToLower()
$mb = [math]::Round((Get-Item $dlMsix).Length / 1MB, 1)
Write-Output "MSIX_PATH=$dlMsix"
Write-Output "MSIX_SIZE_MB=$mb"
Write-Output "MSIX_SHA256=$hash"
