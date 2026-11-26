# Scorpion Download Manager (`Scorpion IDM`) 🦂⚡

A native Windows desktop download manager (`PyQt6` + officially signed `Python 3.14` runtime) designed for high-speed multi-connection file downloads, video and audio capture, and BitTorrent/Magnet management.

- ⬇️ **Latest Windows Installer (`v2.1.30`):** [GitHub Releases](https://github.com/Mahmoud-847/scorpion-idm/releases/latest)
- 🌐 **Official Microsoft Edge Extension:** [Scorpion IDM Integration Module — Microsoft Edge Add-ons](https://microsoftedge.microsoft.com/addons/detail/hgcdbjpjlfgnejhceobphikeebmhmgcj)
- 🔒 **Privacy Policy:** [PRIVACY.md](https://github.com/Mahmoud-847/scorpion-idm/blob/main/PRIVACY.md)
- 🎬 **Video Downloads & Support Scope:** [VIDEO_DOWNLOADS.md](VIDEO_DOWNLOADS.md)

---

## Key Features
- **Multi-Connection Acceleration & Strict Integrity:** Splits downloads over parallel `HTTP Range` connections with strict `Content-Range` and `Content-Length` verification, strong `ETag` / `Last-Modified` resume validation across both direct and 16-port video streams, and full TLS certificate verification.
- **Crash-Safe Pause & Resume:** Persists segment progress continuously with atomic `.bak`-backed state saves and supports refreshing expired download links (*Refresh Download Address*).
- **One-Click Media & Stream Capture:** Renders a compact **"Download with Scorpion"** floating bar above supported players with a live quality selector (`1080p` / `720p` / `M4A`), `ffprobe` stream validation, browser-session range transfer (e.g., Telegram Web), and per-installation authenticated local loopback communication on `127.0.0.1:19615` via Native Messaging (`com.scorpionidm.bridge`).
- **BitTorrent & Magnet Support (`BitTorrent` / `Magnet`):** Interactive inline file-tree preview and selective downloading powered by bundled `aria2c`, with atomic output finalization and rollback on move errors.
- **Modern Windows Desktop Experience:** Golden-Scorpion brand identity, Obsidian dark and light themes, stacked accessible download cards with keyboard navigation and screen-reader roles, corner progress toast cards, Windows taskbar progress indicators, and full English & Arabic (RTL) localization.
- **Distribution & Integrity Model:** Runs on the unmodified, digitally signed `Python Software Foundation (pythonw.exe)` host, while bundled `.py` source files and the `Inno Setup` installer are shipped **without independent code signing**; auto-update packages and compiled sources are verified against `SHA-256` checksums in `release/update.json`.

---

## Browser Integration
- **Microsoft Edge (One-Click Official Store Install):** Available directly on Microsoft Edge Add-ons:  
  https://microsoftedge.microsoft.com/addons/detail/hgcdbjpjlfgnejhceobphikeebmhmgcj  
  *(Note: If you previously loaded an unpacked development copy in `edge://extensions`, remove it first to avoid duplicate extension instances.)*
- **Google Chrome & Brave:** Open **Connect Browser** inside Scorpion IDM; the setup wizard prepares a persistent extension folder and provides step-by-step activation with automatic connection detection.

---

## Development, Testing & Building

The public landing page is a static site in `docs/`. To serve it on GitHub Pages, select **Deploy from a branch**, then `main` and `/docs` in the repository’s Pages settings. The download buttons point to the Windows installer asset on GitHub Releases. Update the link in the landing page, extension popup and welcome page when changing the advertised installer version.

### 1. Run Directly from Source
```powershell
py -3.14 native_app/scorpion_qt.py
```

### 2. Run Automated Test Suites (Python + Browser Extension)
```powershell
py -3.14 -m unittest discover -s tests -p "test_*.py" -v
node --test tests/browser-transfer.test.cjs tests/content-panel.test.cjs tests/popup.test.cjs
```

### 3. Build Windows Installer & Update Payload
```powershell
.\fetch_tools.ps1
.\build_installer.ps1
```
Builds `release/Scorpion-Setup-<version>.exe`, `release/Scorpion-Update-Payload.zip`, and `release/update.json` including `SHA-256` hashes for the update payload, bundled application scripts, and extension files.

### 4. Automated Publisher (GitHub Sync)
```powershell
py -3.14 auto_publish.py
```
