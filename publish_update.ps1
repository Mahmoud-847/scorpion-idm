# Builds Scorpion IDM, generates release/update.json & release/Scorpion-Update-Payload.zip, and pushes to GitHub
$ErrorActionPreference = "Stop"
$root = $PSScriptRoot
Set-Location $root

Write-Host "==> 1. Building Scorpion IDM & Update Package..." -ForegroundColor Cyan
& "$root\build_installer.ps1"

Write-Host "==> 2. Publishing Update to GitHub (https://github.com/Mahmoud-847/scorpion-idm.git)..." -ForegroundColor Cyan
if (-not (Test-Path "$root\.git")) {
    git init
    git branch -M main
}
$remotes = git remote
if ($remotes -notcontains "origin") {
    git remote add origin "https://github.com/Mahmoud-847/scorpion-idm.git"
} else {
    git remote set-url origin "https://github.com/Mahmoud-847/scorpion-idm.git"
}

git add .
git commit -m "Release Scorpion IDM update" --allow-empty
git push -u origin main --force

Write-Host "==> Update published successfully to GitHub! All connected PCs will now receive this update." -ForegroundColor Green
