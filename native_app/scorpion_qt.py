# -*- coding: utf-8 -*-
import os
import sys

# Guard against pythonw.exe where sys.stdout / sys.stderr are None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import json
import copy
import html
import re
import time
import uuid
import shutil

# Resource root: install dir when frozen by PyInstaller, project root in dev mode
if getattr(sys, "frozen", False):
    RESOURCE_ROOT = os.path.dirname(sys.executable)
else:
    RESOURCE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Installed builds run on the official, signed Python runtime renamed to ScorpionIDM.exe, with this file
# in <install>/app (see build_installer.ps1). Older builds were frozen by PyInstaller.
EMBEDDED_RUNTIME = not getattr(sys, "frozen", False) and os.path.basename(sys.executable).lower() == "scorpionidm.exe"
INSTALLED = getattr(sys, "frozen", False) or EMBEDDED_RUNTIME
MS_STORE_APP_ID = "9N3ZB1H6C77W"
MS_STORE_APP_URL = f"ms-windows-store://pdp/?productid={MS_STORE_APP_ID}"


def is_msix_packaged() -> bool:
    """Returns True when running from an MSIX / Microsoft Store package."""
    try:
        if os.path.isfile(os.path.join(RESOURCE_ROOT, "AppxManifest.xml")):
            return True
    except Exception:
        pass
    if os.name == "nt":
        try:
            import ctypes

            buf_len = ctypes.c_uint32(0)
            rc = ctypes.windll.kernel32.GetCurrentPackageFullName(ctypes.byref(buf_len), None)
            if rc == 122:  # ERROR_INSUFFICIENT_BUFFER -> process has an app package identity
                return True
        except Exception:
            pass
    return False


def windows_display_language() -> str:
    if os.name == "nt":
        try:
            import ctypes

            language_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if language_id & 0x3FF == 0x01:
                return "ar"
        except (AttributeError, OSError):
            pass
    return "en"


import hashlib
import hmac
import http.cookiejar
import secrets
import socket
import base64
import urllib.parse
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
_APP_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
if _APP_MODULE_DIR not in sys.path:
    sys.path.insert(0, _APP_MODULE_DIR)

from media_transfer import BrowserTransferMixin, browser_local_url, fragment_url, finite_duration, validate_media
from scorpion_brand import (
    PALETTES as BRAND_PALETTES,
    TOKENS as BRAND_TOKENS,
    build_qss as brand_build_qss,
    outline_icon,
    outline_pixmap,
    prefers_reduced_motion,
    scorpion_emblem_icon,
    scorpion_emblem_pixmap,
)
from scorpion_cards import (
    DownloadCardRowDelegate,
    DownloadCardTableWidget,
    QueueSchedulerDialog,
    ROLE_CARD_META,
    SIDEBAR_ROLE_ICON,
    ScorpionTitleBar,
    SidebarDelegate,
    TorrentInlinePanel,
    apply_win32_window_effects,
)

# Verify HTTPS with the Windows certificate store (like browsers do), so antivirus or company HTTPS
# inspection (e.g. Kaspersky) doesn't fail every check while certificates stay verified
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

import requests

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QRectF, QPointF, QTime, QByteArray, QPoint, QPropertyAnimation, QEasingCurve, QEvent
from PyQt6.QtGui import QIcon, QFont, QColor, QPainter, QPen, QLinearGradient, QAction, QClipboard, QPainterPath, QPolygonF, QShortcut, QKeySequence
from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsDropShadowEffect,
    QSizePolicy,
    QScrollArea,
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QGridLayout,
    QSplitter,
    QTreeWidget,
    QTreeWidgetItem,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QMenuBar,
    QPushButton,
    QLabel,
    QLineEdit,
    QComboBox,
    QProgressBar,
    QTabWidget,
    QDialog,
    QFileDialog,
    QMessageBox,
    QSystemTrayIcon,
    QMenu,
    QFrame,
    QSpinBox,
    QTimeEdit,
    QCheckBox,
    QStackedWidget,
    QStyledItemDelegate,
    QStyle,
    QStyleOptionViewItem,
    QTextBrowser,
)

# ==============================================================================
# STYLESHEETS (OBSIDIAN & AMBER DESIGN TOKENS + COORDINATED LIGHT MODE)
# ==============================================================================
PALETTES = BRAND_PALETTES


def _is_dark_theme() -> bool:
    app = QApplication.instance()
    return True if app is None else (app.property("scorpionTheme") != "light")


def pal() -> dict:
    return PALETTES["dark" if _is_dark_theme() else "light"]


def L(text) -> str:
    """Keep numbers/units/latin readable inside Arabic (RTL) text."""
    return "\u200e" + str(text) + "\u200e"


def bidi_filename(name: str) -> str:
    """Isolate file extensions/numeric suffixes from RTL stems so .xlsx / .mp3 never visually reverse."""
    s = str(name or "")
    if not s:
        return ""
    if not re.search(r"[\u0600-\u06FF]", s):
        return "\u2066" + s + "\u2069"
    m = re.search(r"([0-9A-Za-z.-]*\.[A-Za-z0-9]{1,8})$", s)
    if m:
        return f"{s[:m.start()]}\u2066\u200e{m.group(1)}\u2069"
    return s


def mode_color(mode: str) -> str:
    p = pal()
    return {
        "done": p["success"],
        "error": p["danger"],
        "paused": p["warn"],
        "merging": p["accent"],
        "verifying": p["accent"],
        "saving": p["accent"],
    }.get(mode, p["accent"])


_ICON_FONT = None


def _icon_font_family() -> str:
    global _ICON_FONT
    if _ICON_FONT is None:
        from PyQt6.QtGui import QFontDatabase

        fams = QFontDatabase.families()
        _ICON_FONT = "Segoe Fluent Icons" if "Segoe Fluent Icons" in fams else "Segoe MDL2 Assets"
    return _ICON_FONT


def glyph_icon(code: str, color: str = None, size: int = 16) -> QIcon:
    """Returns crisp unified vector outline icon when named, falling back to OS icon font."""
    col = color or pal()["text"]
    if isinstance(code, str) and code.startswith("svg:"):
        return outline_icon(code[4:], col, size)
    from PyQt6.QtGui import QPixmap

    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont(_icon_font_family())
    f.setPixelSize(int(size * 1.6))
    p.setFont(f)
    p.setPen(QColor(col))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, code)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


APP_VERSION = "2.1.32"

# External programs shipped with the app: <install>/tools (ffmpeg, ffprobe + DLLs, QuickJS) and <install>/build (aria2c)
TOOLS_DIR = os.path.join(RESOURCE_ROOT, "tools")
TOOLS_PACK_FILES = ("ffmpeg.exe", "ffprobe.exe", "qjs.exe")


def find_tool(name: str) -> str:
    """Path of a bundled program, falling back to one installed on the PC (developer machines)."""
    exe = name if name.lower().endswith(".exe") else name + ".exe"
    for cand in (
        os.path.join(TOOLS_DIR, exe),
        os.path.join(RESOURCE_ROOT, "build", exe),
        os.path.join(RESOURCE_ROOT, "build", "tools", exe),
        shutil.which(name) or "",
        os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Links\{exe}"),
    ):
        if cand and os.path.isfile(cand):
            return cand
    return ""


DRM_VIDEO_DOMAINS = (
    "netflix.com",
    "disneyplus.com",
    "primevideo.com",
    "shahid.mbc.net",
    "watchit.com",
    "osnplus.com",
    "tv.apple.com",
    "hulu.com",
    "max.com",
    "peacocktv.com",
    "paramountplus.com",
    "tod.tv",
    "starzplay.com",
)


def is_drm_video_url(url: str) -> bool:
    try:
        p = urllib.parse.urlparse((url or "").strip())
        host = (p.hostname or "").lower()
        if not host:
            return False
        if any(host == d or host.endswith("." + d) for d in DRM_VIDEO_DOMAINS):
            return True
        if re.search(r"(^|\.)amazon\.[a-z.]+$", host) and re.match(r"^/(gp/video|detail)\b", p.path or "", re.I):
            return True
    except Exception:
        pass
    return False


def needs_login(err) -> bool:
    text = str(err).lower()
    return any(k in text for k in ("registered users", "login required", "log in", "sign in", "cookies", "private video",
                                   "rate-limit reached or login", "requires authentication"))


def localize_error_msg(msg, is_ar: bool) -> str:
    """Translate known user-facing download errors cleanly between Arabic and English."""
    text = str(msg or "").replace("ERROR:", "").strip()
    low = text.lower()
    if any(k in low for k in ("drm protected", "this video is drm", "widevine", "playready", "encrypted media", "تشفير drm")):
        return (
            "هذا المحتوى محمي بتشفير DRM (مثل Netflix / Shahid) ولا يدعم التنزيل الخارجي. استخدم ميزة التنزيل داخل التطبيق الرسمي للمنصة."
            if is_ar
            else "DRM-protected content (e.g. Netflix / Shahid) cannot be downloaded externally. Use the official app's download feature."
        )
    if needs_login(text) or "محتاج تسجيل دخول" in text:
        return (
            "الفيديو ده محتاج تسجيل دخول في الموقع. افتح الموقع في المتصفح وسجّل دخول، وبعدين اضغط زر التحميل اللي فوق الفيديو تاني."
            if is_ar
            else "This video requires signing in on the site. Log in in your browser, then click the floating download button again."
        )
    if "unsupported url" in low or "مش لفيديو واحد" in text:
        return (
            "العنوان ده مش لفيديو واحد (زي صفحة بروفايل أو فيد). شغّل الفيديو نفسه واضغط زر التحميل اللي فوقه، أو افتح المنشور لوحده وانسخ عنوانه."
            if is_ar
            else "This URL is not a single video (it may be a profile or feed page). Play the video itself and use its button, or copy the post URL."
        )
    if any(k in low for k in ("403: forbidden", "http error 403", "http 403")):
        return (
            "رفض الخادم الوصول للرابط (HTTP 403). أعد فتح صفحة الفيديو واضغط زر التنزيل لتجديد الرابط."
            if is_ar
            else "The server denied access to this stream (HTTP 403). Reopen the video page and click download to refresh the link."
        )
    if any(k in low for k in ("certificate_verify_failed", "certificate verify failed", "sslerror", "self-signed certificate")):
        return (
            "تعذر التحقق من شهادة الأمان للخادم (SSL/TLS)."
            if is_ar
            else "Server SSL/TLS certificate verification failed."
        )
    if "invalid byte range" in low or "wrong byte range" in low:
        return (
            "أرجع الخادم نطاق بايتات غير صالح."
            if is_ar
            else "The server returned an invalid byte range."
        )

    exact_pairs = (
        (
            "تعذر نقل مخرجات التورنت",
            "Failed to move completed torrent files to the save folder. Source files were preserved.",
        ),
        (
            "لم يتم العثور على ملفات التورنت",
            "Completed torrent output files could not be found.",
        ),
        (
            "تعذر تنزيل الفيديو المحدد",
            "Could not download the selected video. Reopen the video page, play it briefly, and click the download button above it.",
        ),
        (
            "ما قدرناش نلاقي الفيديو في الصفحة دي",
            "Could not find a downloadable video on this page. Sign in if required, play the video for a few seconds, and click its download button.",
        ),
        (
            "العنوان يحتوي على عدة فيديوهات",
            "This URL contains multiple videos. Open the specific video on its own page and try again.",
        ),
        (
            "فيديو تليجرام مرتبط بجلسة المتصفح",
            "Telegram videos are tied to the browser session. Open the video in Telegram Web and click the download button above it.",
        ),
        (
            "الملف مرتبط بجلسة المتصفح",
            "This file is tied to the browser session. Reopen the video in your browser and click download again.",
        ),
        (
            "الرابط يخص جزءًا من البث",
            "This URL points to a single stream segment. Please use the full video or stream URL.",
        ),
        (
            "تعذر استخراج بيانات الفيديو",
            "Could not extract video stream information.",
        ),
        (
            "لم ينتج التنزيل ملف فيديو",
            "No video file was produced by the download. Please retry from the player.",
        ),
        (
            "فشل دمج الصوت والصورة",
            "Failed to merge audio and video tracks. The incomplete file was not saved.",
        ),
        (
            "فشل تحويل الصوت",
            "Failed to convert audio track. The incomplete file was not saved.",
        ),
        (
            "أداة فحص الفيديو غير متاحة",
            "Media verification tool (ffprobe) is unavailable. Update app tools and retry.",
        ),
        (
            "الملف المستلم غير قابل للتشغيل أو غير مكتمل",
            "The downloaded media file is incomplete or unplayable. Please retry from the player.",
        ),
        (
            "الملف المستلم لا يحتوي على المسار المطلوب",
            "The downloaded file is missing the required media track. Please retry from the player.",
        ),
        (
            "التنزيل وصل من غير الصوت الموجود في المصدر",
            "The video downloaded without its audio track. Please retry.",
        ),
        (
            "مدة الملف أقصر من الفيديو الأصلي",
            "The downloaded file is shorter than the original media and was rejected as incomplete. Please retry.",
        ),
        (
            "الملف لم يصل بحجمه الكامل",
            "The downloaded file size did not match the server total. Please retry.",
        ),
        (
            "التنزيل من المتصفح انقطع",
            "Browser media transfer was interrupted. Reopen the video and try again.",
        ),
        (
            "انقطع الاتصال بتبويب الفيديو",
            "Lost connection to the video browser tab. Reopen it and start the download again.",
        ),
        (
            "تم إلغاء التنزيل. اضغط زر التنزيل",
            "Download cancelled. Click the floating download button on the video in your browser to restart.",
        ),
        (
            "جلسة التنزيل انتهت",
            "Browser transfer session expired. Please retry from the browser.",
        ),
        (
            "الفيديو لم يصل بالكامل",
            "The video did not transfer completely. Please retry from your browser.",
        ),
        (
            "تعذر إنشاء ملف التنزيل",
            "Could not create the download file. Check free disk space and folder permissions.",
        ),
    )
    for ar_needle, en_msg in exact_pairs:
        if ar_needle in text or en_msg.lower() == low:
            return text if (is_ar and ar_needle in text) else (en_msg if not is_ar else text)

    if "aria2c torrent engine not found" in low:
        return "محرك التورنت aria2c غير موجود." if is_ar else "aria2c torrent engine not found."
    return text


def friendly_video_error(err, is_ar: bool = True) -> str:
    """Why a video failed, in words the user can act on (same rules for every site)."""
    return localize_error_msg(err, is_ar)


def video_format_for(quality: str, has_ffmpeg: bool = True) -> str:
    """yt-dlp format selector for a quality picked by the user: "best", "audio" or a height like "1080p"."""
    import re

    m = re.fullmatch(r"(\d{3,4})p", (quality or "").strip().lower())
    if not has_ffmpeg:
        # Without ffmpeg only single-file formats (video + audio together) can be saved
        return f"best[height<={m.group(1)}]/best" if m else "best"
    if quality == "audio":
        return "bestaudio[ext=m4a]/bestaudio/best"
    if m:
        h = m.group(1)
        # The exact height first (H.264 plays everywhere, other codecs if that's all there is at this height),
        # then the closest lower one
        return (
            f"bestvideo[height={h}][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height={h}]+bestaudio/"
            f"bestvideo[height<={h}][vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[height<={h}]+bestaudio/"
            f"best[height<={h}]/best"
        )
    # Prefer H.264 (avc1): AV1/VP9 files do not play in the default Windows player
    return "bestvideo[vcodec^=avc1]+bestaudio[ext=m4a]/bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best"


# Local browser bridge (127.0.0.1:19615): only our extension or authenticated local clients are trusted.
BRIDGE_CLIENT_HEADER = "X-Scorpion-Client"
BRIDGE_TOKEN_HEADER = "X-Scorpion-Token"
BRIDGE_ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://", "extension://")
NATIVE_HOST_NAME = "com.scorpionidm.bridge"
OFFICIAL_EXTENSION_ID = "hgcdbjpjlfgnejhceobphikeebmhmgcj"


def load_or_create_bridge_token(app_data_dir: str = "") -> str:
    """Return the per-installation secret token shared between the desktop app and local extension."""
    base = app_data_dir or os.path.join(os.path.expanduser("~"), "AppData", "Local", "ScorpionIDM")
    tok_path = os.path.join(base, "store_bridge_token" if is_msix_packaged() else "bridge_token")
    try:
        if os.path.isfile(tok_path):
            with open(tok_path, "r", encoding="utf-8") as f:
                val = f.read().strip()
            if len(val) >= 32:
                return val
    except OSError:
        pass
    val = secrets.token_hex(32)
    try:
        os.makedirs(base, exist_ok=True)
        tmp = f"{tok_path}.{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(val)
        os.replace(tmp, tok_path)
    except OSError:
        pass
    return val


_EXTENSION_HASH_FILES = (
    "manifest.json",
    "background.js",
    "content.js",
    "popup.js",
    "welcome.html",
    "welcome.css",
    "welcome.js",
    "media.js",
    "browser-transfer.js",
    "telegram-reader.js",
)


def _canon_ext_dir(path: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.abspath(path)))


def _ext_dir_matches_reference(candidate_dir: str, ref_dir: str) -> bool:
    if not candidate_dir or not ref_dir or not os.path.isdir(candidate_dir) or os.path.islink(candidate_dir):
        return False
    def fingerprint(folder):
        entries = {}
        for base, dirs, files in os.walk(folder):
            if any(os.path.islink(os.path.join(base, d)) for d in dirs):
                raise OSError("Linked extension directory")
            for name in files:
                if name == "bridge-auth.json":
                    continue
                path = os.path.join(base, name)
                if os.path.islink(path):
                    raise OSError("Linked extension file")
                with open(path, "rb") as stream:
                    entries[os.path.relpath(path, folder)] = hashlib.sha256(stream.read()).hexdigest()
        return entries
    try:
        reference = fingerprint(ref_dir)
        return bool(reference and "manifest.json" in reference and fingerprint(candidate_dir) == reference)
    except OSError:
        return False


def _trusted_local_extension_dirs(ext_source_dir: str = "") -> set:
    trusted = set()
    ref_dir = ""
    candidates = []
    if ext_source_dir:
        candidates.append(ext_source_dir)
    if RESOURCE_ROOT:
        candidates.append(os.path.join(RESOURCE_ROOT, "browser-extension"))
    proj_ext = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "browser-extension")
    candidates.append(proj_ext)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(os.path.join(local, "ScorpionIDM", "browser-extension"))
        candidates.append(os.path.join(local, "Programs", "ScorpionIDM", "browser-extension"))
    for p in candidates:
        if p and os.path.isdir(p) and not os.path.islink(p):
            trusted.add(_canon_ext_dir(p))
            if not ref_dir and os.path.isfile(os.path.join(p, "manifest.json")):
                ref_dir = p
    dl_ext = os.path.join(os.path.expanduser("~"), "Downloads", "Scorpion-Browser-Extension")
    if ref_dir and _ext_dir_matches_reference(dl_ext, ref_dir):
        trusted.add(_canon_ext_dir(dl_ext))
    return trusted


def _discover_unpacked_extension_origins(ext_source_dir: str = "") -> list:
    import glob

    origins = [f"chrome-extension://{OFFICIAL_EXTENSION_ID}/"]
    if os.name != "nt":
        return origins
    local = os.environ.get("LOCALAPPDATA", "")
    if not local:
        return origins
    trusted_dirs = _trusted_local_extension_dirs(ext_source_dir)
    if not trusted_dirs:
        return origins
    for rel in ("Microsoft/Edge/User Data", "Google/Chrome/User Data", "BraveSoftware/Brave-Browser/User Data"):
        base = os.path.join(local, rel)
        for pattern in (os.path.join(base, "*", "Preferences"), os.path.join(base, "*", "Secure Preferences")):
            for pref_path in glob.glob(pattern):
                try:
                    with open(pref_path, "r", encoding="utf-8", errors="ignore") as f:
                        settings = (json.load(f).get("extensions") or {}).get("settings") or {}
                    for ext_id, info in settings.items():
                        if not isinstance(info, dict) or not re.fullmatch(r"[a-p]{32}", str(ext_id or "")):
                            continue
                        raw_path = str(info.get("path") or "").strip()
                        if not raw_path or not os.path.isdir(raw_path) or os.path.islink(raw_path):
                            continue
                        if _canon_ext_dir(raw_path) in trusted_dirs:
                            orig = f"chrome-extension://{ext_id}/"
                            if orig not in origins:
                                origins.append(orig)
                except Exception:
                    pass
    return origins


def register_native_messaging_hosts(app_data_dir: str = "", write_registry: bool = True):
    """Register HKCU native messaging host manifest so extensions obtain bridge_token securely."""
    if is_msix_packaged():
        return
    base = app_data_dir or os.path.join(os.path.expanduser("~"), "AppData", "Local", "ScorpionIDM")
    try:
        os.makedirs(base, exist_ok=True)
        bat_path = os.path.join(base, "native_host.bat")
        manifest_path = os.path.join(base, f"{NATIVE_HOST_NAME}.json")
        exe_cand = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ScorpionIDM", "ScorpionIDM.exe")
        inst_site = os.path.join(os.path.dirname(exe_cand), "app", "sitecustomize.py")
        if os.path.isfile(exe_cand) and os.path.isfile(inst_site):
            bat_cmd = f'@echo off\r\n"{exe_cand}" "{inst_site}" --native-messaging %*\r\n'
        else:
            dev_site = os.path.join(os.path.dirname(os.path.abspath(__file__)), "sitecustomize.py")
            bat_cmd = f'@echo off\r\n"{sys.executable}" "{dev_site}" --native-messaging %*\r\n'
        with open(bat_path, "w", encoding="utf-8", newline="") as bf:
            bf.write(bat_cmd)
        manifest = {
            "name": NATIVE_HOST_NAME,
            "description": "Scorpion Download Manager Local Bridge Pairing Host",
            "path": bat_path,
            "type": "stdio",
            "allowed_origins": _discover_unpacked_extension_origins(),
        }
        with open(manifest_path, "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2)
        if write_registry and os.name == "nt":
            real_base = os.path.normcase(os.path.abspath(os.path.join(os.path.expanduser("~"), "AppData", "Local", "ScorpionIDM")))
            if os.path.normcase(os.path.abspath(base)) == real_base:
                import winreg

                for root_sub in (
                    r"Software\Microsoft\Edge\NativeMessagingHosts",
                    r"Software\Google\Chrome\NativeMessagingHosts",
                    r"Software\BraveSoftware\Brave-Browser\NativeMessagingHosts",
                ):
                    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{root_sub}\\{NATIVE_HOST_NAME}") as key:
                        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, manifest_path)
    except Exception:
        pass


CHANGELOG_HISTORY = [
    {
        "version": "2.1.33",
        "date": "2026-11-27",
        "title_ar": "اسم واحد واضح للبرنامج",
        "title_en": "One clear name everywhere",
        "ar": [
            "البرنامج والإضافة يظهران باسم «Scorpion Download Manager» في كل مكان.",
            "إصلاح ظهور علامة «+» مرتين على زر «إضافة رابط».",
        ],
        "en": [
            "The app and the extension now show the name “Scorpion Download Manager” everywhere.",
            "Fix the “Add URL” button showing the plus sign twice.",
        ],
    },
    {
        "version": "2.1.32",
        "date": "2026-11-26",
        "title_ar": "إصلاح تنزيل يوتيوب",
        "title_en": "YouTube downloads fixed",
        "ar": [
            "إصلاح فشل تنزيل فيديوهات يوتيوب وظهور «تعذر قراءة الجودات» عند تسجيل الدخول في المتصفح، بعد تغيير في يوتيوب.",
        ],
        "en": [
            "Fix YouTube downloads failing, and “Could not read qualities”, when signed in to YouTube in the browser, after a change on YouTube's side.",
        ],
    },
    {
        "version": "2.1.31",
        "date": "2026-11-26",
        "title_ar": "تنزيل أدق وأمان أكثر وبرنامج أخف",
        "title_en": "More precise downloads, safer, lighter",
        "ar": [
            "كليك يمين «تنزيل الفيديو» لم يعد ينزّل فيديو آخر في الصفحات التي فيها أكثر من فيديو.",
            "المواقع لم تعد تستطيع بدء تنزيل من غير ما تضغط أنت على الزر.",
            "البرنامج يفتح أسرع، ولا يتجمد عند إلغاء تنزيل تيليجرام وهو على وشك الانتهاء.",
            "لو حدث خطأ غير متوقع في الواجهة يكمل البرنامج عمله بدل أن يُغلق.",
            "عدد الاتصالات الذي تختاره في الإعدادات يبقى كما هو بعد إعادة التشغيل.",
            "الإضافة أخف على صفحات فيسبوك والصفحات الطويلة أثناء التمرير.",
            "المشغلات المضمّنة في المقالات تحتفظ بالفيديو حتى لو تغيّر رابط الصفحة.",
            "حفظ الملفات التي أسماؤها محجوزة في ويندوز (مثل CON) بدل فشل التنزيل.",
            "إلغاء تثبيت البرنامج ينظّف ربطه بالمتصفحات بالكامل.",
        ],
        "en": [
            "Right-click “Download video” no longer downloads a different video on pages with several videos.",
            "Websites can no longer start a download without you clicking the button.",
            "The app opens faster and no longer freezes when you cancel a Telegram download that is about to finish.",
            "An unexpected error in the window no longer closes the app.",
            "The number of connections you choose in Settings is kept after a restart.",
            "The extension is lighter on Facebook and other long pages while scrolling.",
            "Players embedded in articles keep their video even when the page address changes.",
            "Files whose names Windows reserves (such as CON) are saved instead of failing.",
            "Uninstalling now fully removes the app's link to your browsers.",
        ],
    },
    {
        "version": "2.1.30",
        "date": "2026-11-26",
        "title_ar": "قائمة الجودات وإصلاحات التشغيل",
        "title_en": "Quality list and startup fixes",
        "ar": [
            "قائمة الجودات تظل ظاهرة عند التبديل بين العربية والإنجليزية.",
            "رسالة أوضح عندما لا توجد جودات للفيديو أو عندما لا يكون البرنامج متصلًا.",
            "أول تشغيل يتبع لغة التثبيت، وتبقى لغتك كما هي بعد التحديث.",
            "إصلاح تعليق التنزيل المؤجل عند بدئه أثناء فحص الرابط.",
        ],
        "en": [
            "The quality list stays visible when switching between Arabic and English.",
            "Clearer message when a video has no qualities or the app is not connected.",
            "The first run follows the installer's language, and your language is kept after updates.",
            "Fix a scheduled download getting stuck when started while its link was being checked.",
        ],
    },
    {
        "version": "2.1.29",
        "date": "2026-11-19",
        "title_ar": "ربط أسهل بين الإضافة والبرنامج",
        "title_en": "Easier setup between extension and app",
        "ar": [
            "إذا لم يكن البرنامج مثبتًا تعرض نافذة الإضافة زرًا لتحميله، مع صفحة ترحيب بخطوات البدء وتجربة تنزيل.",
            "الإضافة تتبع لغة المتصفح تلقائيًا، وملف تثبيت البرنامج يُنزَّل من المتصفح كالمعتاد.",
            "دعوة اختيارية لتقييم الإضافة بعد ثلاثة تنزيلات.",
        ],
        "en": [
            "When the app is not installed, the extension window shows a button to download it, with a welcome page and a test download.",
            "The extension follows your browser's language, and the app's installer downloads normally in the browser.",
            "An optional invitation to rate the extension after three downloads.",
        ],
    },
    {
        "version": "2.1.28",
        "date": "2026-11-18",
        "title_ar": "استكمال أوثق وسهولة استخدام",
        "title_en": "More reliable resume and accessibility",
        "ar": [
            "إذا تغيّر الملف على الخادم أثناء الإيقاف يبدأ التنزيل من جديد بدل خلط النسختين.",
            "اختيار الفيديو الذي تشير إليه أسرع، وقائمة الجودات تتحدّث عند تغيير الحساب.",
            "دعم قارئات الشاشة والتنقل بلوحة المفاتيح بين أزرار بطاقات التحميل.",
            "تحديد السرعة أدق في السرعات المنخفضة.",
        ],
        "en": [
            "If a file changes on the server while paused, the download restarts instead of mixing the two versions.",
            "Picking the video under the pointer is quicker, and the quality list refreshes when you switch accounts.",
            "Screen-reader support and keyboard navigation between download card buttons.",
            "More accurate speed limiting at low speeds.",
        ],
    },
    {
        "version": "2.1.27",
        "date": "2026-11-17",
        "title_ar": "شكل جديد بالكامل",
        "title_en": "A completely new look",
        "ar": [
            "هوية العقرب الذهبي الجديدة، وواجهة داكنة، وبطاقات تحميل مكدّسة، واختيار ملفات التورنت قبل التنزيل.",
            "إصلاح ملفات تصل ناقصة من بعض الخوادم.",
            "الحفاظ على تسجيل الدخول عند التنزيل من مواقع تحوّل الروابط.",
            "التحديث أكثر أمانًا: لا يتأثر البرنامج إذا حدث خطأ في آخر خطوة.",
            "ربط الإضافة بالبرنامج تلقائي وآمن.",
        ],
        "en": [
            "The new golden scorpion identity, a dark interface, stacked download cards, and choosing torrent files before downloading.",
            "Fix files arriving incomplete from some servers.",
            "Stay signed in when downloading from sites that redirect links.",
            "Safer updates: an error in the last step no longer harms the installed app.",
            "The extension connects to the app automatically and securely.",
        ],
    },
    {
        "version": "2.1.26",
        "date": "2026-11-17",
        "title_ar": "سلامة الملفات والأمان",
        "title_en": "File safety and security",
        "ar": [
            "التنظيف التلقائي يحذف ملفات البرنامج المؤقتة فقط ولا يلمس مجلد التنزيلات.",
            "الاستكمال يتأكد أن الملف ما زال هو نفسه على الخادم.",
            "قائمة التنزيلات محفوظة بنسخة احتياطية حتى لا تضيع إذا أُغلق الجهاز فجأة.",
            "تنزيلات التصفح الخفي منفصلة ولا تُحفظ في السجل.",
            "الإضافة لا تلغي تنزيل المتصفح إلا بعد أن يقبله البرنامج.",
        ],
        "en": [
            "Automatic cleanup only removes the app's own temporary files and never touches your downloads folder.",
            "Resuming checks that the file on the server is still the same one.",
            "The download list is backed up so it is not lost if the computer shuts down suddenly.",
            "Private-browsing downloads are kept separate and are not saved to the history.",
            "The extension only cancels the browser's download after the app accepts it.",
        ],
    },
    {
        "version": "2.1.25",
        "date": "2026-11-17",
        "title_ar": "إصلاح المشغلات المضمّنة وأسماء الملفات",
        "title_en": "Embedded players and file names",
        "ar": [
            "إصلاح فشل التنزيل (خطأ 403) من بعض مشغلات البث المضمّنة.",
            "الاحتفاظ بالاسم الحقيقي للملف عند تنزيل فيديو أو صوت مباشر.",
            "رسائل الخطأ بالإنجليزية عندما تكون الواجهة بالإنجليزية.",
        ],
        "en": [
            "Fix downloads failing (error 403) from some embedded streaming players.",
            "Keep the real file name when downloading a direct video or audio link.",
            "Error messages appear in English when the interface is in English.",
        ],
    },
    {
        "version": "2.1.24",
        "date": "2026-11-17",
        "title_ar": "ظهور التنزيلات فورًا",
        "title_en": "Downloads appear right away",
        "ar": [
            "كل تنزيل جديد يظهر فورًا في القائمة الرئيسية.",
            "رسالة تأكيد الإلغاء تظهر أمام كل النوافذ.",
            "إصلاح إظهار البرنامج من شريط المهام.",
        ],
        "en": [
            "Every new download appears in the main list right away.",
            "The cancel confirmation always appears in front of other windows.",
            "Fix showing the app from the taskbar.",
        ],
    },
    {
        "version": "2.1.23",
        "date": "2026-11-17",
        "title_ar": "واجهة أوضح في كل المراحل",
        "title_en": "A clearer interface at every step",
        "ar": [
            "بطاقة التحميل أوضح، بأزرار مرتبة وحركة أنعم.",
            "نافذة إضافة رابط جديدة تفحص الرابط دون أن تتوقف الواجهة، وتنبهك إذا كان الفيديو محميًا.",
            "نافذة التقدم تعرض رسائل الخطأ كاملة.",
            "تحسين نافذة الإضافة وشريط التنزيل.",
        ],
        "en": [
            "A clearer download card with better-ordered buttons and smoother motion.",
            "A new Add Link window checks the link without freezing and warns you about protected videos.",
            "The progress window shows error messages in full.",
            "Improved extension window and download bar.",
        ],
    },
    {
        "version": "2.1.22",
        "date": "2026-11-17",
        "title_ar": "المنصات المحمية والأسماء العربية",
        "title_en": "Protected platforms and Arabic names",
        "ar": [
            "زر التنزيل لا يظهر في المنصات المحمية مثل Netflix وShahid، مع رسالة توضح السبب.",
            "إصلاح تنزيل SoundCloud.",
            "تحسين تنزيل الأغاني من Spotify.",
            "إصلاح أسماء الملفات العربية التي كانت تظهر رموزًا غريبة.",
        ],
        "en": [
            "The download button is hidden on protected platforms such as Netflix and Shahid, with a message explaining why.",
            "Fix SoundCloud downloads.",
            "Improved song downloads from Spotify.",
            "Fix Arabic file names that showed garbled characters.",
        ],
    },
    {
        "version": "2.1.21",
        "date": "2026-11-13",
        "title_ar": "منع التكرار وزر الإلغاء",
        "title_en": "No duplicates and a Cancel button",
        "ar": [
            "منع تنزيل الرابط نفسه مرتين.",
            "زر «إلغاء» في بطاقة التحميل.",
            "إصلاح توقف تنزيل SoundCloud عند 20%.",
            "بدء أسرع مع المواقع البطيئة، والتعرف على امتدادات الملفات (مثل xlsx وcsv وpdf) تلقائيًا.",
        ],
        "en": [
            "The same link is no longer downloaded twice.",
            "A Cancel button on the download card.",
            "Fix SoundCloud downloads stopping at 20%.",
            "Faster start on slow sites, and file extensions (such as xlsx, csv, pdf) are detected automatically.",
        ],
    },
    {
        "version": "2.1.20",
        "date": "2026-11-13",
        "title_ar": "تنزيل الصوتيات",
        "title_en": "Audio downloads",
        "ar": [
            "شريط التنزيل يظهر فوق مشغلات الصوت.",
            "دعم كل صيغ الصوت المشهورة.",
            "إصلاح تنزيل المقاطع والرسائل الصوتية من تيليجرام.",
            "تنزيل الصوتيات التي تحتاج تسجيل دخول.",
        ],
        "en": [
            "The download bar appears over audio players.",
            "Support for all common audio formats.",
            "Fix downloading audio clips and voice messages from Telegram.",
            "Download audio that requires signing in.",
        ],
    },
    {
        "version": "2.1.18",
        "date": "2026-11-12",
        "title_ar": "الإضافة على متجر Microsoft Edge",
        "title_en": "The extension on the Microsoft Edge store",
        "ar": [
            "الإضافة الرسمية متاحة على متجر Microsoft Edge وتُثبَّت بضغطة واحدة.",
            "البرنامج يفرّق بين إضافة المتجر والنسخة اليدوية القديمة ويمنع تكرارهما.",
        ],
        "en": [
            "The official extension is on the Microsoft Edge store and installs in one click.",
            "The app tells the store extension apart from an older manual copy and avoids running both.",
        ],
    },
    {
        "version": "2.1.17",
        "date": "2026-11-08",
        "title_ar": "شريط تنزيل ثابت وسياسة خصوصية",
        "title_en": "Steady download bar and privacy policy",
        "ar": [
            "شريط الفيديو يعرض زر التنزيل والجودة فقط، دون حالات أو نسب.",
            "تنزيل فيديو من تيليجرام لا يمنع تنزيل فيديو آخر، ولا يتكرر تنزيل المصدر نفسه.",
            "تنزيل تيليجرام يبقى مرتبطًا بالفيديو الأصلي أثناء التمرير.",
            "سياسة خصوصية واضحة يمكن فتحها من نافذة الإضافة.",
        ],
        "en": [
            "The video bar shows only the download and quality buttons, with no status or percentages.",
            "A Telegram download no longer blocks downloading another video, and the same source is not downloaded twice.",
            "A Telegram download stays tied to its video while you scroll.",
            "A clear privacy policy, available from the extension window.",
        ],
    },
    {
        "version": "2.1.16",
        "date": "2026-11-04",
        "title_ar": "تنزيل أسرع وأوثق لفيديوهات تيليجرام",
        "title_en": "Faster, more reliable Telegram downloads",
        "ar": [
            "تنزيل فيديوهات تيليجرام أصبح أسرع.",
            "إصلاح فشل حفظ فيديو تيليجرام عندما يكون مجلد التنزيل على قرص غير C.",
            "زر «إلغاء» لتنزيلات تيليجرام بدل الإيقاف المؤقت، وحذف الملفات المؤقتة عند فشل التنزيل أو إلغائه.",
            "البرنامج يلتقط الآن ملفات كان المتصفح ينزّلها بنفسه بالخطأ (مثل ملفات ‎.ts).",
            "زر التنزيل يظهر الآن فوق مشغلات كانت تخفي الفيديو داخلها (مثل OK و VK)، ومع تغيير سيرفر المشاهدة.",
            "إصلاح فشل تنزيل الفيديو من مشغلات المواقع المضمّنة التي لا تعمل إلا داخل صفحة الموقع.",
        ],
        "en": [
            "Telegram video downloads are faster.",
            "Fix Telegram videos failing to save when the download folder is on a drive other than C.",
            "Telegram downloads get a Cancel button instead of Pause, and leftover temporary files are removed on failure or cancel.",
            "Some files the browser used to download by itself (such as .ts files) are now caught by Scorpion.",
            "The download button now appears on players that hide their video inside them (such as OK and VK), including after switching servers.",
            "Fix downloads failing from embedded site players that only work inside the site's own page.",
        ],
    },
    {
        "version": "2.1.15",
        "date": "2026-11-04",
        "title_ar": "تنزيل الفيديو الذي تختاره بالضبط",
        "title_en": "Download exactly the video you pick",
        "ar": [
            "تنزيل الفيديو الذي يقف عليه المؤشر أو الظاهر أمامك أثناء التمرير، حتى لو كان متوقفًا.",
            "فيديو يعمل في الخلفية لم يعد يغيّر الفيديو المختار.",
            "قائمة الجودات تخص الفيديو المختار دائمًا، فلا يُنزَّل مقطع آخر بالخطأ.",
        ],
        "en": [
            "Download the video under the pointer or in view while scrolling, even when it is paused.",
            "A video playing in the background no longer changes your selection.",
            "The quality list always belongs to the selected video, so a different clip is never downloaded by mistake.",
        ],
    },
    {
        "version": "2.1.14",
        "date": "2026-11-04",
        "title_ar": "ظهور البرنامج وثبات شريط التحميل",
        "title_en": "App startup and a steadier download bar",
        "ar": [
            "إصلاح تشغيل البرنامج بعد التحديث دون أن تظهر نافذته.",
            "شريط التحميل فوق الفيديو أصبح ثابتًا، يُسحب من مقبض واضح، ويظل مغلقًا حتى تنتقل لصفحة أخرى.",
        ],
        "en": [
            "Fix the app starting without showing its window after an update.",
            "The download bar over videos stays put, drags from a clear handle, and stays closed until you leave the page.",
        ],
    },
    {
        "version": "2.1.13",
        "date": "2026-11-04",
        "title_ar": "تنزيل فيديوهات تيليجرام وضمان اكتمال الفيديو",
        "title_en": "Telegram videos and complete-download checks",
        "ar": [
            "تنزيل فيديوهات تيليجرام ويب من زر التنزيل فوق الفيديو.",
            "الفيديو الناقص أو الأقصر من الأصلي لم يعد يظهر كتحميل مكتمل.",
            "التعرف على الفيديوهات في المواقع أصبح أدق.",
        ],
        "en": [
            "Download Telegram Web videos from the button on the video.",
            "A video that is incomplete or shorter than the original is no longer shown as complete.",
            "More accurate video detection on websites.",
        ],
    },
    {
        "version": "2.1.11",
        "date": "2026-11-03",
        "title_ar": "الإصدار 2.1.11",
        "title_en": "Version 2.1.11",
        "ar": [
            "تحسينات وإصلاحات عامة.",
        ],
        "en": [
            "General improvements and fixes.",
        ],
    },
    {
        "version": "2.1.10",
        "date": "2026-11-03",
        "title_ar": "الإصدار 2.1.10",
        "title_en": "Version 2.1.10",
        "ar": [
            "تحسينات وإصلاحات عامة.",
        ],
        "en": [
            "General improvements and fixes.",
        ],
    },
    {
        "version": "2.1.9",
        "date": "2026-11-03",
        "title_ar": "الإصدار 2.1.9",
        "title_en": "Version 2.1.9",
        "ar": [
            "تحسينات وإصلاحات عامة.",
        ],
        "en": [
            "General improvements and fixes.",
        ],
    },
    {
        "version": "2.1.8",
        "date": "2026-11-02",
        "title_ar": "الإصدار 2.1.8",
        "title_en": "Version 2.1.8",
        "ar": [
            "تحسينات وإصلاحات عامة.",
        ],
        "en": [
            "General improvements and fixes.",
        ],
    },
    {
        "version": "2.1.7",
        "date": "2026-11-02",
        "title_ar": "الإصدار 2.1.7",
        "title_en": "Version 2.1.7",
        "ar": [
            "تحسينات وإصلاحات عامة.",
        ],
        "en": [
            "General improvements and fixes.",
        ],
    },
    {
        "version": "2.1.6",
        "date": "2026-11-02",
        "title_ar": "الإصدار 2.1.6 — بحث واختصارات",
        "title_en": "Version 2.1.6 — Search & Shortcuts",
        "ar": [
            "خانة بحث في قائمة التحميلات بالاسم أو الرابط.",
            "اختصارات لوحة المفاتيح: Ctrl+N للإضافة، Ctrl+V للصق رابط، Ctrl+F للبحث، Delete للحذف، Enter لنافذة التقدم.",
            "عرض سبب فشل التحميل عند الوقوف على كلمة «فشل».",
            "تأكيد قبل حذف تحميل لم يكتمل.",
            "نافذة إضافة رابط أبسط وأوضح.",
        ],
        "en": [
            "Search box for the downloads list (file name or URL).",
            "Keyboard shortcuts: Ctrl+N add, Ctrl+V paste a link, Ctrl+F search, Delete, Enter opens the progress window.",
            "Hover “Failed” to see why a download failed.",
            "Confirmation before deleting an unfinished download.",
            "Simpler, clearer Add Download dialog.",
        ],
    },
    {
        "version": "2.1.4",
        "date": "2026-11-02",
        "title_ar": "الإصدار 2.1.4 — التحديث من داخل البرنامج",
        "title_en": "Version 2.1.4 — In-App Updates",
        "ar": [
            "التحديث من داخل البرنامج بضغطة زر، مع عرض ما الجديد.",
            "تحميل الصوتيات من SoundCloud والمواقع المدعومة وحفظها بصيغة MP3.",
            "شريط التحميل العائم في المتصفح: زر إغلاق وزر لتبديل اللغة.",
            "اختصارات سطح المكتب وقائمة ابدأ ترجع تلقائياً لو اتحذفت.",
        ],
        "en": [
            "One-click in-app updates with release notes.",
            "Audio downloads from SoundCloud and other supported sites, saved as MP3.",
            "Browser floating bar: close button and language toggle.",
            "Desktop and Start Menu shortcuts come back automatically if deleted.",
        ],
    },
    {
        "version": "2.0.0",
        "date": "2026-10-29",
        "title_ar": "الإصدار 2.0.0 — محرك 32 اتصال ودعم التورنت والفيديو",
        "title_en": "Version 2.0.0 — 32-Connection Engine, Video & Torrent Support",
        "ar": [
            "محرك تحميل يقسم الملفات والفيديوهات حتى 32 اتصالاً متوازياً، ويعيد توزيع الأجزاء عندما ينتهي أحدها مبكراً.",
            "تحميل ملفات التورنت وروابط ماجنت مع نافذة لاختيار الملفات.",
            "واجهة حديثة باللغتين العربية والإنجليزية مع الوضع الداكن والفاتح.",
        ],
        "en": [
            "Download engine that splits files and videos across up to 32 parallel connections, rebalancing when one finishes early.",
            "BitTorrent and Magnet support with a file selection dialog.",
            "Modern UI in Arabic and English with light and dark themes.",
        ],
    },
]


def _ver_tuple(v: str) -> tuple:
    parts = []
    for x in str(v or "").strip().lstrip("vV").split("."):
        num = "".join(ch for ch in x if ch.isdigit())
        parts.append(int(num) if num else 0)
    return tuple(parts or [0])


ICONS = {
    "add": "svg:add", "video": "svg:video", "torrent": "svg:torrents", "play": "svg:play", "pause": "svg:pause", "stop": "svg:stop",
    "delete": "svg:delete", "clear": "svg:clear", "browser": "svg:browser", "moon": "svg:moon", "sun": "svg:sun",
    "lang": "svg:lang", "folder": "svg:folder", "open": "svg:open_file", "close": "svg:close", "hide": "svg:minimize",
    "download": "svg:download", "settings": "svg:settings", "update": "svg:update",
    "search": "svg:search", "chevron": "svg:chevron_down", "probe": "svg:probe", "clock": "svg:clock", "calendar": "svg:calendar",
}


def build_qss(p: dict) -> str:
    return brand_build_qss(p)


LIGHT_QSS = build_qss(PALETTES["light"])
DARK_QSS = build_qss(PALETTES["dark"])

BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

CATEGORY_MAP = {
    "Compressed": [".zip", ".rar", ".7z", ".tar", ".gz", ".bz2", ".xz", ".tgz"],
    "Programs": [".exe", ".msi", ".dmg", ".pkg", ".deb", ".rpm", ".apk", ".iso", ".bat"],
    "Video": [".mp4", ".mkv", ".avi", ".mov", ".webm", ".flv", ".wmv", ".m4v", ".ts"],
    "Music": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus", ".amr", ".m4b", ".weba", ".aiff"],
    "Documents": [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx", ".txt", ".epub", ".csv"],
}


def format_bytes(b: int) -> str:
    if not b or b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    val = float(b)
    while val >= 1024 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    return f"{val:.2f} {units[i]}"


def format_speed(bps: int) -> str:
    if not bps or bps <= 0:
        return "0 KB/s"
    return f"{format_bytes(bps)}/s"


def format_eta(sec) -> str:
    if sec is None or sec < 0:
        return "—"
    if sec == 0:
        return "Done"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m {s}s"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def detect_category(filename: str, mime: str = "") -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    for cat, exts in CATEGORY_MAP.items():
        if ext in exts:
            return cat
    mime = (mime or "").lower()
    if mime.startswith("video/"):
        return "Video"
    if mime.startswith("audio/"):
        return "Music"
    if "pdf" in mime:
        return "Documents"
    if "zip" in mime or "compressed" in mime:
        return "Compressed"
    return "General"


def _fix_header_mojibake(val: str) -> str:
    if not val or not any("\u0080" <= ch <= "\u00ff" for ch in val):
        return val
    if any("\u0600" <= ch <= "\u06ff" for ch in val):
        return val
    try:
        fixed = val.encode("latin-1").decode("utf-8")
        if fixed and "\ufffd" not in fixed:
            return fixed
    except (UnicodeEncodeError, UnicodeDecodeError):
        pass
    return val


def sanitize_filename(name: str) -> str:
    fixed = _fix_header_mojibake(name or "")
    clean = "".join("_" if c in '<>:"/\\|?*\r\n\t' or ord(c) < 32 else c for c in (fixed or "download_file")).strip()
    # Windows refuses names ending in a dot or space, and device names such as CON.mp4 or NUL.txt
    clean = clean.rstrip(". ")
    stem = clean.split(".", 1)[0].strip().upper()
    if stem in {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}:
        clean = "_" + clean
    return clean or "scorpion_download.bin"


def _infer_ext_from_meta(url: str, headers: dict) -> str:
    ct = (headers.get("Content-Type") or headers.get("content-type") or "").split(";")[0].strip().lower()
    mime_map = (
        ("spreadsheetml", ".xlsx"),
        ("ms-excel", ".xls"),
        ("csv", ".csv"),
        ("pdf", ".pdf"),
        ("wordprocessingml", ".docx"),
        ("msword", ".doc"),
        ("presentationml", ".pptx"),
        ("audio/mpeg", ".mp3"),
        ("audio/mp4", ".m4a"),
        ("audio/ogg", ".ogg"),
        ("audio/wav", ".wav"),
        ("audio/flac", ".flac"),
        ("video/mp4", ".mp4"),
        ("video/webm", ".webm"),
        ("zip", ".zip"),
    )
    for token, ext in mime_map:
        if token in ct:
            return ext
    try:
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        qtype = " ".join(str(v).lower() for k in ("type", "format", "ext") for v in qs.get(k, []))
        for token, ext in (("xlsx", ".xlsx"), ("excel", ".xlsx"), ("xls", ".xls"), ("csv", ".csv"), ("pdf", ".pdf"), ("docx", ".docx"), ("zip", ".zip")):
            if token in qtype:
                return ext
    except Exception:
        pass
    return ""


def _sniff_file_ext(path: str) -> str:
    try:
        with open(path, "rb") as f:
            head = f.read(16)
    except Exception:
        return ""
    if not head:
        return ""
    if head.startswith(b"PK\x03\x04"):
        import zipfile
        try:
            with zipfile.ZipFile(path, "r") as zf:
                names = zf.namelist()
            if any(n.startswith("xl/") for n in names):
                return ".xlsx"
            if any(n.startswith("word/") for n in names):
                return ".docx"
            if any(n.startswith("ppt/") for n in names):
                return ".pptx"
        except Exception:
            pass
        return ".zip"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        return ".xls"
    if head.startswith(b"%PDF-"):
        return ".pdf"
    if head.startswith(b"ID3") or head[:2] in (b"\xff\xfb", b"\xff\xf3"):
        return ".mp3"
    if head.startswith(b"OggS"):
        return ".ogg"
    if head.startswith(b"fLaC"):
        return ".flac"
    return ""


def extract_filename(url: str, headers: dict) -> str:
    cd = _fix_header_mojibake(headers.get("Content-Disposition") or headers.get("content-disposition") or "")
    name = ""
    m_ext = re.search(r"filename\*\s*=\s*([^;\r\n]+)", cd, re.I)
    if m_ext:
        val = m_ext.group(1).strip().strip('"\'')
        m_rfc = re.match(r"^([A-Za-z0-9._-]+)'[^']*'(.*)$", val)
        if m_rfc:
            charset, encoded = m_rfc.group(1), m_rfc.group(2)
            try:
                decoded = urllib.parse.unquote(encoded, encoding=charset or "utf-8", errors="replace")
            except LookupError:
                decoded = urllib.parse.unquote(encoded, encoding="utf-8", errors="replace")
            if decoded:
                name = sanitize_filename(_fix_header_mojibake(decoded))
        elif val:
            if "''" in val:
                val = val.split("''", 1)[1]
            name = sanitize_filename(_fix_header_mojibake(urllib.parse.unquote(val)))
    if not name and "filename=" in cd.lower():
        m_std = re.search(r'filename\s*=\s*"([^"]+)"|filename\s*=\s*([^;\r\n]+)', cd, re.I)
        if m_std:
            part = _fix_header_mojibake((m_std.group(1) or m_std.group(2) or "").strip().strip('"\';'))
            if part:
                name = sanitize_filename(urllib.parse.unquote(part))
    if not name:
        try:
            parsed = urllib.parse.urlparse(url)
            base = os.path.basename(urllib.parse.unquote(parsed.path))
            if base and len(base) > 1 and base != "/":
                name = sanitize_filename(base)
        except Exception:
            pass
    if not name:
        return "scorpion_file.bin"
    if not os.path.splitext(name)[1]:
        inferred = _infer_ext_from_meta(url, headers)
        if inferred:
            name += inferred
    return name


# ==============================================================================
# PAINTED WIDGETS (THEME-AWARE, RTL-AWARE)
# ==============================================================================
def _mirror_if_rtl(widget: QWidget, painter: QPainter):
    if widget.layoutDirection() == Qt.LayoutDirection.RightToLeft:
        painter.translate(widget.width(), 0)
        painter.scale(-1, 1)


class RingProgress(QWidget):
    """Circular progress ring with the percentage in the middle."""

    def __init__(self, parent=None, diameter: int = 96):
        super().__init__(parent)
        self.setFixedSize(diameter, diameter)
        self.target = 0.0
        self.shown = 0.0
        self.mode = "connecting"
        self.angle = 0
        self._has_state = False

    def set_state(self, pct: float, mode: str):
        self.target = max(0.0, min(100.0, float(pct or 0)))
        if not self._has_state or mode in ("paused", "done", "error", "merging", "verifying", "saving") or self.mode != mode:
            self.shown = self.target
        self.mode = mode
        self._has_state = True
        self.update()

    def tick(self):
        self.shown += (self.target - self.shown) * 0.15
        if abs(self.target - self.shown) < 0.05:
            self.shown = self.target
        if self.mode in ("active", "connecting", "merging", "verifying", "saving"):
            self.angle = (self.angle + 6) % 360
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = pal()
        w = self.width()
        stroke = 7
        r = QRectF(stroke / 2 + 1, stroke / 2 + 1, w - stroke - 2, w - stroke - 2)

        p.setPen(QPen(QColor(c["track"]), stroke))
        p.drawEllipse(r)

        col = QColor(mode_color(self.mode))
        pen = QPen(col, stroke)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        if self.mode == "connecting" and self.shown < 0.5:
            p.drawArc(r, int((90 - self.angle) * 16), int(-80 * 16))
        else:
            if self.mode == "done":
                span = 100.0
            elif self.mode in ("merging", "verifying", "saving") and self.target >= 99.0:
                span = 100.0
            else:
                span = self.shown
            if span > 0:
                p.drawArc(r, 90 * 16, int(-span * 3.6 * 16))
            if (not prefers_reduced_motion()) and self.mode in ("active", "merging", "verifying", "saving") and (self.mode != "active" or span < 100):
                # small moving glow dot on the track to show activity
                glow = QColor(col)
                glow.setAlpha(110)
                p.setPen(QPen(glow, stroke))
                p.drawArc(r, int((90 - self.angle) * 16), int(-12 * 16))

        if self.mode == "done":
            txt, size = "✓", 26
        elif self.mode == "error":
            txt, size = "!", 26
        else:
            txt, size = f"{self.target:.0f}%", 18
        f = QFont("Segoe UI", 1, QFont.Weight.DemiBold)
        f.setPixelSize(size)
        p.setFont(f)
        p.setPen(QColor(mode_color(self.mode) if self.mode in ("done", "error") else c["text"]))
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignCenter, txt)


class SlimProgressBar(QWidget):
    """Thin bar; a soft highlight sweeps across while downloading."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(8)
        self.target = 0.0
        self.shown = 0.0
        self.mode = "connecting"
        self._has_state = False

    def set_state(self, pct: float, mode: str):
        self.target = max(0.0, min(100.0, float(pct or 0)))
        if not self._has_state or mode in ("paused", "done", "error", "merging", "verifying", "saving") or self.mode != mode:
            self.shown = self.target
        self.mode = mode
        self._has_state = True
        self.update()

    def tick(self):
        self.shown += (self.target - self.shown) * 0.15
        if abs(self.target - self.shown) < 0.05:
            self.shown = self.target
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = pal()
        w, h = self.width(), self.height()
        _mirror_if_rtl(self, p)
        track = QPainterPath()
        track.addRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        p.fillPath(track, QColor(c["track"]))
        p.setClipPath(track)
        col = QColor(mode_color(self.mode))
        if self.mode == "connecting" and self.shown < 0.5:
            if prefers_reduced_motion():
                p.fillRect(QRectF(0, 0, w * 0.25, h), col)
                return
            bw = w * 0.25
            x = -bw + (w + bw) * ((time.time() * 0.6) % 1.0)
            p.fillRect(QRectF(x, 0, bw, h), col)
            return
        fw = w * (100.0 if self.mode == "done" else self.shown) / 100.0
        if fw > 0:
            fill_rect = QRectF(0, 0, fw, h)
            if self.mode in ("active", "merging", "verifying", "saving", "done", "connecting"):
                g_fill = QLinearGradient(0, 0, fw, 0)
                g_fill.setColorAt(0.0, QColor(c["accent"]))
                g_fill.setColorAt(1.0, QColor(c["accent_intense"]))
                p.fillRect(fill_rect, g_fill)
            else:
                p.fillRect(fill_rect, col)
        if (not prefers_reduced_motion()) and self.mode in ("active", "merging", "verifying", "saving") and fw > 20:
            sw = 80
            x = -sw + (fw + sw) * ((time.time() * 0.5) % 1.0)
            g = QLinearGradient(x, 0, x + sw, 0)
            g.setColorAt(0.0, QColor(255, 255, 255, 0))
            g.setColorAt(0.5, QColor(255, 255, 255, 110))
            g.setColorAt(1.0, QColor(255, 255, 255, 0))
            p.fillRect(QRectF(max(0.0, x), 0, min(sw, fw - max(0.0, x)), h), g)


class SegmentMapWidget(QWidget):
    """
    File map: everything is drawn as downloaded, then each segment's remaining
    range [currentByte..endByte] is cleared - stays correct after work-stealing splits.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.segments = []
        self.total = 0
        self.progress = 0.0
        self.done = False
        self.mode = "active"

    def set_data(self, segments, total: int, progress: float, done: bool, mode: str = "active"):
        self.segments = segments or []
        self.total = int(total or 0)
        self.progress = float(progress or 0)
        self.done = done
        self.mode = mode
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = pal()
        w, h = self.width(), self.height()
        _mirror_if_rtl(self, p)
        path = QPainterPath()
        path.addRoundedRect(QRectF(0, 0, w, h), 4, 4)
        empty = QColor(c["track"])
        p.fillPath(path, empty)
        p.setClipPath(path)
        got = QColor(mode_color("done" if self.done else self.mode))
        known = self.total > 0 and all(s.get("endByte", -1) >= s.get("startByte", 0) for s in self.segments)
        if not known:
            p.fillRect(QRectF(0, 0, w * min(100.0, self.progress) / 100.0, h), got)
            return
        p.fillRect(QRectF(0, 0, w, h), got)
        scale = w / float(self.total)
        for s in self.segments:
            cur, end = s.get("currentByte", 0), s.get("endByte", -1)
            if s.get("status") != "completed" and end >= cur:
                x0, x1 = cur * scale, (end + 1) * scale
                p.fillRect(QRectF(x0, 0, max(0.0, x1 - x0), h), empty)
                if s.get("status") == "downloading":
                    p.fillRect(QRectF(min(max(0.0, w - 2.0), max(0.0, x0)), 0, 2, h), QColor(c["warn"]))
        sep = QColor(c["surface"])
        p.setPen(QPen(sep, 1))
        for s in self.segments:
            x = s.get("startByte", 0) * scale
            if x > 1:
                p.drawLine(QPointF(x, 0), QPointF(x, h))


class SpeedGraphWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(64)
        self.history = []

    def set_history(self, history):
        self.history = list(history or [])
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        c = pal()
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(c["surface2"]), 1))
        for i in range(1, 4):
            y = h * i / 4.0
            p.drawLine(QPointF(0, y), QPointF(w, y))
        if len(self.history) < 2:
            return
        max_spd = max(max(self.history), 102400)
        pts = []
        for i, val in enumerate(self.history):
            x = (i / (len(self.history) - 1)) * w
            y = h - 3 - min(h - 8, (val / max_spd) * (h - 8))
            pts.append(QPointF(x, y))
        area = QPainterPath()
        area.moveTo(pts[0].x(), h)
        for pt in pts:
            area.lineTo(pt)
        area.lineTo(pts[-1].x(), h)
        area.closeSubpath()
        acc = QColor(c["accent"])
        g = QLinearGradient(0, 0, 0, h)
        top = QColor(acc)
        top.setAlpha(70)
        bot = QColor(acc)
        bot.setAlpha(0)
        g.setColorAt(0.0, top)
        g.setColorAt(1.0, bot)
        p.fillPath(area, g)
        p.setPen(QPen(acc, 2))
        p.drawPolyline(QPolygonF(pts))


def _make_tile(caption: str):
    box = QWidget()
    lay = QVBoxLayout(box)
    lay.setContentsMargins(6, 4, 6, 4)
    lay.setSpacing(2)
    val = QLabel("—")
    val.setObjectName("Value")
    val.setAlignment(Qt.AlignmentFlag.AlignCenter)
    cap = QLabel(caption)
    cap.setObjectName("Caption")
    cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
    lay.addWidget(val)
    lay.addWidget(cap)
    return box, val


def _vsep():
    s = QFrame()
    s.setObjectName("VSep")
    s.setFrameShape(QFrame.Shape.VLine)
    return s


def _set_elided(label: QLabel, text: str, mode=Qt.TextElideMode.ElideMiddle):
    label.setToolTip(text)
    fm = label.fontMetrics()
    width = max(80, label.width() - 4)
    label.setText(fm.elidedText(text, mode, width))


def _elide_filename(label: QLabel, raw_name: str):
    """Elide raw filename cleanly before inserting BiDi isolation marks."""
    raw = str(raw_name or "")
    label.setToolTip(bidi_filename(raw))
    fm = label.fontMetrics()
    width = max(80, label.width() - 4)
    elided = fm.elidedText(raw, Qt.TextElideMode.ElideMiddle, width)
    label.setText(bidi_filename(elided))


class FluentComboBox(QComboBox):
    """QComboBox whose display text obeys RTL/LTR leading alignment even under QSS."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(34)

    def showPopup(self):
        view = self.view()
        if view is not None:
            view.setLayoutDirection(self.layoutDirection())
        super().showPopup()

    def paintEvent(self, event):
        c = pal()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(c["accent"] if self.hasFocus() else c["border"]), 1.0))
        p.setBrush(QColor(c["surface"]))
        p.drawRoundedRect(r, 7, 7)

        rtl = self.layoutDirection() == Qt.LayoutDirection.RightToLeft
        pad_side = 10
        arrow_w = 24
        if rtl:
            arrow_r = QRectF(pad_side - 2, 0, arrow_w, self.height())
            text_r = QRectF(pad_side + arrow_w, 0, max(10.0, self.width() - (2 * pad_side + arrow_w)), self.height())
            align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
        else:
            arrow_r = QRectF(self.width() - pad_side - arrow_w + 2, 0, arrow_w, self.height())
            text_r = QRectF(pad_side, 0, max(10.0, self.width() - (2 * pad_side + arrow_w)), self.height())
            align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter

        p.setFont(self.font())
        p.setPen(QColor(c["text"] if self.isEnabled() else c["muted"]))
        txt = self.fontMetrics().elidedText(self.currentText(), Qt.TextElideMode.ElideRight, int(text_r.width()))
        p.drawText(text_r, align, txt)

        pm = outline_pixmap("chevron_down", c["muted"], 12, 1.9)
        p.drawPixmap(int(arrow_r.center().x() - 6), int(arrow_r.center().y() - 6), pm)


def confirm_action_dialog(title: str, text: str, is_ar: bool, yes_label: str = "", no_label: str = "") -> bool:
    """Modal confirmation guaranteed to appear centered and above always-on-top cards."""
    box = QMessageBox(QMessageBox.Icon.Question, title, text, QMessageBox.StandardButton.NoButton, None)
    box.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowStaysOnTopHint)
    box.setWindowIcon(scorpion_emblem_icon())
    box.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight)
    yes_btn = box.addButton(
        yes_label or ("نعم، إلغاء وحذف" if is_ar else "Yes, cancel & delete"),
        QMessageBox.ButtonRole.YesRole,
    )
    yes_btn.setObjectName("DangerBtn")
    no_btn = box.addButton(
        no_label or ("تراجع" if is_ar else "Keep download"),
        QMessageBox.ButtonRole.NoRole,
    )
    box.setDefaultButton(no_btn)
    box.adjustSize()
    scr = QApplication.primaryScreen()
    if scr is not None:
        avail = scr.availableGeometry()
        box.move(
            avail.center().x() - box.width() // 2,
            avail.center().y() - box.height() // 2,
        )
    raise_timer = QTimer(box)
    raise_timer.setSingleShot(True)
    raise_timer.timeout.connect(lambda: (box.raise_(), box.activateWindow()))
    raise_timer.start(0)
    box.exec()
    return box.clickedButton() is yes_btn


# ==============================================================================
# IDM-STYLE PROGRESS WINDOW (INDEPENDENT TOP-LEVEL WINDOW PER DOWNLOAD)
# ==============================================================================
class IDMProgressDialog(QDialog):
    def __init__(self, engine, dl_id: str, lang: str = "ar", parent=None):
        # No Qt parent: must appear on its own even if the main window is hidden/minimized
        super().__init__(None)
        self.engine = engine
        self.dl_id = dl_id
        self.main_window = parent
        self.is_ar = lang == "ar"
        self._was_completed = False
        self._last_mode = None
        T = (lambda ar, en: ar) if self.is_ar else (lambda ar, en: en)
        self.T = T

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowMinimizeButtonHint
            | Qt.WindowType.WindowCloseButtonHint
        )
        if parent is not None and not parent.windowIcon().isNull():
            self.setWindowIcon(parent.windowIcon())
        else:
            self.setWindowIcon(scorpion_emblem_icon())
        self.setWindowTitle("Scorpion")
        self.resize(640, 440)
        self.setMinimumWidth(560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 18, 18, 16)
        root.setSpacing(12)

        # ---- Hero card: ring + name + status + slim bar ----
        hero = QFrame()
        hero.setObjectName("CardFrame")
        hv = QVBoxLayout(hero)
        hv.setContentsMargins(18, 16, 18, 16)
        hv.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(16)
        self.ring = RingProgress()
        top.addWidget(self.ring)
        info = QVBoxLayout()
        info.setSpacing(4)
        self.lbl_filename = QLabel("")
        self.lbl_filename.setObjectName("Title")
        self.lbl_filename.setMinimumWidth(1)
        self.lbl_url = QLabel("")
        self.lbl_url.setObjectName("Url")
        self.lbl_url.setMinimumWidth(1)
        # Latin-only text (file names, hosts) would otherwise hug the left edge in Arabic mode
        lead = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute) if self.is_ar else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        self.lbl_filename.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_url.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
        pill_row = QHBoxLayout()
        self.lbl_status = QLabel("")
        pill_row.addWidget(self.lbl_status)
        pill_row.addStretch()
        info.addStretch()
        info.addWidget(self.lbl_filename)
        info.addWidget(self.lbl_url)
        info.addSpacing(4)
        info.addLayout(pill_row)
        info.addStretch()
        top.addLayout(info, 1)
        hv.addLayout(top)
        self.bar = SlimProgressBar()
        hv.addWidget(self.bar)
        self.lbl_amount = QLabel("")
        self.lbl_amount.setObjectName("Muted")
        self.lbl_amount.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hv.addWidget(self.lbl_amount)
        root.addWidget(hero)

        # ---- 4 centered tiles ----
        tiles = QFrame()
        tiles.setObjectName("CardFrame")
        tl = QHBoxLayout(tiles)
        tl.setContentsMargins(8, 12, 8, 12)
        tl.setSpacing(0)
        self.tile = {}
        for i, (key, cap) in enumerate([
            ("speed", T("السرعة", "Speed")),
            ("eta", T("الوقت المتبقي", "Time left")),
            ("left", T("المتبقي", "Remaining")),
            ("size", T("حجم الملف", "File size")),
        ]):
            if i:
                tl.addWidget(_vsep())
            box, val = _make_tile(cap)
            tl.addWidget(box, 1)
            self.tile[key] = val
        root.addWidget(tiles)

        self.lbl_meta = QLabel("")
        self.lbl_meta.setObjectName("Caption")
        self.lbl_meta.setAlignment(Qt.AlignmentFlag.AlignCenter)
        root.addWidget(self.lbl_meta)

        # ---- Tabs ----
        self.tabs = QTabWidget()
        seg_tab = QWidget()
        sl = QVBoxLayout(seg_tab)
        sl.setContentsMargins(14, 14, 14, 14)
        sl.setSpacing(8)
        cap1 = QLabel(T("خريطة الملف", "File map"))
        cap1.setObjectName("Caption")
        sl.addWidget(cap1)
        self.seg_map = SegmentMapWidget()
        sl.addWidget(self.seg_map)
        sl.addSpacing(4)
        self.lbl_graph = QLabel(T("السرعة اللحظية", "Live speed"))
        self.lbl_graph.setObjectName("Caption")
        sl.addWidget(self.lbl_graph)
        self.speed_graph = SpeedGraphWidget()
        sl.addWidget(self.speed_graph)
        self.seg_table = QTableWidget(0, 5)
        self.seg_table.setHorizontalHeaderLabels(
            [T("الجزء", "Part"), T("تم تحميل", "Downloaded"), T("الحجم", "Size"), T("النسبة", "Progress"), T("الحالة", "Status")]
        )
        hh = self.seg_table.horizontalHeader()
        for col in range(5):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        self.seg_table.verticalHeader().setVisible(False)
        self.seg_table.verticalHeader().setDefaultSectionSize(32)
        self.seg_table.setShowGrid(False)
        self.seg_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.seg_table.setSelectionMode(QTableWidget.SelectionMode.NoSelection)
        self.seg_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.seg_table.setMinimumHeight(155)
        sl.addWidget(self.seg_table, 1)
        self.tabs.addTab(seg_tab, T("الأجزاء", "Segments"))

        lim_tab = QWidget()
        ll = QVBoxLayout(lim_tab)
        ll.setContentsMargins(16, 16, 16, 16)
        lim_row = QHBoxLayout()
        lim_row.addWidget(QLabel(T("أقصى سرعة (كيلوبايت/ث) — 0 بدون حد", "Max speed (KB/s) — 0 = unlimited")))
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(0, 1000000)
        self.spin_limit.setMinimumWidth(120)
        lim_row.addWidget(self.spin_limit)
        b = QPushButton(T("تطبيق", "Apply"))
        b.setObjectName("PrimaryBtn")
        b.clicked.connect(self.apply_speed_limit)
        lim_row.addWidget(b)
        lim_row.addStretch()
        ll.addLayout(lim_row)
        ll.addStretch()
        self.tabs.addTab(lim_tab, T("حد السرعة", "Speed limit"))

        chk_tab = QWidget()
        cl = QVBoxLayout(chk_tab)
        cl.setContentsMargins(16, 16, 16, 16)
        self.lbl_hash = QLabel("SHA-256: —")
        self.lbl_hash.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.lbl_hash.setWordWrap(True)
        self.lbl_hash.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        cl.addWidget(self.lbl_hash)
        bh = QPushButton(T("حساب SHA-256 و MD5", "Compute SHA-256 & MD5"))
        bh.clicked.connect(self.compute_hash)
        hb = QHBoxLayout()
        hb.addWidget(bh)
        hb.addStretch()
        cl.addLayout(hb)
        cl.addStretch()
        self.tabs.addTab(chk_tab, T("التحقق من الملف", "Checksum"))
        root.addWidget(self.tabs, 1)
        # Compact by default (the tabs are for the curious); the choice is remembered
        self.tabs.setVisible(bool(self.engine.settings.get("progressDetailsOpen", False)))

        # ---- Buttons ----
        btns = QHBoxLayout()
        btns.setSpacing(8)
        self.btn_toggle = QPushButton()
        self.btn_toggle.setObjectName("PrimaryBtn")
        self.btn_toggle.setMinimumWidth(130)
        self.btn_toggle.clicked.connect(self.toggle_pause)
        btns.addWidget(self.btn_toggle)
        self.btn_open_file = QPushButton(T("تشغيل الملف", "Open file"))
        self.btn_open_file.setObjectName("PrimaryBtn")
        self.btn_open_file.setMinimumWidth(130)
        self.btn_open_file.clicked.connect(self.open_file)
        btns.addWidget(self.btn_open_file)
        self.btn_cancel = QPushButton(T("إلغاء التحميل", "Cancel"))
        self.btn_cancel.setObjectName("DangerBtn")
        self.btn_cancel.clicked.connect(self.cancel_download)
        btns.addWidget(self.btn_cancel)
        btns.addStretch()
        self.btn_open_folder = QPushButton(T("فتح المجلد", "Open folder"))
        self.btn_open_folder.clicked.connect(self.open_folder)
        btns.addWidget(self.btn_open_folder)
        self.btn_details = QPushButton()
        self.btn_details.clicked.connect(self.toggle_details)
        btns.addWidget(self.btn_details)
        self.btn_hide = QPushButton(T("إخفاء", "Hide"))
        self.btn_hide.clicked.connect(self.close)
        btns.addWidget(self.btn_hide)
        root.addLayout(btns)
        self._update_details_button()

        self._apply_icons()
        self.anim_timer = QTimer(self)
        self.anim_timer.timeout.connect(self._animate)
        self.data_timer = QTimer(self)
        self.data_timer.timeout.connect(self.refresh_ui)
        self.refresh_ui()
        avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        if self.tabs.isHidden():
            self.adjustSize()
            self.resize(max(640, self.width()), self.minimumSizeHint().height())
        else:
            self.resize(max(700, self.width()), min(780, avail.height() - 30))

    def apply_theme(self):
        self._apply_icons()
        self.refresh_ui()

    def _update_details_button(self):
        opened = not self.tabs.isHidden()
        self.btn_details.setText(self.T("▴ إخفاء التفاصيل", "▴ Less") if opened else self.T("▾ التفاصيل", "▾ Details"))

    def toggle_details(self):
        opened = self.tabs.isHidden()
        self.tabs.setVisible(opened)
        self.engine.settings["progressDetailsOpen"] = opened
        self.engine.save_state()
        self._update_details_button()
        avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        if opened:
            self.resize(max(self.width(), 700), min(780, avail.height() - 30))
        else:
            width = max(640, self.width())
            self.adjustSize()
            self.resize(width, self.minimumSizeHint().height())

    def _apply_icons(self):
        c = pal()
        self.btn_open_file.setIcon(glyph_icon(ICONS["open"], c["primary_text"]))
        self.btn_cancel.setIcon(glyph_icon(ICONS["close"], c["danger"]))
        self.btn_open_folder.setIcon(glyph_icon(ICONS["folder"], c["text"]))
        self.btn_hide.setIcon(glyph_icon(ICONS["hide"], c["text"]))

    # ----- timers only run while the window is visible -----
    def showEvent(self, event):
        super().showEvent(event)
        self.anim_timer.start(33)
        self.data_timer.start(250)

    def hideEvent(self, event):
        super().hideEvent(event)
        self.anim_timer.stop()
        self.data_timer.stop()

    def _animate(self):
        self.ring.tick()
        self.bar.tick()

    def bring_to_front(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()

    def refresh_ui(self):
        T = self.T
        item = self.engine.downloads.get(self.dl_id)
        if not item:
            self.close()
            return

        status = item.get("status", "")
        phase = item.get("phase", "")
        total = int(item.get("totalSize") or 0)
        done = int(item.get("downloadedBytes") or 0)
        pct = float(item.get("progress") or 0.0)
        is_video = bool(item.get("isVideo"))

        if status == "completed":
            mode, st = "done", T("اكتمل التحميل", "Completed")
            pct = 100.0
        elif status == "error":
            mode, st = "error", T("فشل التحميل", "Failed")
        elif status == "paused":
            mode, st = "paused", T("متوقف مؤقتاً", "Paused")
        elif status == "queued":
            mode, st = "paused", T("في قائمة الانتظار", "Queued")
        elif status == "scheduled":
            mode, st = "paused", T("مجدول للتحميل لاحقاً", "Scheduled")
        elif phase == "selecting":
            mode, st = "connecting", T("في انتظار اختيار ملفات التورنت", "Waiting for file selection")
        elif phase == "merging":
            mode, st = "merging", T("جاري دمج الصوت والصورة", "Merging audio & video")
        elif phase == "verifying":
            mode, st = "verifying", T("جاري التحقق من سلامة الملف", "Verifying file integrity")
        elif phase == "saving":
            mode, st = "saving", T("جاري حفظ الملف النهائي", "Saving final file")
        elif phase == "connecting" or done == 0:
            mode = "connecting"
            if item.get("isTorrent"):
                st = T("جاري البحث عن Peers", "Finding peers")
            elif item.get("category") == "Music" or item.get("videoQuality") == "audio":
                st = T("جاري تجهيز المقطع الصوتي", "Preparing audio")
            else:
                st = T("جاري تجهيز الفيديو", "Preparing video") if is_video else T("جاري الاتصال", "Connecting")
        else:
            mode, st = "active", T("جاري التحميل", "Downloading")

        self.ring.set_state(pct, mode)
        self.bar.set_state(pct, mode)

        # status pill
        col = QColor(mode_color(mode))
        self.lbl_status.setText(st)
        self.lbl_status.setStyleSheet(
            f"background: rgba({col.red()},{col.green()},{col.blue()},38); color: {col.name()};"
            "border-radius: 10px; padding: 3px 12px; font-size: 12px; font-weight: 600;"
        )

        self.setWindowTitle(f"{pct:.0f}% — {bidi_filename(item.get('filename', ''))}")
        _elide_filename(self.lbl_filename, item.get("filename", ""))
        if status == "error" and item.get("errorMsg"):
            err_msg = localize_error_msg(item.get("errorMsg"), self.is_ar)
            self.lbl_url.setWordWrap(True)
            self.lbl_url.setText(err_msg)
            self.lbl_url.setToolTip(err_msg)
            self.lbl_url.setStyleSheet(f"color: {pal()['danger']}; font-size: 12px;")
            if self.tabs.isHidden():
                hint_h = self.minimumSizeHint().height()
                if self.height() < hint_h:
                    self.resize(self.width(), hint_h)
        else:
            self.lbl_url.setWordWrap(False)
            host = urllib.parse.urlparse(item.get("url", "")).netloc or item.get("url", "")
            _set_elided(self.lbl_url, host)
            self.lbl_url.setStyleSheet("")

        if total > 0:
            amount = T(f"تم تحميل {L(format_bytes(done))} من {L(format_bytes(total))}",
                       f"{format_bytes(done)} of {format_bytes(total)}")
        else:
            amount = T(f"تم تحميل {L(format_bytes(done))}", f"{format_bytes(done)} downloaded")
        self.lbl_amount.setText(amount)

        unknown = "—"
        downloading = status == "downloading" and mode == "active"
        self.tile["speed"].setText(L(format_speed(item.get("speed", 0))) if downloading else unknown)
        self.tile["eta"].setText(L(format_eta(item.get("timeLeft"))) if downloading else ("0s" if mode == "done" else unknown))
        self.tile["left"].setText(L(format_bytes(max(0, total - done))) if total > 0 else unknown)
        self.tile["size"].setText(L(format_bytes(total)) if total > 0 else unknown)
        self.tile["speed"].setStyleSheet(f"color: {pal()['accent']};" if downloading else "")

        segs = item.get("segments", [])
        active = sum(1 for s in segs if s.get("status") == "downloading")
        started = item.get("startedAt") or (item.get("createdAt", 0) / 1000.0)
        ended = item.get("finishedAt") or time.time()
        elapsed = format_eta(max(0, int(ended - started))) if started else "—"
        resume = (T("الاستكمال مدعوم", "Resumable") if (item.get("supportsRange") or is_video)
                  else T("الاستكمال غير مدعوم", "Not resumable"))
        sep = "     •     "
        meta_parts = [T(f"الوقت المنقضي {L(elapsed)}", f"Elapsed {elapsed}")]
        if status == "downloading" and segs:
            meta_parts.append(T(f"الاتصالات {L(f'{active}/{len(segs)}')}", f"Connections {active}/{len(segs)}"))
        elif segs and (status != "error" or len(segs) > 1 or done > 0):
            meta_parts.append(T(f"البورتات {L(len(segs))}", f"Ports {len(segs)}"))
        if status != "error":
            meta_parts.append(resume)
        self.lbl_meta.setText(sep.join(meta_parts))

        self.seg_map.set_data(segs, total, pct, status == "completed", mode)
        hist = item.get("speedHistory", [])
        self.speed_graph.set_history(hist)
        peak = max(hist) if hist else 0
        self.lbl_graph.setText(T(f"السرعة اللحظية  —  الذروة {L(format_speed(peak))}", f"Live speed  —  peak {format_speed(peak)}"))
        self._fill_segment_table(segs)

        finished = status == "completed"
        browser_owned = bool(item.get("browserTransfer"))
        is_drm_err = status == "error" and (
            is_drm_video_url(item.get("url", "")) or "drm" in str(item.get("errorMsg", "")).lower()
        )
        self.btn_open_file.setVisible(finished)
        self.btn_toggle.setVisible(
            (not finished)
            and (not is_drm_err)
            and (not browser_owned or status not in ("downloading", "error"))
        )
        self.btn_toggle.setEnabled(phase not in ("merging", "verifying", "saving"))
        self.btn_cancel.setVisible(not finished)
        self.btn_open_folder.setEnabled(
            any(os.path.exists(pth) for pth in (item.get("filePath") or "", item.get("tempFilePath") or "", item.get("saveDir") or "") if pth)
        )
        want_obj = "" if status == "downloading" else "PrimaryBtn"
        if self.btn_toggle.objectName() != want_obj:
            self.btn_toggle.setObjectName(want_obj)
            self.btn_toggle.style().unpolish(self.btn_toggle)
            self.btn_toggle.style().polish(self.btn_toggle)
        if status == "downloading":
            self.btn_toggle.setText(T("إيقاف مؤقت", "Pause"))
            self.btn_toggle.setIcon(glyph_icon(ICONS["pause"], pal()["muted"] if phase in ("merging", "verifying", "saving") else pal()["text"]))
        else:
            if status in ("queued", "scheduled"):
                self.btn_toggle.setText(T("تشغيل الآن", "Start now"))
            elif status == "error":
                self.btn_toggle.setText(T("إعادة المحاولة", "Retry"))
            else:
                self.btn_toggle.setText(T("استئناف", "Resume"))
            self.btn_toggle.setIcon(glyph_icon(ICONS["play"], pal()["primary_text"]))

        if item.get("checksumSha256"):
            self.lbl_hash.setText(f"SHA-256: {item['checksumSha256']}\nMD5: {item.get('checksumMd5', '')}")

        if finished and not self._was_completed:
            self._was_completed = True
            self.bring_to_front()

    def _fill_segment_table(self, segs):
        T = self.T
        c = pal()
        if self.seg_table.rowCount() != len(segs):
            self.seg_table.setRowCount(len(segs))
        status_map = {
            "completed": (T("مكتمل", "Complete"), c["success"]),
            "downloading": (T("يحمّل", "Receiving"), c["accent"]),
            "error": (T("خطأ", "Error"), c["danger"]),
            "idle": (T("في الانتظار", "Waiting"), c["muted"]),
        }
        for r, s in enumerate(segs):
            dl = int(s.get("downloaded") or 0)
            if s.get("size"):
                size = int(s["size"])
            elif s.get("endByte", -1) >= s.get("currentByte", 0):
                size = dl + (s["endByte"] - s["currentByte"] + 1)
            else:
                size = dl
            part_pct = 100.0 if s.get("status") == "completed" else ((dl / size * 100.0) if size > 0 else 0.0)
            label = re.sub(r"#(\d+)", lambda m: L("#" + m.group(1)), str(s.get("label") or f"#{s.get('id')}"))
            st_txt, st_col = status_map.get(s.get("status"), (s.get("status", ""), c["muted"]))
            values = [
                (label, None),
                (L(format_bytes(dl)), None),
                (L(format_bytes(size)) if size else "—", None),
                (L(f"{min(100.0, part_pct):.1f}%"), None),
                (st_txt, st_col),
            ]
            for col_i, (v, fg) in enumerate(values):
                cell = self.seg_table.item(r, col_i)
                if cell is None:
                    cell = QTableWidgetItem()
                    cell.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    self.seg_table.setItem(r, col_i, cell)
                if cell.text() != v:
                    cell.setText(v)
                if fg:
                    cell.setForeground(QColor(fg))
            tip = s.get("info") or ""
            if tip and s.get("status") == "error":
                self.seg_table.item(r, 4).setToolTip(localize_error_msg(tip, self.is_ar))

    def toggle_pause(self):
        item = self.engine.downloads.get(self.dl_id)
        if not item:
            return
        if item["status"] == "downloading":
            self.engine.pause_download(self.dl_id)
        else:
            if item["status"] == "error":
                item["status"] = "paused"
            self.engine.start_download(self.dl_id)
        self.refresh_ui()

    def cancel_download(self):
        if confirm_action_dialog(
            self.T("إلغاء التحميل", "Cancel download"),
            self.T("هل تريد إلغاء هذا التحميل وحذفه من القائمة؟", "Cancel this download and remove it?"),
            self.is_ar,
        ):
            self.engine.delete_download(self.dl_id)
            if self.main_window is not None:
                self.main_window.open_progress_dialogs.pop(self.dl_id, None)
                self.main_window.cards.remove(self.dl_id)
                self.main_window.refresh_all()
            self.close()

    def apply_speed_limit(self):
        item = self.engine.downloads.get(self.dl_id)
        if item:
            item["speedLimitKbps"] = self.spin_limit.value()

    def compute_hash(self):
        res = self.engine.compute_checksum(self.dl_id)
        if res:
            self.lbl_hash.setText(f"SHA-256: {res['sha256']}\nMD5: {res['md5']}")

    def open_folder(self):
        item = self.engine.downloads.get(self.dl_id)
        if not item:
            return
        target = item["filePath"] if os.path.exists(item["filePath"]) else item["tempFilePath"]
        if os.path.exists(target):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
        elif os.path.exists(item["saveDir"]):
            os.startfile(item["saveDir"])

    def open_file(self):
        item = self.engine.downloads.get(self.dl_id)
        if item and os.path.exists(item["filePath"]):
            os.startfile(item["filePath"])

# ==============================================================================
# NATIVE ADD NEW DOWNLOAD DIALOG (IDM FILE INFO POPUP)
# ==============================================================================
class AddDownloadDialog(QDialog):
    qualities_ready = pyqtSignal(str, dict)
    probe_ready = pyqtSignal(str, dict)

    def __init__(self, engine, initial_url: str = "", is_video: bool = False, lang: str = "ar", parent=None, is_torrent: bool = False):
        super().__init__(parent)
        self.engine = engine
        self.is_video = is_video
        self.is_torrent = is_torrent
        self.is_ar = lang == "ar"
        self.result_opts = None
        c = pal()

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        if is_torrent:
            title_ar = "تحميل تورنت أو رابط Magnet — Scorpion Download Manager"
            title_en = "Add Torrent / Magnet Link — Scorpion Download Manager"
        elif is_video:
            title_ar = "سحب فيديو ذكي (32 بورت) — Scorpion Download Manager"
            title_en = "Smart Video Grabber (32 Ports) — Scorpion Download Manager"
        else:
            title_ar = "إضافة رابط تحميل جديد (32 بورت) — Scorpion Download Manager"
            title_en = "Add New Download (32 Ports) — Scorpion Download Manager"
        self.setWindowTitle(title_ar if self.is_ar else title_en)
        self.resize(660, 420)
        self.setMinimumWidth(560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 16)
        layout.setSpacing(12)

        # Card 1: Source URL + Probe + Torrent File Picker
        src_card = QFrame()
        src_card.setObjectName("CardFrame")
        sv = QVBoxLayout(src_card)
        sv.setContentsMargins(16, 14, 16, 14)
        sv.setSpacing(8)
        hdr_lbl = QLabel(
            "رابط التحميل، أو رابط ماجنت، أو مسار ملف تورنت:"
            if self.is_ar
            else "Download URL, Magnet URI, or .torrent File Path:"
        )
        hdr_lbl.setStyleSheet("font-weight: 700;")
        sv.addWidget(hdr_lbl)

        url_row = QHBoxLayout()
        url_row.setSpacing(8)
        self.txt_url = QLineEdit(initial_url)
        self.txt_url.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.txt_url.setPlaceholderText("https://...  |  magnet:?xt=urn:btih:...  |  C:\\...\\file.torrent")
        self.txt_url.textChanged.connect(self._on_url_text_changed)
        url_row.addWidget(self.txt_url, 1)

        btn_torrent_file = QPushButton("ملف تورنت" if self.is_ar else ".torrent")
        btn_torrent_file.setIcon(glyph_icon(ICONS["torrent"], c["text"]))
        btn_torrent_file.clicked.connect(self.browse_torrent_file)
        url_row.addWidget(btn_torrent_file)

        self.btn_probe = QPushButton("فحص الرابط" if self.is_ar else "Probe")
        self.btn_probe.setIcon(glyph_icon(ICONS["probe"], c["text"]))
        self.btn_probe.clicked.connect(self.probe_now)
        url_row.addWidget(self.btn_probe)
        sv.addLayout(url_row)

        self.lbl_probe_info = QLabel("")
        self.lbl_probe_info.setWordWrap(True)
        self.lbl_probe_info.setStyleSheet(f"color: {c['muted']}; font-size: 12px; font-weight: 600;")
        sv.addWidget(self.lbl_probe_info)
        layout.addWidget(src_card)

        # Card 2: File Name, Category, Save Folder, Quality / Connections
        det_card = QFrame()
        det_card.setObjectName("CardFrame")
        dv = QVBoxLayout(det_card)
        dv.setContentsMargins(16, 14, 16, 14)
        form_grid = QGridLayout()
        form_grid.setHorizontalSpacing(10)
        form_grid.setVerticalSpacing(10)

        form_grid.addWidget(QLabel("اسم الملف:" if self.is_ar else "File Name:"), 0, 0)
        self.txt_filename = QLineEdit()
        form_grid.addWidget(self.txt_filename, 0, 1)

        form_grid.addWidget(QLabel("التصنيف:" if self.is_ar else "Category:"), 0, 2)
        self.cmb_cat = FluentComboBox()
        for key, ar_lbl, en_lbl in (
            ("Programs", "برامج", "Programs"),
            ("Compressed", "ملفات مضغوطة", "Compressed"),
            ("Video", "فيديو", "Video"),
            ("Music", "صوتيات", "Music"),
            ("Documents", "مستندات", "Documents"),
            ("General", "عام", "General"),
        ):
            self.cmb_cat.addItem(ar_lbl if self.is_ar else en_lbl, key)
        if is_video or is_torrent:
            self._set_category("Video")
        else:
            self._set_category("General")
        self.cmb_cat.currentIndexChanged.connect(self._on_category_changed)
        form_grid.addWidget(self.cmb_cat, 0, 3)

        form_grid.addWidget(QLabel("مجلد الحفظ:" if self.is_ar else "Save Folder:"), 1, 0)
        self._custom_save_dir = False
        self._probed_info = None
        self.txt_savedir = QLineEdit(self.engine.settings["downloadsRoot"])
        self.txt_savedir.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.txt_savedir.setCursorPosition(0)
        self.txt_savedir.textEdited.connect(lambda _t: setattr(self, "_custom_save_dir", True))
        form_grid.addWidget(self.txt_savedir, 1, 1, 1, 2)
        btn_browse = QPushButton("تصفح" if self.is_ar else "Browse")
        btn_browse.setIcon(glyph_icon(ICONS["folder"], c["text"]))
        btn_browse.clicked.connect(self.browse_dir)
        form_grid.addWidget(btn_browse, 1, 3)

        self.probe_ready.connect(self._on_probe_ready)
        if is_video:
            form_grid.addWidget(QLabel("جودة الفيديو:" if self.is_ar else "Video Quality:"), 2, 0)
            self.cmb_quality = FluentComboBox()
            self.qualities_ready.connect(self._on_qualities_ready)
            self._fill_qualities([])
            form_grid.addWidget(self.cmb_quality, 2, 1, 1, 3)
        else:
            form_grid.addWidget(QLabel("عدد البورتات:" if self.is_ar else "Parallel Ports:"), 2, 0)
            self.cmb_conn = FluentComboBox()
            self.cmb_conn.addItems(["1", "4", "8", "16", "32", "64"])
            self.cmb_conn.setCurrentText("32")
            form_grid.addWidget(self.cmb_conn, 2, 1)

        form_grid.setColumnStretch(1, 2)
        dv.addLayout(form_grid)
        layout.addWidget(det_card)
        layout.addStretch()

        # Action Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_start = QPushButton("بدء التحميل الآن" if self.is_ar else "Start Download Now")
        btn_start.setObjectName("PrimaryBtn")
        btn_start.setIcon(glyph_icon(ICONS["download"], c["primary_text"]))
        btn_start.setMinimumWidth(160)
        btn_start.clicked.connect(lambda: self.accept_download(True))
        btn_row.addWidget(btn_start)

        btn_later = QPushButton("التحميل لاحقاً" if self.is_ar else "Download Later")
        btn_later.setIcon(glyph_icon(ICONS["clock"], c["text"]))
        btn_later.clicked.connect(lambda: self.accept_download(False))
        btn_row.addWidget(btn_later)
        btn_row.addStretch()

        btn_cancel = QPushButton("إلغاء" if self.is_ar else "Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        if initial_url:
            QTimer.singleShot(150, self.probe_now)
        elif is_torrent:
            QTimer.singleShot(150, self.browse_torrent_file)

    def _set_category(self, key: str):
        idx = self.cmb_cat.findData(key)
        if idx >= 0:
            self.cmb_cat.setCurrentIndex(idx)

    def _on_category_changed(self):
        cat = self.cmb_cat.currentData() or "General"
        dl_root = os.path.normpath(self.engine.settings.get("downloadsRoot") or "")
        cur_dir = os.path.normpath(self.txt_savedir.text().strip() or dl_root)
        if not self._custom_save_dir and dl_root and (cur_dir == dl_root or os.path.dirname(cur_dir) == dl_root):
            self.txt_savedir.setText(os.path.join(dl_root, cat))
            self.txt_savedir.setCursorPosition(0)

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Save Folder", self.txt_savedir.text())
        if d:
            self._custom_save_dir = True
            self.txt_savedir.setText(os.path.normpath(d))
            self.txt_savedir.setCursorPosition(0)

    def browse_torrent_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "اختر ملف تورنت (.torrent)" if self.is_ar else "Select .torrent File",
            os.path.expanduser("~/Downloads"),
            "Torrent Files (*.torrent);;All Files (*)",
        )
        if path and os.path.isfile(path):
            self.is_torrent = True
            self.txt_url.setText(path)
            base_name = os.path.splitext(os.path.basename(path))[0]
            self.txt_filename.setText(base_name)
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['success']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText(
                f"✅ ملف تورنت جاهز للتحميل بأقصى سرعة (DHT + Trackers + {L('32 Ports')}): {bidi_filename(base_name)}"
                if self.is_ar
                else f"✅ Torrent file ready for full-speed download (DHT + Trackers + 32 Ports): {base_name}"
            )

    def _on_url_text_changed(self, text: str):
        self._probed_info = None
        u = (text or "").strip()
        if u.lower().startswith("magnet:?"):
            self.is_torrent = True
            dn = self.engine.extract_magnet_name(u)
            if dn and not self.txt_filename.text().strip():
                self.txt_filename.setText(dn)
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['success']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText(
                f"🧲 رابط Magnet تورنت جاهز للتحميل ({dn})"
                if self.is_ar
                else f"🧲 Magnet Torrent URI ready ({dn})"
            )
        elif u.lower().endswith(".torrent") and os.path.isfile(u):
            self.is_torrent = True
            base_name = os.path.splitext(os.path.basename(u))[0]
            if not self.txt_filename.text().strip():
                self.txt_filename.setText(base_name)

    def probe_now(self):
        url = self.txt_url.text().strip()
        if not url:
            self.txt_url.setFocus()
            return
        if url.lower().startswith("magnet:?") or (os.path.isfile(url) and url.lower().endswith(".torrent")):
            self._on_url_text_changed(url)
            return
        if not url.startswith("http"):
            return
        if is_drm_video_url(url):
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['danger']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText(localize_error_msg("drm protected", self.is_ar))
            return
        self.btn_probe.setEnabled(False)
        if self.is_video:
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['accent']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText("⏳ جاري قراءة الجودات المتاحة..." if self.is_ar else "⏳ Reading available qualities...")

            def worker():
                try:
                    res = self.engine.list_video_qualities(url)
                except Exception:
                    res = {"ok": False, "qualities": []}
                self.qualities_ready.emit(url, res)

            threading.Thread(target=worker, daemon=True).start()
            return
        self.lbl_probe_info.setStyleSheet(f"color: {pal()['accent']}; font-size: 12px; font-weight: 600;")
        self.lbl_probe_info.setText("⏳ جاري فحص الرابط..." if self.is_ar else "⏳ Probing URL...")

        def probe_worker():
            try:
                res = self.engine.probe_url(url)
                self.probe_ready.emit(url, {"ok": True, "data": res})
            except Exception as e:
                self.probe_ready.emit(url, {"ok": False, "error": str(e)})

        threading.Thread(target=probe_worker, daemon=True).start()

    def _on_probe_ready(self, url: str, payload: dict):
        self.btn_probe.setEnabled(True)
        if url != self.txt_url.text().strip():
            return
        if payload.get("ok"):
            res = payload["data"]
            self._probed_info = {"forUrl": url, **res}
            self.txt_filename.setText(res["filename"])
            self._set_category(res["category"])
            if not self._custom_save_dir:
                self.txt_savedir.setText(res["saveDir"])
                self.txt_savedir.setCursorPosition(0)
            sz = format_bytes(res["totalSize"]) if res["totalSize"] > 0 else ("بث مباشر" if self.is_ar else "Stream")
            if res["supportsRange"]:
                rng = "يدعم 32 بورت والاستكمال" if self.is_ar else "Supports 32-port resume"
            else:
                rng = "اتصال مباشر" if self.is_ar else "Direct stream"
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['success']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText(
                f"✅ الحجم: {L(sz)}  •  {rng}" if self.is_ar else f"✅ Size: {sz}  •  {rng}"
            )
        else:
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['warn']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText(
                f"ℹ جاهز للتحميل ({str(payload.get('error', ''))[:50]})"
                if self.is_ar
                else f"ℹ Ready to download ({str(payload.get('error', ''))[:50]})"
            )

    def _fill_qualities(self, qualities: list):
        """Best (plays everywhere) first, then every quality the video offers, then audio only."""
        keep = self.cmb_quality.currentData()
        self.cmb_quality.clear()
        self.cmb_quality.addItem(
            f"أفضل جودة متوافقة {L('(MP4)')}" if self.is_ar else "Best compatible quality (MP4)", "best"
        )
        for q in qualities:
            size = q.get("size") or 0
            size_txt = f"  ~{L(format_bytes(size))}" if size else ""
            self.cmb_quality.addItem(f"{q['label']}{size_txt}", q["quality"])
        self.cmb_quality.addItem("الصوت فقط (MP3)" if self.is_ar else "Audio only (MP3)", "audio")
        idx = self.cmb_quality.findData(keep) if keep else -1
        self.cmb_quality.setCurrentIndex(max(0, idx))

    def _on_qualities_ready(self, url: str, res: dict):
        self.btn_probe.setEnabled(True)
        if url != self.txt_url.text().strip():
            return  # the link changed while reading
        qualities = res.get("qualities") or []
        self._fill_qualities(qualities)
        if res.get("title") and not self.txt_filename.text().strip():
            self.txt_filename.setText(sanitize_filename(res["title"]))
        if qualities:
            n_q = len(qualities)
            if self.is_ar:
                if n_q == 1:
                    q_count = f"{L(1)} جودة متاحة"
                elif n_q == 2:
                    q_count = "جودتان متاحتان"
                elif 3 <= n_q <= 10:
                    q_count = f"{L(n_q)} جودات متاحة"
                else:
                    q_count = f"{L(n_q)} جودة متاحة"
                self.lbl_probe_info.setStyleSheet(f"color: {pal()['success']}; font-size: 12px; font-weight: 600;")
                self.lbl_probe_info.setText(f"‏✅ {q_count} — أعلاها {L(qualities[0]['label'])}")
            else:
                self.lbl_probe_info.setStyleSheet(f"color: {pal()['success']}; font-size: 12px; font-weight: 600;")
                self.lbl_probe_info.setText(f"✅ {n_q} qualities available — up to {qualities[0]['label']}")
        else:
            self.lbl_probe_info.setStyleSheet(f"color: {pal()['warn']}; font-size: 12px; font-weight: 600;")
            self.lbl_probe_info.setText(
                "ℹ تعذر قراءة الجودات — اختر أفضل جودة" if self.is_ar else "ℹ Couldn't read the qualities — choose Best quality"
            )

    def accept_download(self, start_immediately: bool):
        url = self.txt_url.text().strip()
        if not url:
            self.txt_url.setFocus()
            return
        if is_drm_video_url(url):
            self.probe_now()
            return
        q_val = "best"
        if self.is_video:
            q_val = self.cmb_quality.currentData() or "best"

        is_tor = (
            self.is_torrent
            or url.lower().startswith("magnet:?")
            or url.lower().split("?")[0].endswith(".torrent")
        )
        self.result_opts = {
            "url": url,
            "filename": self.txt_filename.text().strip(),
            "category": self.cmb_cat.currentData() or "General",
            "saveDir": self.txt_savedir.text().strip(),
            "customSaveDir": bool(self._custom_save_dir),
            "connections": 32 if (self.is_video or is_tor) else int(self.cmb_conn.currentText()),
            "startImmediately": start_immediately,
            "isVideo": self.is_video and not is_tor,
            "isTorrent": is_tor,
            "videoQuality": q_val,
        }
        probed = getattr(self, "_probed_info", None)
        if probed and probed.get("forUrl") == url:
            self.result_opts.update({
                "_probed": True,
                "url": probed.get("url") or url,
                "totalSize": int(probed.get("totalSize") or 0),
                "supportsRange": bool(probed.get("supportsRange", True)),
                "etag": probed.get("etag") or "",
                "lastModified": probed.get("lastModified") or "",
            })
        self.accept()


# ==============================================================================
# CORE MULTI-THREADED ENGINE + SIGNAL BRIDGE
# ==============================================================================
class EngineSignals(QObject):
    updated = pyqtSignal()
    completed = pyqtSignal(str)
    browser_captured = pyqtSignal(dict)
    focus_requested = pyqtSignal()
    extension_connected = pyqtSignal(str)
    torrent_files_ready = pyqtSignal(str)
    open_request = pyqtSignal(str)
    lang_changed = pyqtSignal(str)
    quit_requested = pyqtSignal()
    update_available = pyqtSignal(dict)


class _StrictCookieJar(requests.cookies.RequestsCookieJar):
    """RequestsCookieJar that always preserves hostOnly (DomainStrictNonDomain) across copies."""

    def __init__(self, policy=None):
        super().__init__(
            policy=policy
            or http.cookiejar.DefaultCookiePolicy(
                strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain
            )
        )

    def copy(self):
        new_jar = _StrictCookieJar()
        new_jar.update(self)
        return new_jar


class _StrictCookieSession(requests.Session):
    """requests.Session that enforces DomainStrictNonDomain across prepare_request and HTTP redirects."""

    def __init__(self, jar=None):
        super().__init__()
        self.cookies = _StrictCookieJar()
        if jar is not None:
            self.cookies.update(jar)

    def prepare_request(self, request):
        prepared = super().prepare_request(request)
        strict_jar = _StrictCookieJar()
        if prepared._cookies is not None:
            strict_jar.update(prepared._cookies)
        prepared.headers.pop("Cookie", None)
        prepared.prepare_cookies(strict_jar)
        return prepared


class ScorpionNativeEngine(BrowserTransferMixin):
    REQUIRED_EXT_FILES = (
        "manifest.json",
        "background.js",
        "content.js",
        "media.js",
        "browser-transfer.js",
        "telegram-reader.js",
        "content.css",
        "popup.html",
        "popup.js",
        "welcome.html",
        "welcome.css",
        "welcome.js",
        "icon.png",
        "scorpion-logo.svg",
        "icons/icon-16.png",
        "icons/icon-32.png",
        "icons/icon-48.png",
        "icons/icon-128.png",
    )

    def __init__(self):
        self.signals = EngineSignals()
        self.project_root = RESOURCE_ROOT
        self.ext_source_dir = os.path.join(self.project_root, "browser-extension")
        self.app_data = os.path.join(os.path.expanduser("~"), "AppData", "Local", "ScorpionIDM")
        self.legacy_prog_ext_dir = os.path.join(
            os.path.expanduser("~"), "AppData", "Local", "Programs", "ScorpionIDM", "browser-extension"
        )
        self.appdata_ext_dir = os.path.join(self.app_data, "browser-extension")
        self.temp_root = os.path.join(self.app_data, "temp")
        self.default_dl_root = os.path.join(os.path.expanduser("~"), "Downloads", "Scorpion")
        self.state_file = os.path.join(self.app_data, "scorpion_native_state.json")
        self.rpc_port = 19615
        self.rpc_alive = False
        self.last_ext_seen = {}
        self.bridge_token = load_or_create_bridge_token(self.app_data)
        self._diagnostics = []

        self.settings = {
            "defaultConnections": 32,
            "globalSpeedLimitKbps": 0,
            "clipboardMonitor": True,
            "autoStartFromBrowser": True,
            "downloadsRoot": self.default_dl_root,
            "userAgent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) ScorpionIDM/2.0",
            "connectedBrowsers": [],
            "wizardShownOnce": False,
            "maxConcurrent": 4,
            "schedEnabled": False,
            "schedTime": "02:00",
            "schedLastFired": "",
            "startWithWindows": True,
            "associateTorrents": True,
            "autoCheckUpdates": True,
            "updateUrl": "https://github.com/Mahmoud-847/scorpion-idm.git",
            "lastSeenVersion": "",
            "theme": "dark",
        }
        self.total_speed = 0
        self.downloads = {}
        self.controllers = {}
        self._recent_captures = {}
        self.lock = threading.RLock()

        os.makedirs(self.app_data, exist_ok=True)
        os.makedirs(self.temp_root, exist_ok=True)
        os.makedirs(self.default_dl_root, exist_ok=True)
        for cat in list(CATEGORY_MAP.keys()) + ["General"]:
            os.makedirs(os.path.join(self.default_dl_root, cat), exist_ok=True)

        self._load_state()
        self._apply_install_prefs()
        if self.settings.get("lang") not in ("ar", "en"):
            self.settings["lang"] = windows_display_language()
        if not (self.settings.get("updateUrl") or "").strip():
            self.settings["updateUrl"] = "https://github.com/Mahmoud-847/scorpion-idm.git"
            self.save_state()
        self.cleanup_old_update_files()
        # Reads every browser profile's preferences and hashes extension files: never on the window's thread
        threading.Thread(target=self.sync_and_repair_browser_extensions, daemon=True).start()
        threading.Thread(target=self._speed_loop, daemon=True).start()
        threading.Thread(target=self._start_browser_rpc_bridge, daemon=True).start()
        threading.Thread(target=self._queue_loop, daemon=True).start()

    def cleanup_old_update_files(self):
        """Removes any .old_* renamed binaries left over from a previous in-place update."""
        install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ScorpionIDM")
        if EMBEDDED_RUNTIME:
            # PyInstaller runtime of versions before the move to the signed Python runtime
            shutil.rmtree(os.path.join(RESOURCE_ROOT, "_internal"), ignore_errors=True)
        for root_dir in {self.project_root, install_dir}:
            if not root_dir or not os.path.isdir(root_dir):
                continue
            for dirpath, _dirnames, filenames in os.walk(root_dir):
                for fn in filenames:
                    if ".old_" in fn:
                        try:
                            os.remove(os.path.join(dirpath, fn))
                        except Exception:
                            pass

    def check_for_updates(self) -> dict:
        """Checks configured update URL / GitHub repo / shared manifest and returns update status."""
        latest_entry = CHANGELOG_HISTORY[0]
        result = {
            "hasUpdate": False,
            "currentVersion": APP_VERSION,
            "latestVersion": APP_VERSION,
            "publishedAt": latest_entry["date"],
            "title_ar": latest_entry["title_ar"],
            "title_en": latest_entry["title_en"],
            "changelog_ar": list(latest_entry["ar"]),
            "changelog_en": list(latest_entry["en"]),
            "downloadUrl": "",
            "localPackage": "",
        }
        src = (self.settings.get("updateUrl") or "").strip()
        if is_msix_packaged():
            result["storeManaged"] = True
            return result
        manifest = None

        if src:
            try:
                # 1) Local or LAN file path (e.g. \\Server\Share\update.json or folder)
                if os.path.exists(src):
                    m_path = os.path.join(src, "update.json") if os.path.isdir(src) else src
                    if os.path.isfile(m_path):
                        with open(m_path, "r", encoding="utf-8") as f:
                            manifest = json.load(f)
                        base_dir = os.path.dirname(m_path)
                        pkg_name = manifest.get("packageFile") or "Scorpion-Update-Payload.zip"
                        cand_pkg = os.path.join(base_dir, pkg_name)
                        if os.path.isfile(cand_pkg):
                            manifest["localPackage"] = cand_pkg
                # 2) GitHub shorthand (owner/repo) or github.com URL (incl. .git)
                elif (
                    not src.startswith(("http://", "https://"))
                    and "/" in src
                    and len(src.split("/")) == 2
                ) or ("github.com/" in src.lower() and not src.lower().endswith(".json")):
                    repo = src.split("github.com/")[-1].strip("/")
                    repo = "/".join(repo.split("/")[:2])
                    if repo.lower().endswith(".git"):
                        repo = repo[:-4]
                    # Check raw update.json in main/master branch first
                    for branch in ("main", "master"):
                        # raw.githubusercontent.com caches files for 5 minutes; a unique query string skips that cache
                        raw_url = f"https://raw.githubusercontent.com/{repo}/{branch}/release/update.json?t={int(time.time())}"
                        r_raw = requests.get(
                            raw_url, headers={"User-Agent": BROWSER_UA, "Cache-Control": "no-cache"}, timeout=10
                        )
                        if r_raw.status_code == 200:
                            manifest = r_raw.json()
                            if isinstance(manifest, dict) and not manifest.get("downloadUrl"):
                                pkg_fn = manifest.get("packageFile") or "Scorpion-Update-Payload.zip"
                                manifest["downloadUrl"] = f"https://github.com/{repo}/raw/{branch}/release/{pkg_fn}"
                            break
                    # Also check GitHub Releases API in case a newer Release tag was published
                    api_url = f"https://api.github.com/repos/{repo}/releases/latest"
                    r = requests.get(api_url, headers={"User-Agent": BROWSER_UA}, timeout=10)
                    if r.status_code == 200:
                        rel = r.json()
                        ver = str(rel.get("tag_name") or rel.get("name") or APP_VERSION).lstrip("vV")
                        # Only app releases count: other releases (e.g. the tools pack "tools-<id>") are not
                        # versions, and their digits would read as a huge version number
                        is_app_release = bool(re.fullmatch(r"\d+(\.\d+)+", ver)) and not rel.get("prerelease")
                        if is_app_release and (
                            not isinstance(manifest, dict) or _ver_tuple(ver) > _ver_tuple(manifest.get("version") or "0")
                        ):
                            notes = [
                                line.strip(" -*•\t")
                                for line in (rel.get("body") or "").splitlines()
                                if line.strip(" -*•\t")
                            ]
                            assets = rel.get("assets") or []
                            selected_asset = None
                            for asset in assets:
                                aname = (asset.get("name") or "").lower()
                                if aname == "scorpion-update-payload.zip":
                                    selected_asset = asset
                                    break
                            if selected_asset is None:
                                for asset in assets:
                                    aname = (asset.get("name") or "").lower()
                                    if re.fullmatch(r"scorpion-setup-[\d.]+\.exe", aname):
                                        selected_asset = asset
                                        break
                            dl_url = (selected_asset.get("browser_download_url") or "") if selected_asset else ""
                            pkg_name = (selected_asset.get("name") or "").lower() if selected_asset else ""
                            rel_sha = ""
                            if selected_asset:
                                digest = str(selected_asset.get("digest") or "").strip().lower()
                                if digest.startswith("sha256:") and re.fullmatch(r"[0-9a-f]{64}", digest.split(":", 1)[1]):
                                    rel_sha = digest.split(":", 1)[1]
                            if pkg_name and not rel_sha:
                                for asset in assets:
                                    if (asset.get("name") or "").lower() == pkg_name + ".sha256":
                                        r_sha = requests.get(
                                            asset.get("browser_download_url") or "",
                                            headers={"User-Agent": BROWSER_UA},
                                            timeout=10,
                                        )
                                        if r_sha.status_code == 200:
                                            cand_sha = (r_sha.text.split() or [""])[0].strip().lower()
                                            if re.fullmatch(r"[0-9a-f]{64}", cand_sha):
                                                rel_sha = cand_sha
                                        break
                            if pkg_name and not rel_sha:
                                for asset in assets:
                                    if (asset.get("name") or "").lower() == "update.json":
                                        r_upd = requests.get(
                                            asset.get("browser_download_url") or "",
                                            headers={"User-Agent": BROWSER_UA},
                                            timeout=10,
                                        )
                                        if r_upd.status_code == 200:
                                            upd_m = r_upd.json() or {}
                                            cand_sha = str(upd_m.get("sha256") or "").strip().lower()
                                            if str(upd_m.get("packageFile") or "").lower() == pkg_name and re.fullmatch(r"[0-9a-f]{64}", cand_sha):
                                                rel_sha = cand_sha
                                        break
                            if dl_url and len(rel_sha) == 64:
                                manifest = {
                                    "version": ver,
                                    "publishedAt": (rel.get("published_at") or "")[:10] or latest_entry["date"],
                                    "title_ar": rel.get("name") or f"الإصدار {ver}",
                                    "title_en": rel.get("name") or f"Version {ver}",
                                    "changelog_ar": notes or latest_entry["ar"],
                                    "changelog_en": notes or latest_entry["en"],
                                    "downloadUrl": dl_url,
                                    "sha256": rel_sha,
                                }
                            else:
                                result["error"] = (
                                    "إصدار التحديث يفتقد حزمة التطبيق أو بصمة التحقق SHA-256 / "
                                    "Release update is missing verified app package or SHA-256 checksum"
                                )
                # 3) Direct HTTP/HTTPS URL to update.json (or direct .zip/.exe link)
                elif src.startswith(("http://", "https://")):
                    if src.lower().split("?")[0].endswith((".zip", ".exe")):
                        manifest = {
                            "version": APP_VERSION,
                            "downloadUrl": src,
                        }
                    else:
                        r = requests.get(src, headers={"User-Agent": BROWSER_UA}, timeout=10)
                        if r.status_code == 200:
                            manifest = r.json()
            except requests.exceptions.SSLError:
                result["error"] = "تعذر التحقق من شهادة الاتصال بخادم التحديثات (قد يكون بسبب جدار حماية الشبكة) / Couldn't verify the update server's certificate (a network firewall may be inspecting HTTPS)"
            except requests.exceptions.Timeout:
                result["error"] = "انتهت مهلة الاتصال بخادم التحديثات / Connection to the update server timed out"
            except requests.exceptions.ConnectionError:
                result["error"] = "لا يوجد اتصال بخادم التحديثات / Can't reach the update server"
            except Exception:
                # Raw exception text can contain server addresses; never show those to users
                result["error"] = "تعذر قراءة معلومات التحديث / Couldn't read the update information"
            if manifest is None and not result.get("error"):
                result["error"] = "لم يتم العثور على معلومات التحديث / No update information found"

        result["checkedAt"] = time.strftime("%Y-%m-%d %H:%M")
        if isinstance(manifest, dict):
            rem_ver = str(manifest.get("version") or APP_VERSION).strip().lstrip("vV")
            result["latestVersion"] = rem_ver
            result["hasUpdate"] = _ver_tuple(rem_ver) > _ver_tuple(APP_VERSION)
            # Release notes come from the server only for a newer version; otherwise the
            # local history describes what is installed (the server copy may be older or cached)
            if result["hasUpdate"]:
                result["publishedAt"] = manifest.get("publishedAt") or result["publishedAt"]
                result["title_ar"] = manifest.get("title_ar") or f"الإصدار {rem_ver}"
                result["title_en"] = manifest.get("title_en") or f"Version {rem_ver}"
                if manifest.get("changelog_ar"):
                    result["changelog_ar"] = list(manifest["changelog_ar"])
                if manifest.get("changelog_en"):
                    result["changelog_en"] = list(manifest["changelog_en"])
                result["downloadUrl"] = (manifest.get("downloadUrl") or "").strip()
                result["localPackage"] = (manifest.get("localPackage") or "").strip()
                result["sha256"] = (manifest.get("sha256") or "").strip().lower()
            if isinstance(manifest.get("tools"), dict):
                result["tools"] = manifest["tools"]

        return result

    def tools_ready(self) -> bool:
        return all(os.path.isfile(os.path.join(TOOLS_DIR, f)) for f in TOOLS_PACK_FILES)

    def ensure_tools(self, tools: dict) -> bool:
        """
        Installs or refreshes the bundled programs (ffmpeg, ffprobe, QuickJS) from the tools pack
        described in update.json, so video and audio work without installing anything.
        """
        tools = tools or {}
        version = str(tools.get("version") or "").strip()
        url = str(tools.get("url") or "").strip()
        expected = str(tools.get("sha256") or "").strip().lower()
        if not version or not url.lower().startswith("https://") or len(expected) != 64:
            return False
        ver_file = os.path.join(TOOLS_DIR, "version.txt")
        try:
            with open(ver_file, "r", encoding="utf-8") as f:
                if f.read().strip() == version and self.tools_ready():
                    return True
        except OSError:
            pass
        if getattr(self, "_tools_busy", False):
            return False
        self._tools_busy = True
        pkg = os.path.join(self.temp_root, "Scorpion_Tools_Pkg.zip")
        try:
            import zipfile

            os.makedirs(self.temp_root, exist_ok=True)
            sha = hashlib.sha256()
            with requests.get(url, headers={"User-Agent": BROWSER_UA}, stream=True, timeout=30) as r:
                r.raise_for_status()
                with open(pkg, "wb") as f:
                    for chunk in r.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            f.write(chunk)
                            sha.update(chunk)
            if sha.hexdigest() != expected:
                return False
            os.makedirs(TOOLS_DIR, exist_ok=True)
            root = os.path.normcase(os.path.abspath(TOOLS_DIR))
            with zipfile.ZipFile(pkg) as zf:
                for m in zf.infolist():
                    dest = os.path.normcase(os.path.abspath(os.path.join(TOOLS_DIR, m.filename)))
                    if os.path.commonpath([root, dest]) != root:
                        return False
                for m in zf.infolist():
                    if m.is_dir():
                        continue
                    target = os.path.join(TOOLS_DIR, m.filename)
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    tmp = target + ".part"
                    with zf.open(m) as src_f, open(tmp, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
                    try:
                        os.replace(tmp, target)
                    except PermissionError:
                        # The old file is in use: move it aside, it is cleaned up on the next start
                        os.replace(target, f"{target}.old_{int(time.time() * 1000)}")
                        os.replace(tmp, target)
            with open(ver_file, "w", encoding="utf-8") as f:
                f.write(version)
            return self.tools_ready()
        except Exception:
            return False
        finally:
            self._tools_busy = False
            try:
                os.remove(pkg)
            except OSError:
                pass

    def install_update_package(self, pkg_path: str, expected_sha256: str = "", progress_cb=None) -> tuple:
        """
        Applies an update package (.zip payload or Setup .exe) via staged extraction and
        transactional rollback if any file write/swap fails.
        """
        import subprocess
        import time
        import zipfile

        if is_msix_packaged():
            return False, "تُدار التحديثات تلقائياً عبر Microsoft Store / Updates are managed by Microsoft Store."

        if not os.path.isfile(pkg_path):
            return False, "ملف التحديث غير موجود"

        expected = (expected_sha256 or "").strip().lower()
        if len(expected) != 64:
            return False, "التحديث بدون بصمة SHA-256 — تم الإلغاء / Update has no SHA-256 checksum, aborted"
        sha = hashlib.sha256()
        with open(pkg_path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                sha.update(chunk)
        if sha.hexdigest() != expected:
            return False, "بصمة ملف التحديث غير مطابقة — تم الإلغاء / Update checksum mismatch, aborted"

        install_dir = os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ScorpionIDM")
        os.makedirs(install_dir, exist_ok=True)
        install_root = os.path.normcase(os.path.abspath(install_dir))
        exe_path = os.path.join(install_dir, "ScorpionIDM.exe")

        if pkg_path.lower().endswith(".exe") and not zipfile.is_zipfile(pkg_path):
            subprocess.Popen(
                [pkg_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], cwd=os.path.dirname(pkg_path)
            )
            if hasattr(self, "signals"):
                self.signals.quit_requested.emit()
            return True, "restarting"

        def _rm_tree(path):
            if not path or not os.path.exists(path):
                return
            for root_p, dirs, files in os.walk(path, topdown=False):
                for fn in files:
                    try:
                        os.remove(os.path.join(root_p, fn))
                    except OSError:
                        pass
                for dn in dirs:
                    try:
                        os.rmdir(os.path.join(root_p, dn))
                    except OSError:
                        pass
            try:
                os.rmdir(path)
            except OSError:
                pass

        ts = int(time.time() * 1000)
        stage_dir = os.path.join(install_dir, f".update_stage_{ts}")
        stage_root = os.path.normcase(os.path.abspath(stage_dir))
        staged_files = []
        swapped = []
        committed = False
        try:
            os.makedirs(stage_dir, exist_ok=True)
            with zipfile.ZipFile(pkg_path, "r") as zf:
                members = zf.infolist()
                for member in members:
                    dest = os.path.normcase(os.path.abspath(os.path.join(install_dir, member.filename)))
                    stage_dest = os.path.normcase(os.path.abspath(os.path.join(stage_dir, member.filename)))
                    if os.path.commonpath([install_root, dest]) != install_root or os.path.commonpath([stage_root, stage_dest]) != stage_root:
                        return False, f"مسار غير آمن داخل ملف التحديث / Unsafe path in update package: {member.filename}"
                total = max(1, len(members))
                # Phase 1: Extract every file into stage_dir before touching live files in install_dir
                for idx, member in enumerate(members, 1):
                    staged_path = os.path.normpath(os.path.join(stage_dir, member.filename))
                    if member.is_dir():
                        os.makedirs(staged_path, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(staged_path), exist_ok=True)
                    with zf.open(member) as src_f, open(staged_path, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
                        dst_f.flush()
                    staged_files.append((member.filename, staged_path))
                    if progress_cb and (idx % 15 == 0 or idx == total):
                        try:
                            progress_cb(min(90, int(50 + 40 * idx / total)))
                        except Exception:
                            pass

            # Phase 2: Atomic per-file swap with full rollback if any replacement fails
            for idx, (rel_name, staged_path) in enumerate(staged_files, 1):
                target_path = os.path.normpath(os.path.join(install_dir, rel_name))
                os.makedirs(os.path.dirname(target_path), exist_ok=True)
                backup_path = ""
                if os.path.exists(target_path):
                    backup_path = f"{target_path}.old_{ts}_{idx}"
                    os.replace(target_path, backup_path)
                try:
                    os.replace(staged_path, target_path)
                except Exception:
                    if backup_path and os.path.exists(backup_path) and not os.path.exists(target_path):
                        try:
                            os.replace(backup_path, target_path)
                        except OSError:
                            pass
                    raise
                swapped.append((target_path, backup_path))
            committed = True
        except Exception as e:
            for tp, bp in reversed(swapped):
                try:
                    if os.path.exists(tp):
                        os.remove(tp)
                except OSError:
                    pass
                if bp and os.path.exists(bp):
                    try:
                        os.replace(bp, tp)
                    except OSError:
                        pass
            _rm_tree(stage_dir)
            return False, str(e)

        # Commit point passed: never rollback or remove live files on any post-commit step.
        if committed:
            for _tp, bp in swapped:
                if bp and os.path.exists(bp):
                    try:
                        os.remove(bp)
                    except OSError:
                        pass
            _rm_tree(stage_dir)
            if progress_cb:
                try:
                    progress_cb(100)
                except Exception:
                    pass
            try:
                if hasattr(self, "sync_and_repair_browser_extensions"):
                    self.sync_and_repair_browser_extensions()
            except Exception:
                pass
            try:
                if hasattr(self, "settings") and "ensure_app_shortcuts" in globals():
                    ensure_app_shortcuts(self.settings)
            except Exception:
                pass
            launched = False
            launch_err = ""
            try:
                if os.path.exists(exe_path):
                    subprocess.Popen([exe_path], cwd=install_dir)
                    launched = True
                    if hasattr(self, "signals"):
                        self.signals.quit_requested.emit()
                else:
                    launch_err = "executable missing"
            except Exception as exc:
                launch_err = str(exc)
            if not launched:
                return True, f"installed_restart_failed:{launch_err}"
            return True, "restarting"

    def _apply_install_prefs(self):
        """Apply one-time installer preferences while preserving a saved language."""
        old_bat = os.path.join(self.app_data, "uninstall.bat")
        if os.path.exists(old_bat):
            try:
                os.remove(old_bat)
            except Exception:
                pass
        prefs_file = os.path.join(self.app_data, "install_prefs.json")
        if not os.path.exists(prefs_file):
            return
        try:
            with open(prefs_file, "r", encoding="utf-8") as f:
                prefs = json.load(f)
            if self.settings.get("lang") not in ("ar", "en") and prefs.get("lang") in ("ar", "en"):
                self.settings["lang"] = prefs["lang"]
            for k in ("startWithWindows", "associateTorrents", "desktopShortcut"):
                if k in prefs:
                    self.settings[k] = bool(prefs[k])
            os.remove(prefs_file)
            self.save_state()
        except Exception:
            pass

    def active_count(self) -> int:
        return len(self.controllers)

    def _queue_loop(self):
        """Starts queued downloads when a slot is free, and fires the daily scheduler."""
        while True:
            time.sleep(1.0)
            try:
                self.expire_browser_transfers()
                # Scheduler: at the chosen time (once per day) move scheduled downloads into the queue
                if self.settings.get("schedEnabled"):
                    now = time.localtime()
                    today = time.strftime("%Y-%m-%d", now)
                    hh, mm = (self.settings.get("schedTime") or "02:00").split(":")[:2]
                    due = (now.tm_hour, now.tm_min) >= (int(hh), int(mm))
                    if due and self.settings.get("schedLastFired") != today:
                        with self.lock:
                            self.settings["schedLastFired"] = today
                            for it in self.downloads.values():
                                if it.get("status") == "scheduled":
                                    it["status"] = "queued"
                        self.save_state()
                # Queue: start the oldest queued items while there are free slots
                max_c = max(1, int(self.settings.get("maxConcurrent") or 4))
                with self.lock:
                    queued = sorted(
                        (it for it in self.downloads.values() if it.get("status") == "queued"),
                        key=lambda x: x.get("createdAt", 0),
                    )
                for it in queued:
                    with self.lock:
                        if self.active_count() >= max_c:
                            break
                        if it.get("status") != "queued":
                            continue
                        it["status"] = "paused"
                    self.start_download(it["id"])
            except Exception:
                pass

    def sync_and_repair_browser_extensions(self) -> dict:
        # One at a time: startup runs it in the background while a dialog may ask for it
        lock = self.__dict__.setdefault("_ext_sync_lock", threading.Lock())
        with lock:
            return self._sync_and_repair_browser_extensions()

    def _sync_and_repair_browser_extensions(self) -> dict:
        """
        Ensures all browser extension files and per-install bridge-auth.json exist across:
        1. Declared extension directories (ext_source_dir, legacy_prog_ext_dir, appdata_ext_dir)
        2. Any unpacked local copy under ~/Downloads/Scorpion-Browser-Extension or browser Preferences.
        Never writes bridge-auth.json inside a checked-out git workspace root.
        """
        repaired_paths = []
        src_abs = os.path.normcase(os.path.abspath(self.ext_source_dir))
        msix_mode = is_msix_packaged()
        if msix_mode:
            return {
                "primaryPath": self.ext_source_dir,
                "legacyPath": "",
                "filesPresent": sum(os.path.exists(os.path.join(self.ext_source_dir, f)) for f in self.REQUIRED_EXT_FILES),
                "filesTotal": len(self.REQUIRED_EXT_FILES),
                "repairedPaths": [],
            }
        candidate_dirs = [self.ext_source_dir, self.legacy_prog_ext_dir, self.appdata_ext_dir]
        # Avoid touching user Downloads in isolated temporary test environments (e.g. legacy_prog_ext_dir under TEMP)
        is_isolated_temp = os.path.normcase(os.path.abspath(self.legacy_prog_ext_dir)).startswith(
            os.path.normcase(os.path.abspath(os.environ.get("TEMP", "") or "__none__"))
        )
        if not is_isolated_temp:
            dl_ext = os.path.join(os.path.expanduser("~"), "Downloads", "Scorpion-Browser-Extension")
            if _canon_ext_dir(dl_ext) in _trusted_local_extension_dirs(self.ext_source_dir):
                candidate_dirs.append(dl_ext)

        seen_dirs = set()
        tok = getattr(self, "bridge_token", "")
        for target_dir in candidate_dirs:
            if not target_dir:
                continue
            try:
                tgt_abs = os.path.normcase(os.path.abspath(target_dir))
                if tgt_abs in seen_dirs:
                    continue
                seen_dirs.add(tgt_abs)
                same_as_src = tgt_abs == src_abs
                if not same_as_src:
                    os.makedirs(target_dir, exist_ok=True)
                    for fname in self.REQUIRED_EXT_FILES:
                        src = os.path.join(self.ext_source_dir, fname)
                        dst = os.path.join(target_dir, fname)
                        if os.path.exists(src):
                            os.makedirs(os.path.dirname(dst), exist_ok=True)
                            shutil.copy2(src, dst)
                    repaired_paths.append(target_dir)
                parent_git = os.path.isdir(os.path.join(os.path.dirname(os.path.abspath(target_dir)), ".git"))
                if tok and not parent_git and (same_as_src or os.path.isdir(target_dir)):
                    auth_file = os.path.join(target_dir, "bridge-auth.json")
                    with open(auth_file, "w", encoding="utf-8") as af:
                        json.dump({"token": tok}, af)
            except Exception:
                pass

        if "register_native_messaging_hosts" in globals() and hasattr(self, "app_data"):
            try:
                register_native_messaging_hosts(self.app_data, write_registry=not is_isolated_temp)
            except Exception:
                pass

        present_count = sum(
            1 for f in self.REQUIRED_EXT_FILES if os.path.exists(os.path.join(self.ext_source_dir, f))
        )
        return {
            "primaryPath": self.ext_source_dir,
            "legacyPath": self.legacy_prog_ext_dir,
            "filesPresent": present_count,
            "filesTotal": len(self.REQUIRED_EXT_FILES),
            "repairedPaths": repaired_paths,
        }

    def get_permanent_ext_dir(self) -> str:
        if is_msix_packaged():
            return self.ext_source_dir
        self.sync_and_repair_browser_extensions()
        if os.path.exists(os.path.join(self.legacy_prog_ext_dir, "manifest.json")):
            return self.legacy_prog_ext_dir
        return self.ext_source_dir

    def record_browser_connection(self, br_key: str):
        br = (br_key or "chrome").strip().lower()
        if br == "edge":
            br = "msedge"
        if br not in ("chrome", "msedge", "brave"):
            br = "chrome"
        self.last_ext_seen[br] = time.time()
        conn = self.settings.setdefault("connectedBrowsers", [])
        if not isinstance(conn, list):
            conn = []
            self.settings["connectedBrowsers"] = conn
        if br not in conn:
            conn.append(br)
            self.save_state()
        self.signals.extension_connected.emit(br)

    def active_connected_browsers(self, max_age: float = 12.0) -> list:
        now = time.time()
        seen = getattr(self, "last_ext_seen", None) or {}
        return [br for br, ts in seen.items() if now - float(ts or 0) <= max_age]

    def record_diagnostic(self, event: str, detail: str = ""):
        """Append a bounded diagnostic record after redacting query strings and cookie values."""
        try:
            scrubbed = re.sub(r"(https?://[^\s?]+)\?[^\s\"']+", r"\1?<redacted>", str(detail or ""))
            scrubbed = re.sub(r"(Cookie|Authorization|X-Scorpion-Token)\s*:\s*[^\r\n]+", r"\1: <redacted>", scrubbed, flags=re.I)
            line = f"{time.strftime('%Y-%m-%d %H:%M:%S')} [{event}] {scrubbed[:280]}"
            with self.lock:
                buf = self.__dict__.setdefault("_diagnostics", [])
                buf.append(line)
                if len(buf) > 100:
                    del buf[:-100]
            app_data = getattr(self, "app_data", "")
            if app_data:
                log_p = os.path.join(app_data, "diagnostics.log")
                if os.path.isfile(log_p) and os.path.getsize(log_p) > 256 * 1024:
                    with open(log_p, "r", encoding="utf-8", errors="ignore") as f:
                        tail = f.read()[-65536:]
                    with open(log_p, "w", encoding="utf-8") as f:
                        f.write(tail)
                with open(log_p, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
        except Exception:
            pass

    def create_store_pairing_code(self) -> str:
        if not is_msix_packaged():
            return ""
        code = secrets.token_hex(6).upper()
        with self.lock:
            self._store_pairing = (code, time.monotonic() + 300, 6)
        return "-".join(code[index:index + 4] for index in range(0, len(code), 4))

    def redeem_store_pairing_code(self, code: str) -> str:
        if not isinstance(code, str) or not re.fullmatch(r"[0-9A-Fa-f]{12}", code):
            return ""
        with self.lock:
            pairing = getattr(self, "_store_pairing", None)
            if pairing is None:
                return ""
            expected, deadline, attempts = pairing
            if time.monotonic() >= deadline:
                self._store_pairing = None
                return ""
            if hmac.compare_digest(expected, code.upper()):
                self._store_pairing = None
                return self.bridge_token
            self._store_pairing = (expected, deadline, attempts - 1) if attempts > 1 else None
            return ""

    def _start_browser_rpc_bridge(self):
        engine_ref = self
        store_mode = is_msix_packaged()

        class BridgeHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _origin_allowed(self) -> bool:
                """Only our browser extension or an authenticated local client may talk to the bridge."""
                origin = (self.headers.get("Origin") or "").strip().lower()
                if not origin:
                    return True
                return origin.startswith(BRIDGE_ALLOWED_ORIGIN_PREFIXES)

            def _is_trusted_client(self) -> bool:
                if not self._origin_allowed() or self.headers.get(BRIDGE_CLIENT_HEADER) != "1":
                    return False
                try:
                    expected_tok = getattr(engine_ref, "bridge_token", "")
                except NameError:
                    expected_tok = ""
                if not expected_tok:
                    return False
                provided_tok = (self.headers.get("X-Scorpion-Token") or "").strip()
                return bool(provided_tok and provided_tok.isascii() and
                            hmac.compare_digest(provided_tok, expected_tok))

            def _send_cors(self, code=200):
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                if store_mode:
                    self.send_header("X-Scorpion-Bridge-Mode", "store")
                    self.send_header("Access-Control-Expose-Headers", "X-Scorpion-Bridge-Mode")
                    self.send_header("Cache-Control", "no-store")
                origin = (self.headers.get("Origin") or "").strip()
                if origin and self._origin_allowed():
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", f"Content-Type, {BRIDGE_CLIENT_HEADER}, {BRIDGE_TOKEN_HEADER}")
                    self.send_header("Access-Control-Allow-Private-Network", "true")
                self.end_headers()

            def _reject(self):
                self._send_cors(403)
                self.wfile.write(json.dumps({"ok": False, "error": "forbidden"}).encode("utf-8"))

            def do_OPTIONS(self):
                self._send_cors(204 if self._origin_allowed() else 403)

            def do_GET(self):
                parsed = urllib.parse.urlparse(self.path)
                if not self._origin_allowed():
                    self._reject()
                    return
                if parsed.path != "/ping" and not self._is_trusted_client():
                    self._reject()
                    return
                if parsed.path == "/ping":
                    qs = urllib.parse.parse_qs(parsed.query)
                    is_auth = self._is_trusted_client()
                    if qs.get("ext") and not is_auth:
                        self._reject()
                        return
                    if qs.get("ext") and is_auth:
                        br = (qs.get("browser") or ["chrome"])[0]
                        engine_ref.record_browser_connection(br)
                    if qs.get("set_lang") and is_auth:
                        new_lang = (qs.get("set_lang") or [""])[0].strip().lower()
                        if new_lang in ("ar", "en") and engine_ref.settings.get("lang") != new_lang:
                            with engine_ref.lock:
                                engine_ref.settings["lang"] = new_lang
                            engine_ref.save_state()
                            engine_ref.signals.lang_changed.emit(new_lang)
                    self._send_cors(200)
                    ping_payload = {
                        "ok": True,
                        "app": "Scorpion IDM Native",
                        "version": APP_VERSION,
                        "authenticated": bool(is_auth),
                        "uiReady": bool(getattr(engine_ref, "_ui_ready", False)),
                        "uiVisible": bool(getattr(engine_ref, "_ui_visible", False)),
                        "uiPlatform": getattr(engine_ref, "_ui_platform", ""),
                        "lang": engine_ref.settings.get("lang", "ar"),
                        "activeCount": engine_ref.active_count(),
                    }
                    if is_auth:
                        with engine_ref.lock:
                            ping_payload["totalCount"] = len(engine_ref.downloads)
                            ping_payload["extensionCompletedCount"] = len(engine_ref.settings.get("extensionCompletedIds") or [])
                    self.wfile.write(json.dumps(ping_payload).encode("utf-8"))
                    return
                if parsed.path == "/focus":
                    engine_ref.signals.focus_requested.emit()
                    self._send_cors(200)
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    return
                if parsed.path == "/quit":
                    engine_ref.signals.quit_requested.emit()
                    self._send_cors(200)
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    return
                if parsed.path == "/formats":
                    qs = urllib.parse.parse_qs(parsed.query)
                    arg = lambda k: (qs.get(k) or [""])[0]
                    try:
                        res = engine_ref.list_video_qualities(arg("url"), arg("referer"), arg("tab"),
                                                             strict_target=arg("strictTarget").lower() in ("1", "true"))
                    except Exception:
                        res = {"ok": False, "qualities": []}
                    self._send_cors(200)
                    self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
                    return
                if parsed.path == "/capture":
                    qs = urllib.parse.parse_qs(parsed.query)
                    payload = {k: v[0] for k, v in qs.items() if v}
                    if payload.get("url"):
                        engine_ref.signals.browser_captured.emit(payload)
                    self._send_cors(200)
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    return
                self._send_cors(404)
                self.wfile.write(json.dumps({"ok": False}).encode("utf-8"))

            def do_POST(self):
                parsed = urllib.parse.urlparse(self.path)
                if store_mode and parsed.path == "/pair":
                    self._pair_store_extension()
                    return
                if not self._is_trusted_client():
                    self._reject()
                    return
                if parsed.path.startswith("/browser-transfer/"):
                    try:
                        length = int(self.headers.get("Content-Length") or 0)
                        if not 0 < length <= 1024 * 1024:
                            raise ValueError("حجم الطلب غير صالح.")
                        payload = json.loads(self.rfile.read(length).decode("utf-8"))
                        operation = parsed.path.rsplit("/", 1)[-1]
                        if operation == "start":
                            result = engine_ref.begin_browser_transfer(payload)
                        else:
                            result = engine_ref.receive_browser_transfer(operation, payload)
                        code = 200
                    except Exception as err:
                        result, code = {"ok": False, "error": str(err)[:240]}, 400
                    self._send_cors(code)
                    self.wfile.write(json.dumps(result, ensure_ascii=False).encode("utf-8"))
                    return
                if parsed.path == "/formats":
                    length = min(int(self.headers.get("Content-Length") or 0), 2 * 1024 * 1024)
                    try:
                        req = json.loads(self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}")
                        res = engine_ref.list_video_qualities(
                            req.get("url", ""),
                            req.get("referer", ""),
                            req.get("tab", ""),
                            req.get("candidates") or [],
                            req.get("cookies") or [],
                            strict_target=bool(req.get("strictTarget", False)),
                            user_agent=req.get("userAgent", ""),
                            accept_language=req.get("acceptLanguage", ""),
                        )
                    except Exception:
                        res = {"ok": False, "qualities": []}
                    self._send_cors(200)
                    self.wfile.write(json.dumps(res, ensure_ascii=False).encode("utf-8"))
                    return
                if parsed.path == "/capture":
                    length = min(int(self.headers.get("Content-Length") or 0), 2 * 1024 * 1024)
                    raw = self.rfile.read(length).decode("utf-8", errors="replace") if length > 0 else "{}"
                    try:
                        payload = json.loads(raw)
                    except Exception:
                        payload = {}
                    if payload.get("url"):
                        engine_ref.signals.browser_captured.emit(payload)
                    self._send_cors(200)
                    self.wfile.write(json.dumps({"ok": True}).encode("utf-8"))
                    return
                self._send_cors(404)
                self.wfile.write(json.dumps({"ok": False}).encode("utf-8"))

            def _pair_store_extension(self):
                origin = (self.headers.get("Origin") or "").strip()
                try:
                    size = int(self.headers.get("Content-Length") or 0)
                    if not 0 < size <= 128:
                        raise ValueError("Invalid pairing request size")
                    self.connection.settimeout(3)
                    body = self.rfile.read(size)
                    if (not re.fullmatch(r"chrome-extension://[a-p]{32}", origin) or
                            self.headers.get(BRIDGE_CLIENT_HEADER) != "1" or
                            self.headers.get_content_type() != "application/json"):
                        self._reject()
                        return
                    data = json.loads(body)
                    token = engine_ref.redeem_store_pairing_code(data.get("code")) if isinstance(data, dict) else ""
                except (ValueError, OSError):
                    token = ""
                if not token:
                    self._reject()
                    return
                self._send_cors(200)
                self.wfile.write(json.dumps({"ok": True, "token": token}).encode("utf-8"))

        try:
            srv = ThreadingHTTPServer(("127.0.0.1", self.rpc_port), BridgeHandler)
            self.rpc_alive = True
            srv.serve_forever()
        except Exception:
            self.rpc_alive = False

    def _load_state(self):
        data = None
        bak_file = self.state_file + ".bak"
        for cand, from_bak in ((self.state_file, False), (bak_file, True)):
            if not os.path.exists(cand):
                continue
            try:
                with open(cand, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    data = loaded
                    if from_bak:
                        self._state_recovered_from_backup = True
                        if hasattr(self, "record_diagnostic"):
                            self.record_diagnostic("state_recovered", "Recovered corrupted state from backup")
                        try:
                            shutil.copy2(bak_file, self.state_file)
                        except OSError:
                            pass
                    break
            except Exception as err:
                if hasattr(self, "record_diagnostic"):
                    self.record_diagnostic("load_state_error", str(err))
        if isinstance(data, dict):
            try:
                if isinstance(data.get("settings"), dict):
                    self.settings.update(data["settings"])
                    # One-time move to the new default; afterwards the user's own choice is kept
                    if not self.settings.get("connections32Migrated"):
                        if int(self.settings.get("defaultConnections") or 0) < 32:
                            self.settings["defaultConnections"] = 32
                        self.settings["connections32Migrated"] = True
                for item in data.get("downloads", []):
                    if not isinstance(item, dict) or not item.get("id"):
                        continue
                    if item.get("status") in ("downloading", "connecting"):
                        item["status"] = "paused"
                        item["speed"] = 0
                    dl_id = item.get("id")
                    fn = item.get("filename") or "download.bin"
                    stored_tmp = item.get("tempFilePath") or ""
                    temp_abs = os.path.normcase(os.path.abspath(self.temp_root))
                    inside_temp = False
                    if stored_tmp:
                        try:
                            st_abs = os.path.normcase(os.path.abspath(stored_tmp))
                            inside_temp = os.path.commonpath([temp_abs, st_abs]) == temp_abs and os.path.isfile(stored_tmp)
                        except ValueError:
                            inside_temp = False
                    if not inside_temp:
                        item["tempFilePath"] = os.path.join(self.get_item_temp_dir(dl_id), fn + ".scorpion_part")
                    self.downloads[dl_id] = item
            except Exception as err:
                if hasattr(self, "record_diagnostic"):
                    self.record_diagnostic("load_state_items_error", str(err))
        self._sweep_stray_part_files()

    def _sweep_stray_part_files(self):
        # Never touch files inside downloadsRoot: only clean orphaned temp entries owned inside temp_root.
        if os.path.isdir(self.temp_root):
            try:
                temp_abs = os.path.normcase(os.path.abspath(self.temp_root))
                known_ids = set(self.downloads.keys())
                for entry in os.listdir(self.temp_root):
                    p = os.path.join(self.temp_root, entry)
                    p_abs = os.path.normcase(os.path.abspath(p))
                    if os.path.commonpath([temp_abs, p_abs]) != temp_abs:
                        continue
                    if os.path.isdir(p) and entry not in known_ids:
                        shutil.rmtree(p, ignore_errors=True)
                    elif os.path.isfile(p) and entry.startswith("cookies_") and entry.endswith(".txt"):
                        try:
                            os.remove(p)
                        except OSError:
                            pass
            except Exception:
                pass

    def save_state(self):
        import threading

        state_path = getattr(self, "state_file", "")
        if not state_path:
            return
        try:
            with self.lock:
                seq = self.__dict__.get("_state_seq", 0) + 1
                self._state_seq = seq
                persisted_downloads = [
                    d for d in self.downloads.values() if isinstance(d, dict) and not d.get("incognito")
                ]
                snapshot = copy.deepcopy(
                    {"settings": dict(self.settings), "downloads": persisted_downloads}
                )
            os.makedirs(os.path.dirname(state_path), exist_ok=True)
            tmp_path = f"{state_path}.{seq}.{threading.get_ident()}.tmp"
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(snapshot, f, ensure_ascii=False, indent=2)
                f.flush()
                os.fsync(f.fileno())
            commit_lock = self.__dict__.setdefault("_state_commit_lock", threading.Lock())
            with commit_lock:
                if seq < self.__dict__.get("_state_committed_seq", 0):
                    try:
                        os.remove(tmp_path)
                    except OSError:
                        pass
                    return
                if os.path.isfile(state_path):
                    try:
                        shutil.copy2(state_path, state_path + ".bak")
                    except OSError:
                        pass
                os.replace(tmp_path, state_path)
                self._state_committed_seq = seq
        except Exception as err:
            if hasattr(self, "record_diagnostic"):
                self.record_diagnostic("save_state_error", str(err))

    def _cookies_to_jar(self, cookies):
        import http.cookiejar
        import time

        if not cookies:
            return None
        strict_pol = http.cookiejar.DefaultCookiePolicy(
            strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain
        )
        if isinstance(cookies, requests.cookies.RequestsCookieJar):
            if "_StrictCookieJar" in globals() and not isinstance(cookies, _StrictCookieJar):
                s_jar = _StrictCookieJar()
                s_jar.update(cookies)
                return s_jar
            cookies.set_policy(strict_pol)
            return cookies
        jar = _StrictCookieJar() if "_StrictCookieJar" in globals() else requests.cookies.RequestsCookieJar()
        jar.set_policy(strict_pol)
        now = time.time()
        if isinstance(cookies, dict):
            for k, v in cookies.items():
                jar.set(str(k), str(v or ""))
            return jar if len(jar) else None
        if isinstance(cookies, list):
            for c in cookies:
                if not isinstance(c, dict) or not c.get("name"):
                    continue
                raw_dom = str(c.get("domain") or "").strip()
                if not raw_dom:
                    continue
                host_only = bool(c.get("hostOnly", not raw_dom.startswith(".")))
                dom = raw_dom.lstrip(".") if host_only else (raw_dom if raw_dom.startswith(".") else "." + raw_dom)
                exp_raw = c.get("expirationDate")
                expires = None
                if exp_raw:
                    try:
                        exp_num = int(float(exp_raw))
                        if exp_num > 0:
                            if exp_num <= now:
                                continue
                            expires = exp_num
                    except (ValueError, TypeError):
                        pass
                rest = {"HttpOnly": None} if c.get("httpOnly") else {}
                ck = http.cookiejar.Cookie(
                    version=0,
                    name=str(c["name"]),
                    value=str(c.get("value") or ""),
                    port=None,
                    port_specified=False,
                    domain=dom,
                    domain_specified=not host_only,
                    domain_initial_dot=not host_only,
                    path=str(c.get("path") or "/"),
                    path_specified=True,
                    secure=bool(c.get("secure", False)),
                    expires=expires,
                    discard=expires is None,
                    comment=None,
                    comment_url=None,
                    rest=rest,
                    rfc2109=False,
                )
                jar.set_cookie(ck)
            return jar if len(jar) else None
        return None

    def _build_media_headers(
        self,
        referer: str = "",
        user_agent: str = "",
        accept_language: str = "",
        default_ua: str = BROWSER_UA,
        include_origin: bool = True,
    ) -> dict:
        hdrs = {
            "User-Agent": (user_agent or "").strip() or default_ua,
            "Accept-Language": (accept_language or "").strip() or "en-US,en;q=0.9,ar;q=0.8",
        }
        ref = (referer or "").strip()
        if ref:
            hdrs["Referer"] = ref
            if include_origin:
                pr = urllib.parse.urlparse(ref)
                if pr.scheme and pr.netloc:
                    hdrs["Origin"] = f"{pr.scheme}://{pr.netloc}"
        return hdrs

    def _http_session(self, cookies=None) -> requests.Session:
        jar = self._cookies_to_jar(cookies) if cookies is not None else None
        return _StrictCookieSession(jar)

    def probe_url(self, url: str, referer: str = "", cookies=None) -> dict:
        hdrs = {
            "User-Agent": (self.settings.get("userAgent") or BROWSER_UA),
            "Range": "bytes=0-0",
            "Accept-Encoding": "identity",
        }
        if referer:
            hdrs["Referer"] = referer
        jar = self._cookies_to_jar(cookies)
        sess = self._http_session(jar) if hasattr(self, "_http_session") else None
        try:
            if sess is not None:
                r = sess.get(url, headers=hdrs, stream=True, timeout=12, allow_redirects=True)
            else:
                r = requests.get(url, headers=hdrs, cookies=jar, stream=True, timeout=12, allow_redirects=True)
            final_url = r.url
            status = r.status_code
            resp_headers = dict(r.headers)
            r.close()
        finally:
            if sess is not None:
                sess.close()

        etag = (resp_headers.get("ETag") or resp_headers.get("etag") or "").strip()
        last_modified = (resp_headers.get("Last-Modified") or resp_headers.get("last-modified") or "").strip()

        total_size = 0
        supports_range = False
        if status == 206:
            supports_range = not etag.startswith("W/")
            cr = resp_headers.get("Content-Range") or resp_headers.get("content-range") or ""
            m_cr = __import__("re").fullmatch(r"bytes\s+0-0/(\d+)", cr.strip(), __import__("re").I)
            if m_cr:
                total_size = int(m_cr.group(1))
            elif "/" in cr:
                try:
                    total_size = int(cr.split("/")[-1])
                except Exception:
                    pass
        elif 200 <= status < 300:
            if "bytes" in (resp_headers.get("Accept-Ranges") or "").lower() and not etag.startswith("W/"):
                supports_range = True
            try:
                total_size = int(resp_headers.get("Content-Length") or resp_headers.get("content-length") or 0)
            except Exception:
                total_size = 0

        mime = (resp_headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
        filename = extract_filename(final_url, resp_headers)
        category = detect_category(filename, mime)
        save_dir = os.path.join(self.settings["downloadsRoot"], category)
        return {
            "url": final_url,
            "filename": filename,
            "totalSize": total_size,
            "supportsRange": supports_range,
            "category": category,
            "saveDir": save_dir,
            "etag": "" if etag.startswith("W/") else etag,
            "lastModified": last_modified,
        }

    def _create_segments(self, total_size: int, count: int):
        if total_size <= 0 or count <= 1:
            return [{"id": 1, "startByte": 0, "endByte": total_size - 1 if total_size > 0 else -1, "currentByte": 0, "downloaded": 0, "status": "idle", "info": "Ready"}]
        segs = []
        chunk = total_size // count
        for i in range(count):
            s = i * chunk
            e = (total_size - 1) if (i == count - 1) else ((i + 1) * chunk - 1)
            segs.append({"id": i + 1, "startByte": s, "endByte": e, "currentByte": s, "downloaded": 0, "status": "idle", "info": "Ready"})
        return segs

    def extract_magnet_name(self, uri: str) -> str:
        try:
            parsed = urllib.parse.urlparse(uri)
            qs = urllib.parse.parse_qs(parsed.query)
            if qs.get("dn") and qs["dn"][0]:
                return sanitize_filename(urllib.parse.unquote_plus(qs["dn"][0]))
        except Exception:
            pass
        return "Torrent_Download"

    def _is_torrent_source(self, url: str, opts: dict) -> bool:
        if opts.get("isTorrent") or opts.get("type") == "torrent":
            return True
        u_low = (url or "").strip().lower()
        if u_low.startswith("magnet:?"):
            return True
        if u_low.split("?")[0].endswith(".torrent"):
            return True
        if os.path.isfile(url) and u_low.endswith(".torrent"):
            return True
        return False

    def _find_aria2c(self) -> str:
        found = find_tool("aria2c")
        if found:
            return found
        return ""

    def _capture_key(self, url: str, quality: str = "", ptype: str = "") -> tuple:
        return ((url or "").strip(), (quality or "best").strip().lower(), (ptype or "file").strip().lower())

    def record_capture(self, url: str, quality: str, ptype: str, dl_id: str):
        key = self._capture_key(url, quality, ptype)
        with self.lock:
            self.__dict__.setdefault("_recent_captures", {})[key] = (time.time(), dl_id)

    def should_ignore_duplicate_capture(self, url: str, quality: str = "", ptype: str = "") -> str | None:
        url_clean = (url or "").strip()
        if not url_clean:
            return None
        key = self._capture_key(url_clean, quality, ptype)
        now = time.time()
        with self.lock:
            recent = self.__dict__.setdefault("_recent_captures", {})
            for k in [k for k, (ts, _did) in recent.items() if now - ts > 30.0]:
                recent.pop(k, None)
            hit = recent.get(key)
            if hit:
                _ts, dl_id = hit
                existing = self.downloads.get(dl_id)
                if existing and existing.get("status") != "error":
                    return dl_id
            q_clean = (quality or "best").strip().lower()
            for it in self.downloads.values():
                if (
                    (it.get("url") or "").strip() == url_clean
                    and it.get("status") in ("downloading", "connecting", "queued")
                    and (it.get("videoQuality") or "best").strip().lower() == q_clean
                ):
                    return it["id"]
        return None

    def add_download(self, opts: dict) -> dict:
        url = opts["url"].strip()
        total_size = int(opts.get("totalSize") or 0)
        supports_range = bool(opts.get("supportsRange", True))
        filename = opts.get("filename") or ""
        category = opts.get("category") or ""
        explicit_save_dir = (opts.get("saveDir") or "").strip()
        save_dir = explicit_save_dir
        is_torrent = self._is_torrent_source(url, opts)
        is_video = bool(opts.get("isVideo", False)) and not is_torrent
        is_incognito = bool(opts.get("incognito", False))
        needs_probe = (
            total_size <= 0
            and not is_video
            and not is_torrent
            and not opts.get("fromBrowser")
            and not opts.get("_probed")
        )

        if not filename:
            if is_torrent:
                if url.lower().startswith("magnet:?"):
                    filename = self.extract_magnet_name(url)
                else:
                    raw_fn = os.path.basename(url.split("?")[0]) or "Torrent_Download"
                    filename = raw_fn[:-8] if raw_fn.lower().endswith(".torrent") else raw_fn
            elif is_video:
                url_name = extract_filename(url, {})
                url_stem, url_ext = os.path.splitext(url_name)
                generic_stems = {
                    "", "master", "index", "playlist", "manifest", "video",
                    "audio", "stream", "playback", "watch", "media", "scorpion_file", "download_file",
                }
                media_exts = tuple(CATEGORY_MAP["Video"] + CATEGORY_MAP["Music"])
                if (
                    url_ext.lower() in media_exts
                    and url_stem.strip().lower() not in generic_stems
                    and not re.match(r"^index[-_]", url_stem.strip(), re.I)
                ):
                    filename = url_name
                else:
                    is_aud_dl = opts.get("videoQuality") == "audio" or category == "Music"
                    filename = "Scorpion_Audio.mp3" if is_aud_dl else "Scorpion_Video.mp4"
            else:
                filename = extract_filename(url, {})
        if is_torrent and filename.lower().endswith(".torrent"):
            filename = filename[:-8] or "Torrent_Download"
        filename = sanitize_filename(filename)
        if not category:
            category = "Video" if (is_video or is_torrent) else detect_category(filename)
        default_cat_dir = os.path.join(self.settings["downloadsRoot"], category)
        if not save_dir:
            save_dir = default_cat_dir
        custom_save_dir = bool(opts.get("customSaveDir")) or (
            bool(explicit_save_dir)
            and os.path.normcase(os.path.abspath(save_dir)) != os.path.normcase(os.path.abspath(default_cat_dir))
        )
        os.makedirs(save_dir, exist_ok=True)

        base, ext = os.path.splitext(filename)
        final_name = filename
        idx = 1
        # Snapshot under the lock: another thread may add a download while we look
        with self.lock:
            reserved_paths = {os.path.normcase(it.get("filePath") or "") for it in list(self.downloads.values())}
        while os.path.exists(os.path.join(save_dir, final_name)) or os.path.normcase(os.path.join(save_dir, final_name)) in reserved_paths:
            final_name = f"{base} ({idx}){ext}"
            idx += 1

        file_path = os.path.join(save_dir, final_name)
        dl_id = str(uuid.uuid4())
        item_temp_dir = self.get_item_temp_dir(dl_id)
        temp_path = os.path.join(item_temp_dir, final_name + ".scorpion_part")
        req_conns = int(opts.get("connections") or self.settings.get("defaultConnections") or 32)
        if is_torrent:
            conn_count = max(16, min(64, req_conns))
            supports_range = True
        else:
            conn_count = max(1, min(64, req_conns)) if (supports_range and total_size > 128 * 1024) else 1
        etag = (opts.get("etag") or "").strip()
        last_modified = (opts.get("lastModified") or "").strip()
        item = {
            "id": dl_id,
            "url": url,
            "filename": final_name,
            "category": category,
            "saveDir": save_dir,
            "customSaveDir": custom_save_dir,
            "filePath": file_path,
            "tempFilePath": temp_path,
            "totalSize": total_size,
            "downloadedBytes": 0,
            "progress": 0.0,
            "speed": 0,
            "timeLeft": None,
            "status": "paused",
            "supportsRange": supports_range,
            "connections": req_conns,
            "segments": self._create_segments(total_size, conn_count),
            "speedHistory": [],
            "speedLimitKbps": 0,
            "createdAt": int(time.time() * 1000),
            "isVideo": is_video,
            "fromBrowser": bool(opts.get("fromBrowser") or opts.get("browserTransfer")),
            "browserTransfer": bool(opts.get("browserTransfer")),
            "expectedDuration": finite_duration(opts.get("expectedDuration")),
            "isTorrent": is_torrent,
            "videoQuality": opts.get("videoQuality", "best"),
            "referer": (opts.get("referer") or "").strip(),
            # Page the user was on when the download came from an embedded player (iframe)
            "tabUrl": (opts.get("tabUrl") or "").strip(),
            # Other addresses that may identify the video (post links near it, streams the player loaded)
            "candidates": [c for c in (opts.get("candidates") or []) if isinstance(c, str)][:10],
            "strictTarget": bool(opts.get("strictTarget", False)),
            "userAgent": (opts.get("userAgent") or "").strip(),
            "acceptLanguage": (opts.get("acceptLanguage") or "").strip(),
            "etag": "" if etag.startswith("W/") else etag,
            "lastModified": last_modified,
            "validatorRecorded": bool((etag and not etag.startswith("W/")) or last_modified),
            "incognito": is_incognito,
            "checksumSha256": None,
            "checksumMd5": None,
        }
        if needs_probe:
            item["_needsInitialProbe"] = True
        with self.lock:
            self.downloads[dl_id] = item
        cap_quality = opts.get("_captureQuality") or ("audio" if opts.get("category") == "Music" else opts.get("videoQuality", "best"))
        cap_type = opts.get("_captureType") or ("torrent" if is_torrent else ("audio" if cap_quality == "audio" else ("video" if is_video else "file")))
        self.record_capture(url, cap_quality, cap_type, dl_id)
        if opts.get("cookies") and not is_incognito:
            self.__dict__.setdefault("_site_cookies", {})[dl_id] = opts["cookies"]
        if item["browserTransfer"]:
            item.update(status="downloading", phase="downloading", startedAt=time.time())
            item["segments"][0]["status"] = "downloading"
        elif opts.get("startImmediately", True):
            self.save_state()
            self.start_download(dl_id)
        else:
            # "Download later": waits for the scheduler (or a manual Resume)
            item["status"] = "scheduled"
            if needs_probe:
                threading.Thread(
                    target=self._async_probe_item,
                    args=(dl_id, None if is_incognito else opts.get("cookies")),
                    daemon=True,
                ).start()
            self.save_state()
        return item

    def _apply_probe_result_to_item(self, item: dict, p: dict):
        with self.lock:
            item.pop("_needsInitialProbe", None)
            if p.get("url"):
                item["url"] = p["url"]
            total_sz = int(p.get("totalSize") or 0)
            if total_sz > 0:
                item["totalSize"] = total_sz
            item["supportsRange"] = bool(p.get("supportsRange", False))
            if p.get("etag"):
                item["etag"] = p["etag"]
            if p.get("lastModified"):
                item["lastModified"] = p["lastModified"]
            item["validatorRecorded"] = bool(item.get("etag") or item.get("lastModified"))
            p_fn = sanitize_filename(p.get("filename") or "")
            if p_fn and p_fn.lower().endswith(".torrent"):
                item["isTorrent"] = True
                p_fn = p_fn[:-8] or "Torrent_Download"
            if p_fn and p_fn not in ("scorpion_file.bin", "download_file") and int(item.get("downloadedBytes") or 0) == 0:
                new_cat = p.get("category") or detect_category(p_fn)
                if not item.get("customSaveDir"):
                    item["category"] = new_cat
                    target_dir = p.get("saveDir") or os.path.join(self.settings["downloadsRoot"], new_cat)
                    os.makedirs(target_dir, exist_ok=True)
                    item["saveDir"] = target_dir
                else:
                    target_dir = item["saveDir"]
                new_fp = self._available_media_path(os.path.join(target_dir, p_fn), item["id"])
                item["filePath"] = new_fp
                item["filename"] = os.path.basename(new_fp)
                item["tempFilePath"] = os.path.join(self.get_item_temp_dir(item["id"]), item["filename"] + ".scorpion_part")
            if int(item.get("downloadedBytes") or 0) == 0:
                req_conns = int(item.get("connections") or self.settings.get("defaultConnections") or 32)
                if item.get("isTorrent"):
                    conn_count = max(16, min(64, req_conns))
                    item["supportsRange"] = True
                else:
                    conn_count = max(1, min(64, req_conns)) if (item["supportsRange"] and item["totalSize"] > 128 * 1024) else 1
                item["segments"] = self._create_segments(item["totalSize"], conn_count)

    def _async_probe_item(self, dl_id: str, cookies=None):
        with self.lock:
            item = self.downloads.get(dl_id)
            if not item or not item.get("_needsInitialProbe") or dl_id in self.controllers:
                return
        try:
            p = self.probe_url(item["url"], referer=item.get("referer") or "", cookies=cookies)
            with self.lock:
                # Starting a scheduled item claims its probe before creating download segments.
                if self.downloads.get(dl_id) is not item or not item.get("_needsInitialProbe") or dl_id in self.controllers:
                    return
                self._apply_probe_result_to_item(item, p)
                self.save_state()
        except Exception:
            pass

    def _probe_and_start_worker(self, item: dict, ctrl: dict):
        try:
            if not ctrl.get("aborted"):
                cookies = None if item.get("incognito") else self.__dict__.get("_site_cookies", {}).get(item["id"])
                try:
                    p = self.probe_url(item["url"], referer=item.get("referer") or "", cookies=cookies)
                    if not ctrl.get("aborted"):
                        self._apply_probe_result_to_item(item, p)
                except Exception:
                    with self.lock:
                        item.pop("_needsInitialProbe", None)
        finally:
            aborted = bool(ctrl.get("aborted"))
            with self.lock:
                if self.controllers.get(item["id"]) is ctrl:
                    self.controllers.pop(item["id"], None)
                if not aborted and item.get("status") == "downloading":
                    item["status"] = "paused"
            if not aborted:
                self.start_download(item["id"])

    def start_download(self, dl_id: str):
        with self.lock:
            item = self.downloads.get(dl_id)
            if not item or item["status"] == "completed" or dl_id in self.controllers:
                return
            if item.get("browserTransfer"):
                item.update(status="error", speed=0, errorMsg="الملف مرتبط بجلسة المتصفح. افتح الفيديو واضغط زر التنزيل مرة أخرى.")
                self.save_state()
                return
            # Download queue: respect the max number of simultaneous downloads
            if self.active_count() >= max(1, int(self.settings.get("maxConcurrent") or 4)):
                item["status"] = "queued"
                item["speed"] = 0
                self.save_state()
                return
            item["status"] = "downloading"
            item["errorMsg"] = ""
            item["startedAt"] = time.time()
            item.pop("finishedAt", None)

            if item.pop("_needsInitialProbe", False) and int(item.get("totalSize") or 0) <= 0 and not item.get("isVideo") and not item.get("isTorrent"):
                item["phase"] = "connecting"
                ctrl = {"aborted": False, "probing": True, "last_bytes": 0, "last_time": time.time(), "file_lock": threading.Lock()}
                self.controllers[dl_id] = ctrl
                self.save_state()
                threading.Thread(target=self._probe_and_start_worker, args=(item, ctrl), daemon=True).start()
                return

            if item.get("isTorrent") or self._is_torrent_source(item.get("url", ""), item):
                item["isTorrent"] = True
                ctrl = {"aborted": False, "isTorrent": True, "last_bytes": item["downloadedBytes"], "last_time": time.time(), "file_lock": threading.Lock()}
                self.controllers[dl_id] = ctrl
                self.save_state()
                threading.Thread(target=self._run_torrent_worker, args=(item, ctrl), daemon=True).start()
                return

            music_hosts = ("spotify.com", "soundcloud.com", "anghami.com", "deezer.com", "music.apple.com")
            u_host = (urllib.parse.urlparse(item.get("url") or "").hostname or "").lower()
            ref_host = (urllib.parse.urlparse(item.get("referer") or "").hostname or "").lower()
            is_music_host = any(
                h == d or h.endswith("." + d)
                for h in (u_host, ref_host)
                if h
                for d in music_hosts
            ) or ("widevine-license" in (item.get("url") or "").lower() and any(ref_host == d or ref_host.endswith("." + d) for d in music_hosts))
            if is_music_host:
                item["isVideo"] = True
                item["videoQuality"] = "audio"
                item["category"] = "Music"
                if item.get("downloadedBytes", 0) == 0 and not item.get("customSaveDir"):
                    music_dir = os.path.join(self.settings["downloadsRoot"], "Music")
                    os.makedirs(music_dir, exist_ok=True)
                    item["saveDir"] = music_dir
                    item["filePath"] = os.path.join(music_dir, item.get("filename") or "download.mp3")
                if any(x in (item.get("url") or "").lower() for x in ("widevine-license", "spclient.spotify.com", "/license")):
                    if item.get("referer"):
                        item["url"] = item["referer"]

            if item.get("isVideo"):
                ctrl = {"aborted": False, "last_bytes": item["downloadedBytes"], "last_time": time.time(), "file_lock": threading.Lock()}
                self.controllers[dl_id] = ctrl
                self.save_state()
                threading.Thread(target=self._run_video_worker_with_cookies, args=(item, ctrl), daemon=True).start()
                return

            os.makedirs(item["saveDir"], exist_ok=True)
            os.makedirs(os.path.dirname(item["tempFilePath"]), exist_ok=True)
            tmp_exists = os.path.exists(item["tempFilePath"])
            had_partial = tmp_exists and int(item.get("downloadedBytes") or 0) > 0
            need_reset = (not item.get("supportsRange", True)) or (not tmp_exists and item.get("downloadedBytes", 0) > 0)
            if need_reset:
                had_partial = False
                item["downloadedBytes"] = 0
                item["progress"] = 0.0
                for seg in item.get("segments") or []:
                    seg["currentByte"] = seg.get("startByte", 0)
                    seg["downloaded"] = 0
                mode = "w+b"
            else:
                mode = "r+b" if tmp_exists else "w+b"
            f_obj = open(item["tempFilePath"], mode)
            ctrl = {
                "aborted": False,
                "file": f_obj,
                "file_lock": threading.Lock(),
                "last_bytes": item["downloadedBytes"],
                "last_time": time.time(),
                "act_lock": threading.Lock(),
                "active": 0,
                "conn_limit": max(1, len(item["segments"])),
                "resumed_from_partial": had_partial,
            }
            self.controllers[dl_id] = ctrl

            segs_to_start = []
            for seg in item["segments"]:
                if seg["endByte"] == -1 or seg["currentByte"] <= seg["endByte"]:
                    seg["status"] = "downloading"
                    seg["info"] = "Connecting..."
                    segs_to_start.append(seg)
                else:
                    seg["status"] = "completed"
                    seg["info"] = "Complete"
            self.save_state()
        for seg in segs_to_start:
            threading.Thread(target=self._run_segment_worker, args=(item, seg, ctrl), daemon=True).start()

    def _global_budget_split(self) -> tuple:
        """Divide globalSpeedLimitKbps cleanly between active torrents (aria2c) and native/video/browser tasks."""
        global_limit = float(self.settings.get("globalSpeedLimitKbps") or 0)
        if global_limit <= 0:
            return 0.0, 0.0
        ctrls = dict(self.controllers or {})
        downloads = self.downloads or {}
        torrent_ids = []
        other_ids = []
        for did, c in ctrls.items():
            it = downloads.get(did) or {}
            if it.get("isTorrent") or (isinstance(c, dict) and c.get("isTorrent")):
                torrent_ids.append(did)
            else:
                other_ids.append(did)
        if not torrent_ids:
            return 0.0, global_limit
        total_active = max(1, len(torrent_ids) + len(other_ids))
        share = global_limit / float(total_active)
        reserved = 0.0
        for tid in torrent_ids:
            it_lim = float((downloads.get(tid) or {}).get("speedLimitKbps") or 0)
            reserved += min(share, it_lim) if it_lim > 0 else share
        if other_ids:
            non_torrent_budget = max(0.0, global_limit - reserved)
            if non_torrent_budget <= 0.0:
                non_torrent_budget = global_limit / float(total_active)
                share = max(0.0, (global_limit - non_torrent_budget) / max(1, len(torrent_ids)))
        else:
            non_torrent_budget = global_limit
        return share, non_torrent_budget

    def _consume_token_bucket(
        self, key: str, rate_bps: float, num_bytes: int, ctrl: dict = None, max_wait_s: float = None
    ) -> float:
        if rate_bps <= 0 or num_bytes <= 0:
            return 0.0
        buckets = self.__dict__.setdefault("_bw_buckets", {})
        bw_lock = self.__dict__.setdefault("_bw_lock", threading.Lock())
        max_burst = max(1024.0, min(rate_bps * 0.5, 256 * 1024.0))
        remaining = float(num_bytes)
        started_at = time.monotonic()
        while remaining > 0:
            if ctrl and ctrl.get("aborted"):
                return 0.0
            step = min(remaining, max_burst)
            with bw_lock:
                now = time.monotonic()
                b = buckets.get(key)
                if b is None:
                    b = {"tokens": max_burst, "ts": now}
                    buckets[key] = b
                elapsed = max(0.0, now - b["ts"])
                b["ts"] = now
                b["tokens"] = min(max_burst, b["tokens"] + elapsed * rate_bps)
                if b["tokens"] >= step:
                    b["tokens"] -= step
                    remaining -= step
                    continue
                deficit = step - b["tokens"]
                wait_s = min(0.05, max(0.005, deficit / rate_bps))
                if max_wait_s is not None and (now - started_at) + wait_s > max_wait_s:
                    unpaid = max(0.0, remaining - b["tokens"])
                    needed_s = unpaid / rate_bps
                    b["tokens"] = -unpaid
                    b["ts"] = now
                    return needed_s
            time.sleep(wait_s)
        return 0.0

    def consume_bandwidth(self, item: dict, num_bytes: int, ctrl: dict = None, max_wait_s: float = None) -> float:
        """Unified token-bucket limiter shared across direct, video, browser transfer, and torrent tasks."""
        if num_bytes <= 0:
            return 0.0
        extra_wait = 0.0
        item_limit = int(item.get("speedLimitKbps") or 0)
        if item_limit > 0:
            w_item = self._consume_token_bucket(
                f"item:{item.get('id', '')}", item_limit * 1024.0, num_bytes, ctrl, max_wait_s=max_wait_s
            )
            extra_wait = max(extra_wait, w_item)
        _tor_share, non_tor_kbps = self._global_budget_split()
        if non_tor_kbps > 0:
            w_glob = self._consume_token_bucket(
                "global", non_tor_kbps * 1024.0, num_bytes, ctrl, max_wait_s=max_wait_s
            )
            extra_wait = max(extra_wait, w_glob)
        return extra_wait

    def _throttle(self, item: dict, num_bytes: int = 65536, ctrl: dict = None):
        self.consume_bandwidth(item, num_bytes, ctrl)

    def _restart_single_connection(self, item: dict, ctrl: dict):
        """Server ignores Range requests or serves compressed 200 OK: restart over one plain connection."""
        with ctrl["act_lock"]:
            if ctrl.get("restarting"):
                return
            ctrl["restarting"] = True
        with ctrl["file_lock"]:
            ctrl["aborted"] = True
            try:
                ctrl["file"].close()
            except Exception:
                pass
        with self.lock:
            self.controllers.pop(item["id"], None)
            try:
                if os.path.exists(item["tempFilePath"]):
                    os.remove(item["tempFilePath"])
            except Exception:
                pass
            item["supportsRange"] = False
            item["totalSize"] = 0
            item["downloadedBytes"] = 0
            item["progress"] = 0.0
            item["segments"] = self._create_segments(0, 1)
            item["status"] = "paused"
            self.save_state()
        self.start_download(item["id"])

    def _restart_clean_from_source_change(self, item: dict, ctrl: dict, new_etag: str = "", new_lm: str = "", new_total: int = 0):
        """Restart cleanly from byte 0 when ETag/Last-Modified indicates the origin resource changed."""
        with ctrl["act_lock"]:
            if ctrl.get("restarting"):
                return
            ctrl["restarting"] = True
        with ctrl["file_lock"]:
            ctrl["aborted"] = True
            try:
                ctrl["file"].close()
            except Exception:
                pass
        with self.lock:
            self.controllers.pop(item["id"], None)
            try:
                if os.path.exists(item["tempFilePath"]):
                    os.remove(item["tempFilePath"])
            except Exception:
                pass
            if new_total > 0:
                item["totalSize"] = new_total
            clean_etag = "" if (new_etag or "").startswith("W/") else (new_etag or "").strip()
            item["etag"] = clean_etag
            item["lastModified"] = (new_lm or "").strip()
            item["validatorRecorded"] = bool(clean_etag or item["lastModified"])
            if (new_etag or "").startswith("W/"):
                item["supportsRange"] = False
            tot = int(item.get("totalSize") or 0)
            req_conns = int(item.get("connections") or self.settings.get("defaultConnections") or 32)
            conn_count = max(1, min(64, req_conns)) if (item.get("supportsRange", True) and tot > 128 * 1024) else 1
            item["downloadedBytes"] = 0
            item["progress"] = 0.0
            item["segments"] = self._create_segments(tot, conn_count)
            item["status"] = "paused"
            self.save_state()
        self.start_download(item["id"])

    def _abort_all_segments_with_error(self, item: dict, ctrl: dict, reason: str):
        with self.lock:
            self.controllers.pop(item["id"], None)
            ctrl["aborted"] = True
            try:
                if ctrl.get("file"):
                    ctrl["file"].close()
            except Exception:
                pass
            for s in item.get("segments") or []:
                if s.get("status") != "completed":
                    s["status"] = "error"
                    s["info"] = reason[:60]
            item["status"] = "error"
            item["speed"] = 0
            item["errorMsg"] = reason[:160]
            self.save_state()

    def _run_segment_worker(self, item: dict, seg: dict, ctrl: dict):
        """
        Downloads one byte range with strict Content-Range and resume-validator checks.
        """
        seg["status"] = "downloading"
        seg["info"] = "Receiving data..."
        max_attempts = 12
        attempt = 0
        try:
            while not ctrl["aborted"] and item["status"] == "downloading":
                while not ctrl["aborted"]:
                    with ctrl["act_lock"]:
                        if ctrl["active"] < ctrl["conn_limit"]:
                            ctrl["active"] += 1
                            break
                    seg["info"] = "Waiting for a free connection..."
                    time.sleep(0.4)
                if ctrl["aborted"]:
                    return

                retry_reason = None
                released = False
                try:
                    hdrs = self._build_media_headers(
                        item.get("referer") or "",
                        item.get("userAgent") or "",
                        item.get("acceptLanguage") or "",
                        default_ua=self.settings.get("userAgent") or BROWSER_UA,
                        include_origin=False,
                    )
                    req_start = seg["currentByte"]
                    req_end = seg["endByte"]
                    ranged = item["supportsRange"] and req_end >= req_start
                    hdrs["Accept-Encoding"] = "identity"
                    if ranged:
                        hdrs["Range"] = f"bytes={req_start}-{req_end}"
                        if req_start > 0 or ctrl.get("resumed_from_partial"):
                            if_etag = (item.get("etag") or "").strip()
                            if_lm = (item.get("lastModified") or "").strip()
                            if if_etag and not if_etag.startswith("W/"):
                                hdrs["If-Range"] = if_etag
                            elif if_lm:
                                hdrs["If-Range"] = if_lm
                    elif req_start > 0:
                        with ctrl["file_lock"]:
                            if ctrl["aborted"]:
                                return
                            ctrl["file"].seek(0)
                            ctrl["file"].truncate(0)
                            seg["currentByte"] = 0
                            seg["downloaded"] = 0
                            item["downloadedBytes"] = 0
                        req_start = 0

                    jar = None if item.get("incognito") else self._cookies_to_jar(self.__dict__.get("_site_cookies", {}).get(item["id"]))
                    with self._http_session(jar) as _sess:
                        with _sess.get(item["url"], headers=hdrs, stream=True, timeout=(15, 180), allow_redirects=True) as r:
                            if r.status_code in (429, 503, 509, 403, 500, 502, 504):
                                retry_reason = f"HTTP {r.status_code}"
                            elif r.status_code not in (200, 206):
                                seg["status"] = "error"
                                seg["info"] = f"HTTP {r.status_code}"
                                return
                            elif r.status_code == 200 and ranged and (req_start > 0 or len(item.get("segments") or []) > 1):
                                threading.Thread(target=self._restart_single_connection, args=(item, ctrl), daemon=True).start()
                                return
                            else:
                                if r.status_code == 200 and ranged:
                                    ranged = False
                                    item["supportsRange"] = False
                                    seg["endByte"] = -1
                                    req_end = -1
                                resp_hdrs = dict(r.headers)
                                srv_etag = (resp_hdrs.get("ETag") or resp_hdrs.get("etag") or "").strip()
                                srv_strong = "" if srv_etag.startswith("W/") else srv_etag
                                srv_lm = (resp_hdrs.get("Last-Modified") or resp_hdrs.get("last-modified") or "").strip()
                                resp_ce = (resp_hdrs.get("Content-Encoding") or resp_hdrs.get("content-encoding") or "").strip().lower()
                                if ranged and resp_ce not in ("", "identity"):
                                    threading.Thread(target=self._restart_single_connection, args=(item, ctrl), daemon=True).start()
                                    return

                                with self.lock:
                                    stored_etag = (item.get("etag") or "").strip()
                                    stored_strong = "" if stored_etag.startswith("W/") else stored_etag
                                    stored_lm = (item.get("lastModified") or "").strip()
                                    v_rec = bool(item.get("validatorRecorded"))
                                    mismatch = False
                                    if ctrl.get("resumed_from_partial"):
                                        if stored_strong:
                                            if srv_strong != stored_strong:
                                                mismatch = True
                                            elif stored_lm and srv_lm and srv_lm != stored_lm:
                                                mismatch = True
                                        elif stored_lm:
                                            if not srv_lm or srv_lm != stored_lm or srv_strong:
                                                mismatch = True
                                        else:
                                            mismatch = True
                                    else:
                                        if stored_strong and srv_strong != stored_strong:
                                            mismatch = True
                                        elif stored_lm and (not srv_lm or srv_lm != stored_lm):
                                            mismatch = True
                                        elif ranged and srv_etag.startswith("W/") and (req_start > 0 or len(item.get("segments") or []) > 1):
                                            mismatch = True
                                        elif not v_rec and (srv_strong or srv_lm):
                                            item["etag"] = srv_strong
                                            item["lastModified"] = srv_lm
                                            item["validatorRecorded"] = True
                                if mismatch:
                                    threading.Thread(
                                        target=self._restart_clean_from_source_change,
                                        args=(item, ctrl, srv_etag, srv_lm, int(item.get("totalSize") or 0) if (r.status_code == 206 or resp_ce in ("", "identity")) else 0),
                                        daemon=True,
                                    ).start()
                                    return

                                compressed_200 = (r.status_code == 200) and (resp_ce not in ("", "identity"))
                                compressed_wire_len = None
                                if compressed_200:
                                    item["supportsRange"] = False
                                    item["totalSize"] = 0
                                    seg["endByte"] = -1
                                    req_end = -1
                                    cl_comp = (resp_hdrs.get("Content-Length") or resp_hdrs.get("content-length") or "").strip()
                                    if cl_comp.isdigit() and int(cl_comp) > 0:
                                        compressed_wire_len = int(cl_comp)

                                if seg["id"] == 1 and seg["currentByte"] == 0 and r.status_code == 200:
                                    if not compressed_200:
                                        cl_disc = (resp_hdrs.get("Content-Length") or resp_hdrs.get("content-length") or "").strip()
                                        if cl_disc.isdigit() and int(cl_disc) > 0:
                                            item["totalSize"] = int(cl_disc)
                                            if len(item.get("segments") or []) == 1:
                                                seg["endByte"] = int(cl_disc) - 1
                                                req_end = seg["endByte"]
                                    better_name = extract_filename(r.url or item["url"], resp_hdrs)
                                    has_cd_name = "filename" in (resp_hdrs.get("Content-Disposition") or resp_hdrs.get("content-disposition") or "").lower()
                                    if better_name not in ("scorpion_file.bin", "download_file") and (
                                        not os.path.splitext(item.get("filename") or "")[1] or has_cd_name
                                    ):
                                        with self.lock:
                                            new_cat = detect_category(better_name, resp_hdrs.get("Content-Type") or "")
                                            if item.get("customSaveDir"):
                                                new_dir = item["saveDir"]
                                            else:
                                                new_dir = os.path.join(self.settings["downloadsRoot"], new_cat)
                                                os.makedirs(new_dir, exist_ok=True)
                                                item["category"] = new_cat
                                                item["saveDir"] = new_dir
                                            item["filePath"] = self._available_media_path(os.path.join(new_dir, better_name), item["id"])
                                            item["filename"] = os.path.basename(item["filePath"])

                                resp_end = req_end
                                expected_body_len = None
                                if r.status_code == 206 and ranged:
                                    cr_raw = (resp_hdrs.get("Content-Range") or resp_hdrs.get("content-range") or "").strip()
                                    m_cr = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+)", cr_raw, re.I)
                                    if not m_cr:
                                        self._abort_all_segments_with_error(item, ctrl, "The server returned an invalid byte range")
                                        return
                                    cr_start, cr_end, cr_total = map(int, m_cr.groups())
                                    known_total = int(item.get("totalSize") or 0)
                                    if (
                                        cr_start != req_start
                                        or cr_end < req_start
                                        or cr_end > req_end
                                        or cr_total <= 0
                                        or (known_total > 0 and cr_total != known_total)
                                    ):
                                        self._abort_all_segments_with_error(item, ctrl, "The server returned the wrong byte range")
                                        return
                                    if known_total <= 0:
                                        item["totalSize"] = cr_total
                                    resp_end = cr_end
                                    expected_body_len = cr_end - cr_start + 1
                                    cl_hdr = (resp_hdrs.get("Content-Length") or resp_hdrs.get("content-length") or "").strip()
                                    if cl_hdr.isdigit() and int(cl_hdr) != expected_body_len:
                                        self._abort_all_segments_with_error(item, ctrl, "The server returned the wrong byte range length")
                                        return
                                    if seg["id"] == 1 and req_start == 0:
                                        better_name = extract_filename(r.url or item["url"], resp_hdrs)
                                        has_cd_name = "filename" in (resp_hdrs.get("Content-Disposition") or resp_hdrs.get("content-disposition") or "").lower()
                                        if better_name not in ("scorpion_file.bin", "download_file") and (
                                            not os.path.splitext(item.get("filename") or "")[1] or has_cd_name
                                        ):
                                            with self.lock:
                                                new_cat = detect_category(better_name, resp_hdrs.get("Content-Type") or "")
                                                if item.get("customSaveDir"):
                                                    new_dir = item["saveDir"]
                                                else:
                                                    new_dir = os.path.join(self.settings["downloadsRoot"], new_cat)
                                                    os.makedirs(new_dir, exist_ok=True)
                                                    item["category"] = new_cat
                                                    item["saveDir"] = new_dir
                                                item["filePath"] = self._available_media_path(os.path.join(new_dir, better_name), item["id"])
                                                item["filename"] = os.path.basename(item["filePath"])
                                elif r.status_code == 200 and not compressed_200:
                                    cl_hdr = (resp_hdrs.get("Content-Length") or resp_hdrs.get("content-length") or "").strip()
                                    if cl_hdr.isdigit():
                                        expected_body_len = int(cl_hdr)

                                seg["info"] = "Receiving data..."
                                resp_read = 0
                                for chunk in r.iter_content(chunk_size=65536):
                                    if ctrl["aborted"] or item["status"] != "downloading":
                                        return
                                    if not chunk:
                                        continue
                                    with ctrl["file_lock"]:
                                        if ctrl["aborted"]:
                                            return
                                        to_write = len(chunk)
                                        if resp_end != -1:
                                            rem = resp_end - seg["currentByte"] + 1
                                            if rem <= 0:
                                                break
                                            to_write = min(to_write, rem)
                                        ctrl["file"].seek(seg["currentByte"])
                                        ctrl["file"].write(chunk[:to_write])
                                        seg["currentByte"] += to_write
                                        seg["downloaded"] += to_write
                                        item["downloadedBytes"] += to_write
                                        resp_read += to_write
                                    self.consume_bandwidth(item, to_write, ctrl)
                                    if resp_end != -1 and seg["currentByte"] > resp_end:
                                        break
                                exact_len_ok = (expected_body_len is None) or (resp_read == expected_body_len)
                                if exact_len_ok and compressed_wire_len is not None:
                                    try:
                                        raw_pos = r.raw.tell()
                                        if raw_pos > 0 and raw_pos != compressed_wire_len:
                                            exact_len_ok = False
                                    except Exception:
                                        pass
                                if not exact_len_ok:
                                    retry_reason = "Connection dropped"
                                elif seg["endByte"] == -1 or seg["currentByte"] > seg["endByte"]:
                                    if not ctrl["aborted"]:
                                        with ctrl["act_lock"]:
                                            ctrl["active"] = max(0, ctrl["active"] - 1)
                                        released = True
                                        self._on_segment_done(item, seg, ctrl)
                                    return
                                else:
                                    # Server returned a valid smaller prefix sub-range: continue immediately without counting a failure
                                    attempt = 0
                                    continue
                except Exception as e:
                    retry_reason = str(e)[:45]
                finally:
                    if not released:
                        with ctrl["act_lock"]:
                            ctrl["active"] = max(0, ctrl["active"] - 1)

                if ctrl["aborted"]:
                    return
                attempt += 1
                if attempt > max_attempts:
                    seg["status"] = "error"
                    seg["info"] = retry_reason or "Connection error"
                    return
                # Too many parallel connections? Lower the shared limit (never below 2)
                with ctrl["act_lock"]:
                    ctrl["conn_limit"] = max(2, min(ctrl["conn_limit"], ctrl["active"] + 1) - 1)
                seg["info"] = f"Retry {attempt}/{max_attempts} ({retry_reason}) — limit {ctrl['conn_limit']}"
                time.sleep(min(6.0, 0.6 * attempt))
        finally:
            self._check_all_failed(item, ctrl)

    def _check_all_failed(self, item: dict, ctrl: dict):
        """If no segment is still running and some failed, mark the whole download as error."""
        if ctrl.get("aborted") or item.get("status") != "downloading":
            return
        segs = item.get("segments") or []
        if any(s.get("status") == "downloading" for s in segs):
            return
        failed = [s for s in segs if s.get("status") == "error"]
        if failed:
            self.controllers.pop(item["id"], None)
            ctrl["aborted"] = True
            try:
                ctrl["file"].close()
            except Exception:
                pass
            item["status"] = "error"
            item["speed"] = 0
            item["errorMsg"] = failed[0].get("info", "Connection error")
            self.save_state()

    def _on_segment_done(self, item: dict, completed_seg: dict, ctrl: dict):
        with ctrl["file_lock"]:
            completed_seg["status"] = "completed"
            completed_seg["info"] = "Complete"

            # IDM Dynamic Work Stealing
            if item["supportsRange"] and item["totalSize"] > 0 and not ctrl["aborted"]:
                largest = None
                max_rem = 0
                for cand in item["segments"]:
                    if cand["status"] == "downloading" and cand["endByte"] > cand["currentByte"]:
                        rem = cand["endByte"] - cand["currentByte"] + 1
                        if rem > max_rem:
                            max_rem = rem
                            largest = cand
                if largest and max_rem >= 1024 * 1024:
                    half = max_rem // 2
                    new_start = largest["currentByte"] + half
                    old_end = largest["endByte"]
                    if new_start < old_end:
                        largest["endByte"] = new_start - 1
                        largest["info"] = f"Split -> Helping #{completed_seg['id']}"
                        completed_seg["startByte"] = new_start
                        completed_seg["currentByte"] = new_start
                        completed_seg["endByte"] = old_end
                        completed_seg["status"] = "downloading"
                        completed_seg["info"] = f"Helping #{largest['id']} (Work Steal)"
                        threading.Thread(target=self._run_segment_worker, args=(item, completed_seg, ctrl), daemon=True).start()
                        return

            if all(s["status"] == "completed" for s in item["segments"]):
                self._finalize(item, ctrl)

    def _scrape_media_urls(self, page_url: str, referer: str = "") -> list:
        """Fetch an embed/player page and pull out .m3u8 / .mp4 links (incl. escaped JSON)."""
        import re

        hdrs = {"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9,ar;q=0.8"}
        tls_ydl = getattr(self.__dict__.get("_scrape_tls"), "ydl", None)
        if isinstance(getattr(tls_ydl, "params", None), dict) and isinstance(tls_ydl.params.get("http_headers"), dict):
            ydl_hdrs = tls_ydl.params["http_headers"]
            if ydl_hdrs.get("User-Agent"):
                hdrs["User-Agent"] = str(ydl_hdrs["User-Agent"])
            if ydl_hdrs.get("Accept-Language"):
                hdrs["Accept-Language"] = str(ydl_hdrs["Accept-Language"])
        if referer:
            hdrs["Referer"] = referer
        cookiejar = getattr(tls_ydl, "cookiejar", None)
        req_cookies = cookiejar if isinstance(cookiejar, http.cookiejar.CookieJar) else None
        try:
            with self._http_session(req_cookies) as _sess:
                html = _sess.get(page_url, headers=hdrs, timeout=15).text
        except Exception:
            return []
        html = html.replace("\\/", "/").replace("\\u002F", "/").replace("&amp;", "&")
        # Many embed hosts hide the player config in P.A.C.K.E.R-packed JS: unpack it first
        if "eval(function(p,a,c,k,e,d)" in html:
            try:
                from yt_dlp.utils import decode_packed_codes

                for block in re.findall(r"eval\(function\(p,a,c,k,e,d\).*?\.split\('\|'\)[^)]*\)\)", html, re.S):
                    try:
                        html += "\n" + decode_packed_codes(block).replace("\\/", "/")
                    except Exception:
                        pass
            except Exception:
                pass
        # Some embed hosts obfuscate source URLs with base64 literals inside atob("...")
        for b64 in re.findall(r'atob\(\s*["\']([A-Za-z0-9+/=]{24,})["\']\s*\)', html):
            try:
                decoded = base64.b64decode(b64).decode("utf-8", errors="ignore").replace("\\/", "/")
                if decoded:
                    html += "\n" + decoded
            except Exception:
                pass
        found = re.findall(
            r"""https?://[^\s"'<>\\]+?\.(?:m3u8|mpd|mp4|webm|m4a|mp3|ogg|opus|flac|wav)(?:\?[^\s"'<>\\]*)?""",
            html,
            re.I,
        )
        # relative manifest/media paths like file:"/hls/xyz/master.m3u8"
        for rel in re.findall(r"""["'](/[^"'\s]+?\.(?:m3u8|mpd|mp4|m4a|mp3|ogg)(?:\?[^"'\s]*)?)["']""", html, re.I):
            found.append(urllib.parse.urljoin(page_url, rel))
        uniq = []
        for u in found:
            if u not in uniq and not re.search(r"\.(jpg|png|gif)\b", u, re.I):
                uniq.append(u)
        uniq.sort(key=lambda u: (0 if ".m3u8" in u.lower() else 1, 0 if "master" in u.lower() else 1))
        return uniq[:6]

    def _extract_from_player_frame(self, ydl, item: dict, unwrap):
        """Yields (stream, info) for the stream in the player config of the iframe the video plays in."""
        ref_page = (item.get("referer") or "").strip()
        url_page = (item.get("url") or "").strip()
        tab_url = (item.get("tabUrl") or "").strip()
        if not tab_url.lower().startswith(("http://", "https://")):
            return
        same = lambda a, b: a.split("#")[0] == b.split("#")[0]
        # Only the frame document itself (the extension sends the frame's own address as referer, and puts it
        # in url or candidates). A post link found in a feed is not a frame and may list other videos.
        allowed = [url_page] + [c.strip() for c in (item.get("candidates") or []) if isinstance(c, str)]
        if not ref_page.lower().startswith(("http://", "https://")) or same(ref_page, tab_url):
            return
        if not any(same(ref_page, c) for c in allowed if c):
            return
        frame_page = ref_page

        tab = urllib.parse.urlparse(tab_url)
        referers = [tab_url] + ([f"{tab.scheme}://{tab.netloc}/"] if f"{tab.scheme}://{tab.netloc}/" != tab_url else [])
        tls = self.__dict__.setdefault("_scrape_tls", threading.local())
        pf = urllib.parse.urlparse(frame_page)
        frame_origin = f"{pf.scheme}://{pf.netloc}" if pf.scheme and pf.netloc else ""
        has_params = isinstance(getattr(ydl, "params", None), dict)
        had_hdrs = has_params and ("http_headers" in ydl.params)
        orig_hdrs = ydl.params.get("http_headers") if has_params else None

        for ref in referers:
            tls.ydl = ydl
            try:
                streams = [u for u in self._scrape_media_urls(frame_page, ref)
                           if not fragment_url(u) and not browser_local_url(u)]
            finally:
                tls.ydl = None
            for stream in streams:
                if has_params:
                    new_hdrs = dict(orig_hdrs or {})
                    new_hdrs["Referer"] = frame_page
                    if frame_origin:
                        new_hdrs["Origin"] = frame_origin
                    ydl.params["http_headers"] = (
                        type(orig_hdrs)(new_hdrs)
                        if isinstance(orig_hdrs, dict) and type(orig_hdrs) is not dict
                        else new_hdrs
                    )
                try:
                    info = unwrap(ydl.extract_info(stream, download=False))
                except Exception:
                    continue
                if isinstance(info, dict) and (info.get("formats") or info.get("url")):
                    item["referer"] = frame_page
                    yield stream, info
                    return
            if has_params:
                if had_hdrs:
                    ydl.params["http_headers"] = orig_hdrs
                else:
                    ydl.params.pop("http_headers", None)
            if streams:
                return  # the page answered with a player; another Referer will not change its streams

    def _build_audio_search_query(self, item: dict) -> str:
        """Build a clean track search query from filename, title, or page metadata for audio fallback."""
        import html as html_mod
        import re

        raw = os.path.splitext(item.get("filename") or "")[0]
        raw = re.sub(
            r"\s*[\|\-–—•·]\s*(?:Spotify|SoundCloud|Anghami|Deezer|Apple\s*Music|YouTube\s*Music|YouTube|Web\s*Player).*$",
            "",
            raw,
            flags=re.I,
        )
        raw = re.sub(r"^(?:Stream|Listen\s+to|Play)\s+", "", raw, flags=re.I)
        raw = re.sub(r"\s+on\s+(?:Spotify|SoundCloud|Anghami|Deezer|Apple\s*Music).*$", "", raw, flags=re.I)
        raw = re.sub(r"^\(\d+\)\s*", "", raw)
        raw = re.sub(r"\s*\(\d+\)$", "", raw)
        raw = re.sub(r"[•·|_+\ufffd]+", " ", raw)
        raw = re.sub(r"\s+", " ", raw).strip(" -–—.")

        generic_names = {
            "",
            "discover",
            "stream",
            "license",
            "audio",
            "video",
            "scorpion audio",
            "scorpion video",
            "spotify",
            "soundcloud",
            "apple music",
            "deezer",
            "anghami",
            "youtube music",
            "web player",
            "you",
            "search",
        }
        u_hint = ((item.get("url") or "") + " " + (item.get("referer") or "")).lower()
        is_music_url = any(d in u_hint for d in ("spotify.com", "soundcloud.com", "anghami.com", "deezer.com", "music.apple.com"))
        is_opaque_id = is_music_url and bool(re.fullmatch(r"[A-Za-z0-9_-]{12,}|[0-9]+", raw))
        if raw.lower() not in generic_names and len(raw) >= 3 and not is_opaque_id:
            return raw

        for page_url in (item.get("url") or "", item.get("referer") or ""):
            if not page_url.startswith(("http://", "https://")):
                continue
            if any(x in page_url.lower() for x in ("widevine", "spclient.spotify.com", "/license")):
                continue
            try:
                resp = requests.get(page_url, headers={"User-Agent": BROWSER_UA}, timeout=10)
                html_txt = resp.text
                m_og = (
                    re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_txt, re.I)
                    or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title["\']', html_txt, re.I)
                )
                m_desc = (
                    re.search(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_txt, re.I)
                    or re.search(r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:description["\']', html_txt, re.I)
                )
                if m_og:
                    title_part = html_mod.unescape(m_og.group(1)).strip()
                    artist_part = ""
                    if m_desc:
                        desc = html_mod.unescape(m_desc.group(1)).strip()
                        artist_part = desc.split("·")[0].split("•")[0].strip()
                    q_str = (
                        f"{title_part} {artist_part}".strip()
                        if artist_part and artist_part.lower() not in title_part.lower()
                        else title_part
                    )
                    if q_str and q_str.lower() not in generic_names:
                        return q_str
                m_t = re.search(r"<title[^>]*>(.*?)</title>", html_txt, re.I | re.S)
                if m_t:
                    t_txt = re.sub(r"\s+", " ", html_mod.unescape(m_t.group(1))).strip()
                    t_txt = re.sub(
                        r"\s*[\|\-–—•·]\s*(?:Spotify|SoundCloud|Anghami|Deezer|Apple\s*Music|YouTube).*$",
                        "",
                        t_txt,
                        flags=re.I,
                    )
                    if t_txt and t_txt.lower() not in generic_names:
                        return t_txt
            except Exception:
                pass

        return "" if is_opaque_id else raw

    def _extract_with_fallback(self, ydl, item: dict):
        """Try yt-dlp on the URL; for DRM/music sites or unsupported pages, fall back to audio search or stream scraping."""
        u_low = (item.get("url") or "").lower().strip()
        # Telegram Web addresses are virtual service-worker routes. Generic extraction can return
        # the site's three-second animation, which is not the user's video.
        if urllib.parse.urlparse(u_low).hostname == "web.telegram.org" or browser_local_url(u_low):
            raise RuntimeError("فيديو تليجرام مرتبط بجلسة المتصفح. حدّث الإضافة وافتح الفيديو ثم اضغط زر التنزيل فوقه.")
        if is_drm_video_url(u_low) or is_drm_video_url(item.get("referer") or "") or is_drm_video_url(item.get("tabUrl") or ""):
            raise RuntimeError("هذا المحتوى محمي بتشفير DRM (مثل Netflix / Shahid) ولا يدعم التنزيل الخارجي. استخدم ميزة التنزيل داخل التطبيق الرسمي للمنصة.")
        u_clean = u_low.split("?")[0].rstrip("/")
        is_audio = item.get("videoQuality") == "audio" or item.get("category") == "Music"
        strict_target = bool(item.get("strictTarget", False))

        def _unwrap_info(info_obj):
            if isinstance(info_obj, dict) and info_obj.get("entries"):
                if strict_target:
                    entries = (entry for entry in info_obj["entries"] if entry)
                    first = next(entries, None)
                    if next(entries, None) is not None:
                        raise RuntimeError("العنوان يحتوي على عدة فيديوهات. افتح الفيديو المطلوب وحده ثم أعد المحاولة.")
                    return first
                entries = [e for e in info_obj["entries"] if e]
                if entries:
                    return entries[0]
            return info_obj

        def _extract_via_audio_search():
            query = self._build_audio_search_query(item)
            if not query:
                return None
            orig_hdrs = ydl.params.get("http_headers")
            saved_hdrs = dict(orig_hdrs or {})
            saved_cookiefile = ydl.params.pop("cookiefile", None)
            saved_cookies = []
            try:
                saved_cookies = list(ydl.cookiejar)
            except Exception:
                saved_cookies = []
            try:
                if getattr(ydl, "cookiejar", None) is not None:
                    ydl.cookiejar.clear()
            except Exception:
                pass
            try:
                clean_dict = {k: v for k, v in saved_hdrs.items() if k.lower() not in ("referer", "origin")}
                clean_hdrs = type(orig_hdrs)(clean_dict) if isinstance(orig_hdrs, dict) and type(orig_hdrs) is not dict else clean_dict
                ydl.params["http_headers"] = clean_hdrs
                res = _unwrap_info(ydl.extract_info(f"ytsearch1:{query}", download=False))
                if res:
                    item["_fromAudioSearch"] = True
                    item["referer"] = ""
                    if isinstance(res, dict) and res.get("webpage_url"):
                        item["url"] = res["webpage_url"]
                    return res
            except Exception:
                pass
            if saved_cookiefile is not None:
                ydl.params["cookiefile"] = saved_cookiefile
            # The search failed: later fallbacks still need the site's sign-in cookies
            for cookie in saved_cookies:
                try:
                    ydl.cookiejar.set_cookie(cookie)
                except Exception:
                    pass
            ydl.params["http_headers"] = orig_hdrs if orig_hdrs is not None else saved_hdrs
            return None

        if strict_target:
            # These addresses were identified for one particular media element. A feed, parent tab,
            # general page scrape, or audio search can resolve to a different video and is unsafe here.
            tried = set()
            first_err = None
            for target in [item.get("url") or ""] + list(item.get("candidates") or []):
                if not isinstance(target, str):
                    continue
                target = target.strip()
                if not target.lower().startswith(("http://", "https://")) or target in tried:
                    continue
                tried.add(target)
                if fragment_url(target) or browser_local_url(target) or urllib.parse.urlparse(target).hostname == "web.telegram.org":
                    continue
                try:
                    info = _unwrap_info(ydl.extract_info(target, download=False))
                    if isinstance(info, dict) and (info.get("formats") or info.get("url")):
                        item["url"] = target
                        return info
                except Exception as err:
                    if first_err is None or needs_login(err):
                        first_err = err
            if first_err is not None and needs_login(first_err):
                raise first_err
            # An embedded player's own page (the iframe) holds only that player, so the stream named in its
            # player config is the selected video. Such pages usually refuse to load without the parent
            # page as Referer ("embeds disabled"), exactly as the browser loaded them.
            for frame_page, info in self._extract_from_player_frame(ydl, item, _unwrap_info):
                item["url"] = frame_page
                return info
            # The user only sees the generic message: keep the extractor's real reason for diagnosis
            if first_err is not None and hasattr(self, "record_diagnostic"):
                self.record_diagnostic("extract_failed", f"{item.get('url') or ''} :: {first_err}")
            raise RuntimeError("تعذر تنزيل الفيديو المحدد. أعد فتح الفيديو واضغط زر التنزيل فوقه.") from first_err

        drm_music_domains = ("spotify.com", "anghami.com", "deezer.com", "music.apple.com", "widevine-license")
        sc_generic_paths = (
            "https://soundcloud.com",
            "https://soundcloud.com/discover",
            "https://soundcloud.com/stream",
            "https://soundcloud.com/you",
            "https://soundcloud.com/search",
            "https://m.soundcloud.com",
            "https://m.soundcloud.com/discover",
        )

        def _is_generic_music_url(u: str) -> bool:
            ul = (u or "").lower().strip()
            uc = ul.split("?")[0].rstrip("/")
            return any(d in ul for d in drm_music_domains) or uc in sc_generic_paths

        if is_audio and _is_generic_music_url(u_low):
            for alt in list(item.get("candidates") or []):
                alt = (alt or "").strip() if isinstance(alt, str) else ""
                if (
                    not alt.lower().startswith(("http://", "https://"))
                    or _is_generic_music_url(alt)
                    or fragment_url(alt)
                    or browser_local_url(alt)
                    or urllib.parse.urlparse(alt).hostname == "web.telegram.org"
                ):
                    continue
                try:
                    cand_info = _unwrap_info(ydl.extract_info(alt, download=False))
                    if cand_info and (cand_info.get("formats") or cand_info.get("url")):
                        item["url"] = alt
                        return cand_info
                except Exception:
                    pass
            found_info = _extract_via_audio_search()
            if found_info:
                return found_info

        try:
            if fragment_url(item["url"]):
                raise RuntimeError("الرابط يخص جزءًا من البث. استخدم رابط الفيديو أو قائمة البث الكاملة.")
            return _unwrap_info(ydl.extract_info(item["url"], download=False))
        except Exception as first_err:
            # The first address may not identify the video (a feed, a profile, an embedded player): try the
            # others the browser saw (post links near the video, the tab, streams the player loaded) in order
            tried = {item["url"]}
            for alt in [item.get("tabUrl") or ""] + list(item.get("candidates") or []):
                alt = (alt or "").strip() if isinstance(alt, str) else ""
                if not alt.lower().startswith(("http://", "https://")) or alt in tried:
                    continue
                if (
                    _is_generic_music_url(alt)
                    or fragment_url(alt)
                    or browser_local_url(alt)
                    or urllib.parse.urlparse(alt).hostname == "web.telegram.org"
                ):
                    continue
                tried.add(alt)
                try:
                    info = _unwrap_info(ydl.extract_info(alt, download=False))
                    if info and (info.get("formats") or info.get("url")):
                        item["url"] = alt
                        return info
                except Exception as alt_err:
                    if needs_login(alt_err):
                        first_err = alt_err  # the most useful reason to show
            if is_audio:
                found_info = _extract_via_audio_search()
                if found_info:
                    return found_info
            if needs_login(first_err):
                raise first_err
            if not item["url"].lower().split("?")[0].endswith((".html", ".htm", "/")) and "unsupported url" not in str(first_err).lower():
                raise
            tls = self.__dict__.setdefault("_scrape_tls", threading.local())
            tls.ydl = ydl
            try:
                scraped_cands = self._scrape_media_urls(item["url"], item.get("referer") or item["url"])
            finally:
                tls.ydl = None
            for cand in scraped_cands:
                if fragment_url(cand) or browser_local_url(cand):
                    continue
                try:
                    info = _unwrap_info(ydl.extract_info(cand, download=False))
                    item["url"] = cand
                    return info
                except Exception:
                    continue
            raise RuntimeError(
                "ما قدرناش نلاقي الفيديو في الصفحة دي. لو الموقع بيطلب تسجيل دخول، سجّل دخول في Chrome. "
                "ولو الصفحة فيها فيديوهات كتير، شغّل الفيديو نفسه لثواني واضغط زر التحميل اللي فوقه."
            ) from first_err

    def _available_media_path(self, path: str, dl_id: str) -> str:
        base, ext = os.path.splitext(path)
        # Snapshot under the lock: a finishing transfer must never fail because a download was added meanwhile
        with self.lock:
            reserved = {os.path.normcase(it.get("filePath") or "") for it in list(self.downloads.values())
                        if it.get("id") != dl_id}
        result, index = path, 1
        while os.path.exists(result) or os.path.normcase(result) in reserved:
            result = f"{base} ({index}){ext}"
            index += 1
        return result

    def _validate_video_output(self, path: str, item: dict, expected_duration=0, expect_audio=False, audio_only=None):
        if audio_only is None:
            audio_only = (
                item.get("videoQuality") == "audio"
                or item.get("category") == "Music"
                or os.path.splitext(path or "")[1].lower() in CATEGORY_MAP["Music"]
            )
        target_dur = (
            finite_duration(expected_duration)
            if item.get("_fromAudioSearch")
            else max(finite_duration(item.get("expectedDuration")), finite_duration(expected_duration))
        )
        return validate_media(path, find_tool("ffprobe"), target_dur, bool(audio_only), expect_audio)

    def _has_video_stream(self, path: str):
        """True/False from ffprobe; None when it can't tell (no ffprobe, unreadable file)."""
        ffprobe = find_tool("ffprobe")
        if not ffprobe:
            return None
        try:
            out = subprocess.run(
                [ffprobe, "-v", "error", "-select_streams", "v", "-show_entries", "stream=codec_type", "-of", "csv=p=0", path],
                capture_output=True, text=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            return None
        if out.returncode != 0:
            # Not a playable media file at all (e.g. a fragment of a site's interface sound) also has no video
            err = (out.stderr or "").lower()
            return False if ("invalid data" in err or "moov atom not found" in err) else None
        return "video" in out.stdout

    def _write_cookiefile(self, cookies: list, key: str) -> str:
        """The browser's cookies for the video's site, so sign-in-only videos download like in the browser."""
        if not cookies:
            return ""
        path = os.path.join(self.temp_root, f"cookies_{key}.txt")
        now = time.time()
        try:
            os.makedirs(self.temp_root, exist_ok=True)
            lines = ["# Netscape HTTP Cookie File"]
            for c in cookies:
                domain = str(c.get("domain") or "").strip()
                name = str(c.get("name") or "")
                if not domain or not name:
                    continue
                exp = c.get("expirationDate")
                if exp is not None:
                    try:
                        exp_f = float(exp)
                        if exp_f > 0 and exp_f <= now:
                            continue
                    except (TypeError, ValueError):
                        exp_f = 0.0
                else:
                    exp_f = 0.0
                host_only = bool(c.get("hostOnly"))
                include_sub = "FALSE" if host_only else "TRUE"
                if host_only:
                    domain = domain.lstrip(".")
                elif not domain.startswith("."):
                    domain = "." + domain
                lines.append("\t".join([
                    domain, include_sub, str(c.get("path") or "/"), "TRUE" if c.get("secure") else "FALSE",
                    str(int(exp_f)), name, str(c.get("value") or ""),
                ]))
            if len(lines) <= 1:
                return ""
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            return path
        except Exception:
            return ""

    def _run_video_worker_with_cookies(self, item: dict, ctrl: dict):
        cookies = self.__dict__.get("_site_cookies", {}).get(item["id"])
        item["_cookiefile"] = self._write_cookiefile(cookies, item["id"]) if cookies else ""
        try:
            self._run_video_worker(item, ctrl)
        finally:
            cf = item.pop("_cookiefile", "")
            if cf:
                try:
                    os.remove(cf)
                except OSError:
                    pass

    def _js_runtime_opts(self) -> dict:
        """YouTube needs a JavaScript runtime: the bundled QuickJS, or deno if this PC has it (about 3x faster)."""
        qjs_bundled = os.path.join(TOOLS_DIR, "qjs.exe")
        deno_bin = find_tool("deno")
        js_runtime = (
            {"quickjs": {"path": qjs_bundled}} if os.path.isfile(qjs_bundled) and not deno_bin
            else {"deno": {"path": deno_bin}} if deno_bin
            else {"quickjs": {"path": find_tool("qjs")}} if find_tool("qjs")
            else None
        )
        if not js_runtime:
            return {}
        opts = {"js_runtimes": js_runtime}
        try:
            import yt_dlp_ejs  # noqa: F401  (challenge scripts bundled with the app)
        except ImportError:
            opts["remote_components"] = ["ejs:github"]
        return opts

    def list_video_qualities(self, url: str, referer: str = "", tab_url: str = "", candidates=None, cookies=None,
                             strict_target: bool = False, user_agent: str = "", accept_language: str = "") -> dict:
        """
        Every video quality a page offers (as yt-dlp sees it), for the quality pickers in the browser
        button and the Add Download dialog. Cached for a few minutes per address.
        """
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")) or not HAS_YTDLP:
            return {"ok": False, "qualities": []}
        cache = self.__dict__.setdefault("_quality_cache", {})
        candidate_urls = [candidate for candidate in (candidates or []) if isinstance(candidate, str)][:10]
        auth_scope = "anon"
        if cookies:
            now_ts = time.time()
            norm_cookies = []
            for ck in (cookies if isinstance(cookies, (list, tuple)) else []):
                if not isinstance(ck, dict) or not ck.get("name"):
                    continue
                try:
                    exp_f = float(ck.get("expirationDate") or 0)
                except (TypeError, ValueError):
                    exp_f = 0.0
                if exp_f > 0 and exp_f <= now_ts:
                    continue
                norm_cookies.append((
                    str(ck.get("domain") or "").lower(),
                    str(ck.get("path") or "/"),
                    str(ck.get("name") or ""),
                    str(ck.get("value") or ""),
                    bool(ck.get("secure", False)),
                    bool(ck.get("hostOnly", False)),
                ))
            if norm_cookies:
                norm_cookies.sort()
                raw_fp = json.dumps(norm_cookies, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
                auth_scope = "auth:" + hashlib.sha256(raw_fp).hexdigest()
        base_key = (url, bool(strict_target), tuple(candidate_urls) if strict_target else ())
        cache_key = (*base_key, auth_scope)
        hit = cache.get(cache_key)
        if hit and time.time() - hit[0] < 600:
            return hit[1]

        class _Quiet:
            def debug(self, msg):
                pass

            info = warning = error = debug

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                "logger": _Quiet()}
        opts.update(self._js_runtime_opts())
        opts["http_headers"] = self._build_media_headers(referer, user_agent, accept_language)
        item = {"url": url, "referer": referer, "tabUrl": tab_url, "candidates": candidate_urls,
                "strictTarget": bool(strict_target), "userAgent": user_agent, "acceptLanguage": accept_language,
                "videoQuality": "best", "category": ""}
        cookiefile = self._write_cookiefile(cookies, f"q{uuid.uuid4().hex[:8]}") if cookies else ""
        if cookiefile:
            opts["cookiefile"] = cookiefile
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = self._extract_with_fallback(ydl, item)
        finally:
            if cookiefile:
                try:
                    os.remove(cookiefile)
                except OSError:
                    pass
        info = info or {}
        best_audio = max(
            (f for f in info.get("formats") or [] if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none")),
            key=lambda f: f.get("abr") or 0, default=None,
        )
        audio_size = (best_audio or {}).get("filesize") or (best_audio or {}).get("filesize_approx") or 0
        by_height = {}
        for f in info.get("formats") or []:
            h = f.get("height")
            if not h or f.get("vcodec") == "none":
                continue
            size = f.get("filesize") or f.get("filesize_approx") or 0
            if size and f.get("acodec") in (None, "none"):
                size += audio_size  # video-only stream: the saved file also holds the audio
            cur = by_height.setdefault(h, {"height": h, "fps": 0, "size": 0})
            cur["fps"] = max(cur["fps"], int(f.get("fps") or 0))
            cur["size"] = max(cur["size"], int(size or 0))
        qualities = []
        for h in sorted(by_height, reverse=True):
            q = by_height[h]
            tag = {4320: "8K", 2160: "4K", 1440: "2K", 1080: "Full HD", 720: "HD"}.get(h, "")
            q["label"] = f"{h}p{q['fps'] if q['fps'] > 30 else ''}" + (f" {tag}" if tag else "")
            q["quality"] = f"{h}p"
            qualities.append(q)
        res = {
            "ok": True,
            "title": info.get("title") or "",
            "duration": info.get("duration") or 0,
            "pageUrl": item["url"],
            "qualities": qualities,
            "hasAudio": bool(best_audio) or any(f.get("acodec") not in (None, "none") for f in info.get("formats") or []),
        }
        if res.get("ok") and res.get("qualities"):
            cache[cache_key] = (time.time(), res)
        return res

    def get_item_temp_dir(self, dl_id: str) -> str:
        d = os.path.join(self.temp_root, str(dl_id))
        os.makedirs(d, exist_ok=True)
        return d

    def _cleanup_item_temp(self, item: dict):
        if not item:
            return
        temp_root_raw = os.path.abspath(self.temp_root)
        temp_root_abs = os.path.normcase(temp_root_raw)
        dl_id = item.get("id")
        if dl_id:
            dl_dir_raw = os.path.abspath(os.path.join(temp_root_raw, str(dl_id)))
            dl_dir = os.path.normcase(dl_dir_raw)
            try:
                if os.path.commonpath([temp_root_abs, dl_dir]) == temp_root_abs and dl_dir != temp_root_abs:
                    shutil.rmtree(dl_dir_raw, ignore_errors=True)
            except Exception:
                pass
        tp = item.get("tempFilePath")
        if tp and os.path.exists(tp):
            try:
                tp_raw = os.path.abspath(tp)
                tp_abs = os.path.normcase(tp_raw)
                if os.path.commonpath([temp_root_abs, tp_abs]) == temp_root_abs:
                    os.remove(tp_raw)
            except Exception:
                pass

    def _probe_video_stream_meta(self, url: str, headers: dict, fallback_size: int = 0, cookies=None) -> tuple:
        """Verify HTTP 206 Range support and return (exact_size, supports_range, strong_etag, last_modified, raw_etag)."""
        try:
            h = dict(headers or {})
            h["Range"] = "bytes=0-0"
            h["Accept-Encoding"] = "identity"
            with self._http_session(cookies) as _sess:
                r = _sess.get(url, headers=h, stream=True, timeout=10, allow_redirects=True)
                status = r.status_code
                cr = r.headers.get("Content-Range", "")
                cl = r.headers.get("Content-Length", "")
                raw_etag = (r.headers.get("ETag") or "").strip()
                last_mod = (r.headers.get("Last-Modified") or "").strip()
                r.close()
            strong_etag = "" if (not raw_etag or raw_etag[:2].upper() == "W/") else raw_etag
            match = re.fullmatch(r"bytes 0-0/(\d+)", cr.strip())
            if status == 206 and match and int(match[1]) > 0:
                return int(match[1]), True, strong_etag, last_mod, raw_etag
            if status == 200 and cl.isdigit() and int(cl) > 0:
                return int(cl), False, strong_etag, last_mod, raw_etag
        except Exception:
            pass
        return fallback_size, False, "", "", ""

    def _probe_video_stream_range(self, url: str, headers: dict, fallback_size: int = 0, cookies=None) -> tuple:
        """Verify HTTP 206 Range support and return (exact_size, supports_range) for a video stream."""
        sz, ok, _et, _lm, _raw = self._probe_video_stream_meta(url, headers, fallback_size, cookies)
        return sz, ok

    def _alloc_video_segments(self, stream_specs: list, port_alloc: list):
        """Create empty part files and split each stream into byte-range segments. Returns None on failure."""
        new_segs = []
        global_offset = 0
        seg_id = 1
        try:
            for s_spec, n_ports in zip(stream_specs, port_alloc):
                os.makedirs(os.path.dirname(s_spec["partPath"]), exist_ok=True)
                with open(s_spec["partPath"], "wb") as f_init:
                    f_init.truncate(s_spec["size"])
                s_spec["fh"] = open(s_spec["partPath"], "r+b")
                sz = s_spec["size"]
                chunk_sz = sz // n_ports
                for p_i in range(n_ports):
                    loc_start = p_i * chunk_sz
                    loc_end = (sz - 1) if (p_i == n_ports - 1) else ((p_i + 1) * chunk_sz - 1)
                    new_segs.append({
                        "id": seg_id,
                        "label": f"{s_spec['kind']} {L('#' + str(seg_id))}",
                        "size": max(0, loc_end - loc_start + 1),
                        "downloaded": 0,
                        "startByte": global_offset + loc_start,
                        "endByte": global_offset + loc_end,
                        "currentByte": global_offset + loc_start,
                        "localStart": loc_start,
                        "localEnd": loc_end,
                        "localCur": loc_start,
                        "streamIdx": s_spec["idx"],
                        "status": "downloading",
                        "info": f"Active (Port #{seg_id})",
                    })
                    seg_id += 1
                global_offset += sz
            return new_segs
        except Exception:
            for sp in stream_specs:
                try:
                    if sp.get("fh"):
                        sp["fh"].close()
                except Exception:
                    pass
            return None

    def _download_video_streams_16ports(
        self,
        item: dict,
        ctrl: dict,
        reqs: list,
        base_no_ext: str,
        ffmpeg_bin: str,
        has_ffmpeg: bool,
        q: str,
        cookiejar=None,
    ) -> bool:
        """
        Downloads direct HTTP/HTTPS video (and audio) streams using Scorpion's 16-port
        parallel HTTP Range engine, then merges/converts via FFmpeg if needed.
        Returns True if handled, or False if the stream is HLS/DASH and should use 16-port fragment engine.
        """
        if not reqs or len(reqs) > 2:
            return False
        if len(reqs) > 1 and not has_ffmpeg:
            return False

        stream_specs = []
        for idx, f in enumerate(reqs):
            s_url = (f.get("url") or "").strip()
            proto = (f.get("protocol") or "https").lower()
            if not s_url.startswith(("http://", "https://")):
                return False
            if proto not in ("http", "https") or f.get("fragments") or ".m3u8" in s_url.lower() or ".mpd" in s_url.lower():
                return False

            is_yt = "googlevideo.com" in s_url.lower()
            hdrs = self._build_media_headers(
                "" if is_yt else (item.get("referer") or ""),
                item.get("userAgent") or "",
                item.get("acceptLanguage") or "",
            )
            if isinstance(f.get("http_headers"), dict):
                hdrs.update(f["http_headers"])

            approx = int(f.get("filesize") or f.get("filesize_approx") or 0)
            exact_sz, ok_range, strong_etag, last_mod, raw_etag = self._probe_video_stream_meta(s_url, hdrs, approx, cookiejar)
            if not ok_range or exact_sz <= 0:
                return False
            # Independent range requests cannot establish a single entity without a
            # comparable validator. Let the single-stream extractor handle this source.
            if not strong_etag and (raw_etag or not last_mod):
                return False

            vcodec, acodec = f.get("vcodec"), f.get("acodec")
            height = f.get("height")
            res = f" {height}p" if height else ""
            is_ar = self.settings.get("lang", "ar") == "ar"
            if vcodec == "none":
                kind = "صوت" if is_ar else "Audio"
            elif acodec == "none":
                kind = ("فيديو" if is_ar else "Video") + res
            else:
                kind = ("فيديو" if is_ar else "Video") + res

            ext = (f.get("ext") or "mp4").lower()
            item_temp_dir = self.get_item_temp_dir(item["id"])
            part_path = os.path.join(item_temp_dir, f"stream{idx}.{ext}.part")
            stream_specs.append({
                "idx": idx,
                "url": s_url,
                "headers": hdrs,
                "size": exact_sz,
                "etag": strong_etag,
                "rawEtag": raw_etag,
                "lastModified": last_mod,
                "kind": kind,
                "ext": ext,
                "partPath": part_path,
                "lock": threading.Lock(),
                "fh": None,
            })

        total_ports = max(8, int(item.get("connections") or self.settings.get("defaultConnections") or 16))
        if len(stream_specs) == 1:
            port_alloc = [total_ports]
        else:
            audio_ports = max(2, total_ports // 8)
            port_alloc = [max(4, total_ports - audio_ports), audio_ports]

        def _pair_validator_matches(sp: dict, sv_etag: str, sv_lm: str) -> bool:
            if (sp.get("rawEtag") or "")[:2].upper() == "W/":
                return False
            if not sv_etag and not sv_lm:
                return False
            if sv_etag:
                return bool(sp.get("etag") and sp["etag"] == sv_etag)
            if sp.get("rawEtag"):
                return False
            return bool(sp.get("lastModified") and sp["lastModified"] == sv_lm)

        def _validators_match() -> bool:
            saved_vals = item.get("videoValidators")
            if isinstance(saved_vals, list) and len(saved_vals) == len(stream_specs):
                for sp, sv in zip(stream_specs, saved_vals):
                    if not isinstance(sv, dict):
                        return False
                    if not _pair_validator_matches(
                        sp,
                        (sv.get("etag") or "").strip(),
                        (sv.get("lastModified") or "").strip(),
                    ):
                        return False
                return True
            if len(stream_specs) == 1 and ((item.get("etag") or "").strip() or (item.get("lastModified") or "").strip()):
                return _pair_validator_matches(
                    stream_specs[0],
                    (item.get("etag") or "").strip(),
                    (item.get("lastModified") or "").strip(),
                )
            return False

        # Resume support: reuse the previous layout only when validators, sizes, and part files match
        layout_sig = [[sp["idx"], sp["size"], n] for sp, n in zip(stream_specs, port_alloc)]
        prev_segs = item.get("segments") or []
        can_resume = (
            item.get("videoLayout") == layout_sig
            and _validators_match()
            and prev_segs
            and all("streamIdx" in s and "localCur" in s for s in prev_segs)
            and all(
                os.path.isfile(sp["partPath"]) and os.path.getsize(sp["partPath"]) == sp["size"]
                for sp in stream_specs
            )
        )
        if can_resume:
            try:
                for sp in stream_specs:
                    sp["fh"] = open(sp["partPath"], "r+b")
            except Exception:
                can_resume = False
        if can_resume:
            for s in prev_segs:
                done = s["localCur"] > s["localEnd"]
                s["status"] = "completed" if done else "downloading"
                s["info"] = "Complete" if done else "Resuming..."
            item["totalSize"] = sum(sp["size"] for sp in stream_specs)
            item["downloadedBytes"] = sum(int(s.get("downloaded") or 0) for s in prev_segs)
            item["supportsRange"] = True
            item["useRangeVideoEngine"] = True
            item["phase"] = "downloading"
            ctrl["last_bytes"] = item["downloadedBytes"]
            ctrl["last_time"] = time.time()
            ctrl["video_stream_files"] = [sp["fh"] for sp in stream_specs]
            new_segs = prev_segs
        else:
            new_segs = None

        # Pre-allocate part files and build byte-range segments (fresh start)
        if new_segs is None:
            new_segs = self._alloc_video_segments(stream_specs, port_alloc)
            if new_segs is None:
                return False
            item["segments"] = new_segs
            item["videoLayout"] = layout_sig
            item["videoValidators"] = [{"etag": sp["etag"], "lastModified": sp["lastModified"]} for sp in stream_specs]
            if len(stream_specs) == 1:
                item["etag"] = stream_specs[0]["etag"]
                item["lastModified"] = stream_specs[0]["lastModified"]
            item["totalSize"] = sum(sp["size"] for sp in stream_specs)
            item["downloadedBytes"] = 0
            item["supportsRange"] = True
            item["useRangeVideoEngine"] = True
            item["phase"] = "downloading"
            ctrl["last_bytes"] = 0
            ctrl["last_time"] = time.time()
            ctrl["video_stream_files"] = [sp["fh"] for sp in stream_specs]
            self.save_state()

        entity_mismatch = threading.Event()

        def port_worker(seg: dict, sp: dict):
            is_yt_cdn = "googlevideo.com" in sp["url"].lower()
            block_size = 4 * 1024 * 1024  # 4 MB range blocks bypass YouTube single-stream throttling
            retries = 0
            while seg["localCur"] <= seg["localEnd"] and not ctrl["aborted"] and not entity_mismatch.is_set():
                req_start = seg["localCur"]
                req_end = min(seg["localEnd"], req_start + block_size - 1) if is_yt_cdn else seg["localEnd"]
                hdrs = dict(sp["headers"])
                hdrs["Range"] = f"bytes={req_start}-{req_end}"
                hdrs["Accept-Encoding"] = "identity"
                try:
                    with self._http_session(cookiejar) as _sess:
                        with _sess.get(sp["url"], headers=hdrs, stream=True, timeout=20, allow_redirects=True) as resp:
                            content_range = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)", resp.headers.get("Content-Range", "").strip())
                            if resp.status_code != 206 or not content_range or tuple(map(int, content_range.groups())) != (req_start, req_end, sp["size"]):
                                raise RuntimeError("The server returned the wrong byte range")
                            resp_etag = (resp.headers.get("ETag") or "").strip()
                            resp_lm = (resp.headers.get("Last-Modified") or "").strip()
                            if (sp.get("etag") and resp_etag != sp["etag"]) or (
                                not sp.get("etag") and sp.get("lastModified") and resp_lm != sp["lastModified"]
                            ):
                                entity_mismatch.set()
                                seg["status"] = "error"
                                seg["info"] = "Entity changed"
                                return
                            before = seg["localCur"]
                            for chunk in resp.iter_content(chunk_size=65536):
                                if ctrl["aborted"]:
                                    return
                                if not chunk:
                                    continue
                                rem = req_end - seg["localCur"] + 1
                                if rem <= 0:
                                    break
                                to_write = min(len(chunk), rem)
                                with sp["lock"]:
                                    if ctrl["aborted"]:
                                        return
                                    sp["fh"].seek(seg["localCur"])
                                    sp["fh"].write(chunk[:to_write])
                                    seg["localCur"] += to_write
                                    seg["currentByte"] += to_write
                                    seg["downloaded"] += to_write
                                    item["downloadedBytes"] += to_write
                                self.consume_bandwidth(item, to_write, ctrl)
                                if seg["localCur"] > req_end:
                                    break
                    if seg["localCur"] == before:
                        raise RuntimeError("The server returned an empty video range")
                    retries = 0
                except Exception as e:
                    if ctrl["aborted"]:
                        return
                    retries += 1
                    if retries > 6:
                        seg["status"] = "error"
                        seg["info"] = str(e)[:40]
                        return
                    time.sleep(min(2.0, 0.3 * retries))

            if not ctrl["aborted"] and seg["localCur"] > seg["localEnd"]:
                seg["status"] = "completed"
                seg["info"] = "Complete"

        threads = []
        for seg in new_segs:
            sp = stream_specs[seg["streamIdx"]]
            t = threading.Thread(target=port_worker, args=(seg, sp), daemon=True)
            t.start()
            threads.append(t)

        for t in threads:
            t.join()

        for sp in stream_specs:
            try:
                if sp["fh"]:
                    sp["fh"].close()
            except Exception:
                pass

        if ctrl["aborted"]:
            return True

        if entity_mismatch.is_set() or any(s["status"] != "completed" for s in new_segs):
            # Clean up partial files and fall back to yt-dlp if any range worker failed permanently
            for sp in stream_specs:
                try:
                    if os.path.exists(sp["partPath"]):
                        os.remove(sp["partPath"])
                except Exception:
                    pass
            item["downloadedBytes"] = 0
            item.pop("videoValidators", None)
            item.pop("videoLayout", None)
            item["useRangeVideoEngine"] = False
            return False

        # Merge / finalize output
        item["phase"] = "merging"
        item["speed"] = 0
        no_win = 0x08000000 if os.name == "nt" else 0
        if len(stream_specs) == 2 and has_ffmpeg:
            final_out = base_no_ext + ".mp4"
            merge_result = subprocess.run(
                [
                    ffmpeg_bin, "-y",
                    "-i", stream_specs[0]["partPath"],
                    "-i", stream_specs[1]["partPath"],
                    "-c", "copy", "-movflags", "+faststart",
                    final_out,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=no_win,
                check=False,
            )
            if merge_result.returncode != 0:
                raise RuntimeError("فشل دمج الصوت والصورة. لم يتم اعتماد الفيديو كتحميل مكتمل.")
            for sp in stream_specs:
                try:
                    os.remove(sp["partPath"])
                except Exception:
                    pass
            if os.path.exists(final_out):
                item["_videoOutput"] = final_out
                item["totalSize"] = os.path.getsize(final_out)
                item["downloadedBytes"] = item["totalSize"]
        else:
            sp0 = stream_specs[0]
            if q == "audio" and has_ffmpeg:
                final_out = base_no_ext + ".mp3"
                conversion_result = subprocess.run(
                    [ffmpeg_bin, "-y", "-i", sp0["partPath"], "-vn", "-ab", "192k", final_out],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=no_win,
                    check=False,
                )
                if conversion_result.returncode != 0:
                    raise RuntimeError("فشل تحويل الصوت. لم يتم اعتماد الملف كتحميل مكتمل.")
                try:
                    os.remove(sp0["partPath"])
                except Exception:
                    pass
            else:
                out_ext = f".{sp0['ext']}"
                final_out = base_no_ext + out_ext
                if os.path.exists(final_out):
                    try:
                        os.remove(final_out)
                    except Exception:
                        pass
                shutil.move(sp0["partPath"], final_out)
            if os.path.exists(final_out):
                item["_videoOutput"] = final_out
                item["totalSize"] = os.path.getsize(final_out)
                item["downloadedBytes"] = item["totalSize"]

        item["useRangeVideoEngine"] = False
        return True

    def _run_video_worker(self, item: dict, ctrl: dict):
        if not HAS_YTDLP:
            item["status"] = "error"
            item["errorMsg"] = "yt-dlp غير مثبت / yt-dlp is not installed"
            return

        item["phase"] = "connecting"
        item["errorMsg"] = ""
        item["useRangeVideoEngine"] = False
        if item.get("segments"):
            item["segments"][0]["status"] = "downloading"
            item["segments"][0]["info"] = "Extracting streams..."

        q = item.get("videoQuality", "best")
        ffmpeg_bin = find_tool("ffmpeg")
        has_ffmpeg = bool(ffmpeg_bin)
        fmt = video_format_for(q, has_ffmpeg)

        class QuietYtdlpLogger:
            def debug(self, msg):
                pass

            def info(self, msg):
                pass

            def warning(self, msg):
                pass

            def error(self, msg):
                pass

        n_ports = max(8, int(item.get("connections") or self.settings.get("defaultConnections") or 16))
        is_audio_frag = q == "audio" or item.get("category") == "Music"
        frag_ports = min(6, n_ports) if is_audio_frag else min(16, n_ports)

        def update_16_virtual_ports(dl_b: int, tot_b: int, frag_idx: int = 0, frag_cnt: int = 0):
            segs = item.get("segments") or []
            if not segs:
                return
            n = len(segs)
            if tot_b <= 0 and frag_cnt > 0 and dl_b > 0 and frag_idx > 0:
                tot_b = int(dl_b * (frag_cnt / max(1, frag_idx)))
            if tot_b > 0:
                item["totalSize"] = tot_b
                per_seg = max(1, tot_b // n)
                # Distribute downloaded bytes across the 16 concurrent fragment ports
                pct = min(1.0, dl_b / max(1, tot_b))
                for idx_s, s in enumerate(segs):
                    st = idx_s * per_seg
                    en = (tot_b - 1) if (idx_s == n - 1) else ((idx_s + 1) * per_seg - 1)
                    sz_s = max(1, en - st + 1)
                    s["startByte"] = st
                    s["endByte"] = en
                    s["size"] = sz_s
                    s_dl = min(sz_s, int(sz_s * pct))
                    s["downloaded"] = s_dl
                    s["currentByte"] = st + s_dl
                    s["status"] = "completed" if s_dl >= sz_s else "downloading"

        hook_state = {"last_dl": 0}

        def hook(d):
            if ctrl["aborted"]:
                raise RuntimeError("Paused")
            segs = item.get("segments") or []
            if not segs:
                return
            if d["status"] == "downloading":
                item["phase"] = "downloading"
                dl_b = int(d.get("downloaded_bytes") or 0)
                delta = max(0, dl_b - hook_state["last_dl"])
                hook_state["last_dl"] = dl_b
                if delta > 0:
                    self.consume_bandwidth(item, delta, ctrl)
                tot_b = int(d.get("total_bytes") or d.get("total_bytes_estimate") or 0)
                frag_idx = int(d.get("fragment_index") or 0)
                frag_cnt = int(d.get("fragment_count") or 0)
                update_16_virtual_ports(dl_b, tot_b, frag_idx, frag_cnt)
                total = item["totalSize"]
                item["downloadedBytes"] = dl_b
                if total > 0:
                    item["progress"] = min(99.9, round(dl_b / total * 100, 2))
                elif frag_idx and frag_cnt:
                    item["progress"] = min(99.9, round(frag_idx / max(1, frag_cnt) * 100, 2))
                spd = int(d.get("speed") or 0)
                item["speed"] = spd
                remaining = max(0, total - dl_b)
                item["timeLeft"] = int(remaining / spd) if (spd > 0 and total > 0) else d.get("eta")
                item["speedHistory"] = (item.get("speedHistory") or [])[-59:] + [spd]
            elif d["status"] == "finished":
                for s in segs:
                    if s.get("size"):
                        s["downloaded"] = s["size"]
                    s["status"] = "completed"
                item["phase"] = "merging"
                item["speed"] = 0

        base_no_ext = os.path.splitext(item["filePath"])[0]
        item_temp_dir = self.get_item_temp_dir(item["id"])
        temp_base = os.path.join(item_temp_dir, "video_out")
        outtmpl = temp_base + ".%(ext)s"

        ydl_opts = {
            "format": fmt,
            "outtmpl": outtmpl,
            "paths": {"home": item_temp_dir, "temp": item_temp_dir},
            "noplaylist": True,
            "continuedl": True,
            "hls_prefer_native": True,
            "retries": 10,
            "fragment_retries": 10,
            "skip_unavailable_fragments": False,
            "socket_timeout": 30,
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "concurrent_fragment_downloads": frag_ports,
            "logger": QuietYtdlpLogger(),
        }
        if item.get("_cookiefile"):
            ydl_opts["cookiefile"] = item["_cookiefile"]
        ydl_opts["http_headers"] = self._build_media_headers(
            item.get("referer") or "",
            item.get("userAgent") or "",
            item.get("acceptLanguage") or "",
        )
        ydl_opts.update(self._js_runtime_opts())
        if has_ffmpeg:
            # The folder, so yt-dlp also finds ffprobe (needed for MP3 conversion)
            ydl_opts["ffmpeg_location"] = os.path.dirname(ffmpeg_bin)
            if q == "audio":
                ydl_opts["postprocessors"] = [
                    {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
                ]
            else:
                ydl_opts["merge_output_format"] = "mp4"
        else:
            ydl_opts["extractor_args"] = {"youtube": {"player_client": ["android", "ios", "web"]}}

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                # 1) Extract streams first
                info = self._extract_with_fallback(ydl, item)
                if not isinstance(info, dict):
                    raise RuntimeError("تعذر استخراج بيانات الفيديو.")
                if ctrl["aborted"]:
                    return
                if re.fullmatch(r"Scorpion_(?:Video|Audio)(?:\s*\(\d+\))?", os.path.splitext(item.get("filename") or "")[0], re.I):
                    raw_title = (info.get("title") or "").strip()
                    if (
                        raw_title
                        and raw_title.lower() not in {"video", "audio", "master", "index", "playlist", "stream", "playback"}
                        and not re.match(r"^index[-_]", raw_title, re.I)
                    ):
                        clean_stem = sanitize_filename(raw_title)
                        if clean_stem and clean_stem not in ("download_file", "scorpion_download.bin"):
                            cur_ext = os.path.splitext(item.get("filename") or "")[1] or (".mp3" if q == "audio" else ".mp4")
                            save_dir = item.get("saveDir") or os.path.dirname(item["filePath"])
                            new_fp = self._available_media_path(os.path.join(save_dir, clean_stem + cur_ext), item["id"])
                            with self.lock:
                                item["filePath"] = new_fp
                                item["filename"] = os.path.basename(new_fp)
                            base_no_ext = os.path.splitext(new_fp)[0]
                reqs = info.get("requested_formats") or [info]

                # 2) Try Scorpion's 16-port HTTP Range Video Engine first (for YouTube / MP4 streams)
                handled_by_16_ports = self._download_video_streams_16ports(
                    item, ctrl, reqs, temp_base, ffmpeg_bin, has_ffmpeg, q, ydl.cookiejar
                )
                if ctrl["aborted"]:
                    return

                # 3) If HLS (.m3u8) / DASH (.mpd), run yt-dlp with 16 parallel fragment ports
                if not handled_by_16_ports:
                    is_ar = self.settings.get("lang", "ar") == "ar"
                    kind_lbl = "بورت فيديو" if is_ar else "Video Port"
                    tot_est = sum(int(f.get("filesize") or f.get("filesize_approx") or 0) for f in reqs)
                    per_p = max(1, tot_est // frag_ports) if tot_est > 0 else 0
                    item["segments"] = [
                        {
                            "id": i,
                            "formatId": "",
                            "label": f"{kind_lbl} {L('#' + str(i))}",
                            "size": per_p,
                            "downloaded": 0,
                            "startByte": (i - 1) * per_p,
                            "endByte": (i * per_p - 1) if per_p else -1,
                            "currentByte": (i - 1) * per_p,
                            "status": "downloading",
                            "info": f"Port #{i}",
                        }
                        for i in range(1, frag_ports + 1)
                    ]
                    item["totalSize"] = tot_est
                    item["supportsRange"] = True
                    item["phase"] = "downloading"

                    info = ydl.process_ie_result(info, download=True)
                    actual_temp = ydl.prepare_filename(info)
                    chosen_ext = os.path.splitext(actual_temp)[1] or ".mp4"
                    for cand_ext in (
                        ".mp3", ".mp4", ".m4a", ".ogg", ".opus", ".wav", ".flac",
                        ".aac", ".wma", ".amr", ".m4b", ".weba", ".aiff", ".mkv", ".webm",
                    ):
                        cand_temp = temp_base + cand_ext
                        if os.path.exists(cand_temp):
                            actual_temp = cand_temp
                            chosen_ext = cand_ext
                            break
                    if not os.path.isfile(actual_temp):
                        raise RuntimeError("لم ينتج التنزيل ملف فيديو. أعد المحاولة من المشغّل.")
                    item["_videoOutput"] = actual_temp

            fp = item.pop("_videoOutput", "")
            streams_are_audio_only = bool(reqs) and all(f.get("vcodec") in (None, "none") for f in reqs)
            is_audio_dl = (
                q == "audio"
                or item.get("category") == "Music"
                or streams_are_audio_only
                or os.path.splitext(fp or "")[1].lower() in CATEGORY_MAP["Music"]
            )
            expect_audio = not is_audio_dl and any(f.get("acodec") not in (None, "none") for f in reqs)
            item["phase"] = "verifying"
            item["actualDuration"] = self._validate_video_output(
                fp, item, info.get("duration"), expect_audio, audio_only=is_audio_dl
            )
            if ctrl["aborted"]:
                return
            item["phase"] = "saving"
            final_dest = self._available_media_path(base_no_ext + os.path.splitext(fp)[1], item["id"])
            os.makedirs(os.path.dirname(final_dest), exist_ok=True)
            # Publish only after validation, and never overwrite a previous or concurrent download.
            shutil.move(fp, final_dest)
            item["filePath"] = final_dest
            item["filename"] = os.path.basename(final_dest)
            item["totalSize"] = os.path.getsize(final_dest)
            item["downloadedBytes"] = item["totalSize"]
            self._cleanup_item_temp(item)
            for s in item.get("segments") or []:
                s["status"] = "completed"
                if s.get("size"):
                    s["downloaded"] = s["size"]
                s["currentByte"] = s.get("endByte", 0) + 1
            item["phase"] = "done"
            item["finishedAt"] = time.time()
            item["progress"] = 100.0
            item["speed"] = 0
            item["timeLeft"] = 0
            item["status"] = "completed"
            self.controllers.pop(item["id"], None)
            self.save_state()
            self.signals.completed.emit(item["id"])
        except Exception as err:
            item.pop("_videoOutput", None)
            item["filePath"] = base_no_ext + os.path.splitext(item["filename"])[1]
            item["useRangeVideoEngine"] = False
            with self.lock:
                self.controllers.pop(item["id"], None)
            if not ctrl["aborted"]:
                # Clean stale partial video_out.* files so manual retries do not resume corrupt data
                try:
                    for fn in os.listdir(item_temp_dir):
                        if fn.startswith("video_out"):
                            os.remove(os.path.join(item_temp_dir, fn))
                except Exception:
                    pass
                msg = friendly_video_error(err)
                item["status"] = "error"
                item["errorMsg"] = msg[:160]
                item["speed"] = 0
                for s in item.get("segments") or []:
                    if s.get("status") != "completed":
                        s["status"] = "error"
                        s["info"] = msg[:60]
                self.save_state()

    def _run_torrent_worker(self, item: dict, ctrl: dict):
        aria2_bin = self._find_aria2c()
        if not aria2_bin:
            self.controllers.pop(item["id"], None)
            item["status"] = "error"
            item["errorMsg"] = "aria2c torrent engine not found"
            self.save_state()
            return

        item["phase"] = "connecting"
        item["errorMsg"] = ""
        item["supportsRange"] = True
        is_ar = self.settings.get("lang", "ar") == "ar"
        n_ports = max(16, int(item.get("connections") or self.settings.get("defaultConnections") or 32))
        port_lbl = "بورت تورنت" if is_ar else "Torrent Port"

        item["segments"] = [
            {
                "id": i,
                "label": f"{port_lbl} {L('#' + str(i))}",
                "size": 0,
                "downloaded": 0,
                "startByte": 0,
                "endByte": -1,
                "currentByte": 0,
                "status": "downloading",
                "info": "Connecting DHT / Peers...",
            }
            for i in range(1, n_ports + 1)
        ]

        # Pick a free localhost port for aria2c JSON-RPC
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            rpc_port = s.getsockname()[1]

        rpc_url = f"http://127.0.0.1:{rpc_port}/jsonrpc"
        item_temp_dir = self.get_item_temp_dir(item["id"])
        # Torrent data is written to the hidden temp folder and moved to the save folder only when complete
        bt_dir = os.path.join(item_temp_dir, "bt")
        os.makedirs(bt_dir, exist_ok=True)
        os.makedirs(item["saveDir"], exist_ok=True)

        bt_trackers = ",".join([
            "udp://tracker.opentrackr.org:1337/announce",
            "udp://open.stealth.si:80/announce",
            "udp://tracker.torrent.eu.org:451/announce",
            "udp://exodus.desync.com:6969/announce",
            "udp://tracker.openbittorrent.com:6969/announce",
            "http://tracker.opentrackr.org:1337/announce",
        ])

        cmd = [
            aria2_bin,
            "--enable-rpc=true",
            f"--rpc-listen-port={rpc_port}",
            "--rpc-listen-all=false",
            f"--dir={bt_dir}",
            "--continue=true",
            "--pause-metadata=true",
            "--bt-enable-lpd=true",
            "--enable-dht=true",
            "--enable-peer-exchange=true",
            "--bt-max-peers=128",
            f"--max-connection-per-server=16",
            f"--split={n_ports}",
            "--seed-time=0",
            "--file-allocation=none",
            "--allow-overwrite=true",
            "--auto-file-renaming=false",
            f"--bt-tracker={bt_trackers}",
            "--quiet=true",
        ]
        if item.get("speedLimitKbps") and int(item["speedLimitKbps"]) > 0:
            cmd.append(f"--max-overall-download-limit={int(item['speedLimitKbps'])}K")

        no_win = 0x08000000 if os.name == "nt" else 0
        proc = None
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=no_win,
            )
            ctrl["aria2_proc"] = proc
            ctrl["aria2_rpc"] = rpc_url

            def rpc_call(method: str, params: list):
                r = requests.post(
                    rpc_url,
                    json={"jsonrpc": "2.0", "id": "sc", "method": method, "params": params},
                    timeout=3.0,
                )
                return r.json().get("result")

            # Wait for RPC server to come online
            ready = False
            for _ in range(25):
                if ctrl["aborted"]:
                    return
                try:
                    if rpc_call("aria2.getVersion", []):
                        ready = True
                        break
                except Exception:
                    time.sleep(0.15)
            if not ready:
                raise RuntimeError("Failed to start BitTorrent RPC engine")

            # Add .torrent or magnet URI
            src = item["url"].strip()
            torrent_bytes = None
            if os.path.isfile(src) and src.lower().endswith(".torrent"):
                with open(src, "rb") as tf:
                    torrent_bytes = tf.read()
            elif src.lower().startswith(("http://", "https://")) and src.lower().split("?")[0].endswith(".torrent"):
                hdrs = {"User-Agent": BROWSER_UA}
                if item.get("referer"):
                    hdrs["Referer"] = item["referer"]
                resp = requests.get(src, headers=hdrs, timeout=15, allow_redirects=True)
                if resp.url.lower().startswith("magnet:?"):
                    src = resp.url
                elif resp.status_code == 200 and resp.content:
                    torrent_bytes = resp.content

            if torrent_bytes:
                b64_tor = base64.b64encode(torrent_bytes).decode("ascii")
                # Start paused so the user can pick files of multi-file torrents before any data is fetched
                gid = rpc_call("aria2.addTorrent", [b64_tor, [], {"dir": bt_dir, "pause": "true"}])
            else:
                gid = rpc_call("aria2.addUri", [[src], {"dir": bt_dir}])

            if not gid:
                raise RuntimeError("Could not register torrent download")

            files_resolved = False
            def effective_limit_bps() -> int:
                per_item = float(item.get("speedLimitKbps") or 0)
                shared_glob, _ = self._global_budget_split()
                lims = [x for x in (per_item, shared_glob) if x > 0]
                return max(1, int(round(min(lims) * 1024.0))) if lims else 0

            last_limit = -1
            while not ctrl["aborted"]:
                time.sleep(0.35)
                if ctrl["aborted"]:
                    break

                cur_limit = effective_limit_bps()
                if cur_limit != last_limit:
                    last_limit = cur_limit
                    try:
                        rpc_call(
                            "aria2.changeGlobalOption",
                            [{"max-overall-download-limit": str(cur_limit) if cur_limit > 0 else "0"}],
                        )
                    except Exception:
                        pass

                st_obj = rpc_call(
                    "aria2.tellStatus",
                    [
                        gid,
                        [
                            "status",
                            "totalLength",
                            "completedLength",
                            "downloadSpeed",
                            "numSeeders",
                            "connections",
                            "bitfield",
                            "files",
                            "bittorrent",
                            "errorMessage",
                            "followedBy",
                        ],
                    ],
                )
                if not st_obj:
                    continue

                # Follow magnet metadata -> actual torrent download GID
                followed = st_obj.get("followedBy")
                if followed and isinstance(followed, list) and followed[0]:
                    gid = followed[0]
                    ctrl["aria2_gid"] = gid
                    continue

                ctrl["aria2_gid"] = gid
                ctrl["aria2_rpc_call"] = rpc_call
                st = st_obj.get("status", "active")
                tot_b = int(st_obj.get("totalLength") or 0)
                dl_b = int(st_obj.get("completedLength") or 0)
                spd = int(st_obj.get("downloadSpeed") or 0)
                peers = int(st_obj.get("connections") or 0)
                seeders = int(st_obj.get("numSeeders") or 0)
                item["torrentPeers"] = peers
                item["torrentSeeders"] = seeders
                bt_info = (st_obj.get("bittorrent") or {}).get("info") or {}
                bt_name = bt_info.get("name")
                is_metadata_phase = (not bt_info) and tot_b < 256 * 1024 and src.lower().startswith("magnet:?")

                if bt_name and bt_name != item.get("filename"):
                    clean_bt_name = sanitize_filename(bt_name)
                    if clean_bt_name:
                        item["filename"] = clean_bt_name
                        item["filePath"] = os.path.join(item["saveDir"], clean_bt_name)

                # File selection for multi-file torrents (download is paused until resolved)
                if not files_resolved and bt_info and st == "paused":
                    files = st_obj.get("files") or []
                    selection = item.get("torrentSelection")
                    if len(files) > 1 and not selection:
                        item["phase"] = "selecting"
                        item["torrentFiles"] = [
                            {
                                "index": int(f_.get("index") or 0),
                                "path": os.path.relpath(f_.get("path") or "", bt_dir) if f_.get("path") else "",
                                "length": int(f_.get("length") or 0),
                            }
                            for f_ in files
                        ]
                        self.signals.torrent_files_ready.emit(item["id"])
                        while not ctrl["aborted"] and not item.get("torrentSelection"):
                            time.sleep(0.25)
                        if ctrl["aborted"]:
                            break
                        selection = item.get("torrentSelection")
                    if len(files) > 1 and selection:
                        rpc_call("aria2.changeOption", [gid, {"select-file": ",".join(str(i) for i in selection)}])
                    rpc_call("aria2.unpause", [gid])
                    files_resolved = True
                    item["phase"] = "connecting"
                    self.save_state()
                    continue

                if not is_metadata_phase and tot_b > 0:
                    item["phase"] = "downloading"
                    item["totalSize"] = tot_b
                    item["downloadedBytes"] = dl_b
                    item["progress"] = min(99.9, round((dl_b / tot_b) * 100.0, 2))
                    item["speed"] = spd
                    rem = max(0, tot_b - dl_b)
                    item["timeLeft"] = int(rem / spd) if spd > 0 else None
                    item["speedHistory"] = (item.get("speedHistory") or [])[-59:] + [spd]

                    # Map torrent piece bitfield across the 32 visual ports
                    segs = item.get("segments") or []
                    n_s = len(segs)
                    per_s = max(1, tot_b // n_s)
                    pct_overall = min(1.0, dl_b / max(1, tot_b))
                    bf_hex = st_obj.get("bitfield") or ""
                    bits = ""
                    if bf_hex:
                        try:
                            bits = bin(int(bf_hex, 16))[2:].zfill(len(bf_hex) * 4)
                        except Exception:
                            bits = ""

                    for idx_s, s in enumerate(segs):
                        s_start = idx_s * per_s
                        s_end = (tot_b - 1) if (idx_s == n_s - 1) else ((idx_s + 1) * per_s - 1)
                        s_len = max(1, s_end - s_start + 1)
                        s["startByte"] = s_start
                        s["endByte"] = s_end
                        s["size"] = s_len
                        if bits and len(bits) >= n_s:
                            b_start = int(idx_s * len(bits) / n_s)
                            b_end = max(b_start + 1, int((idx_s + 1) * len(bits) / n_s))
                            sub_bits = bits[b_start:b_end]
                            ratio = sub_bits.count("1") / max(1, len(sub_bits))
                        else:
                            ratio = pct_overall
                        s_dl = min(s_len, int(s_len * ratio))
                        s["downloaded"] = s_dl
                        s["currentByte"] = s_start + s_dl
                        s["status"] = "completed" if s_dl >= s_len else "downloading"
                        s["info"] = f"Peers: {peers} (Seeders: {seeders})"

                if st == "complete" and not is_metadata_phase:
                    item["phase"] = "saving"
                    files = st_obj.get("files") or []
                    # Stop the engine so no file handles stay open, then move finished data out of temp
                    if proc and proc.poll() is None:
                        try:
                            proc.terminate()
                            proc.wait(timeout=5)
                        except Exception:
                            pass
                    final_path = self._move_torrent_output(bt_dir, item["saveDir"], files)
                    if not final_path or not os.path.exists(final_path):
                        raise RuntimeError("تعذر نقل ملفات التورنت إلى مجلد الحفظ.")
                    item["filePath"] = final_path
                    if len([e for e in (files or []) if str(e.get("selected", "true")).lower() != "false"]) == 1:
                        item["filename"] = os.path.basename(final_path)
                    for s in item.get("segments") or []:
                        s["status"] = "completed"
                        if s.get("size"):
                            s["downloaded"] = s["size"]
                        s["currentByte"] = s.get("endByte", 0) + 1
                    item["downloadedBytes"] = item["totalSize"] or dl_b
                    item["totalSize"] = item["downloadedBytes"]
                    item["phase"] = "done"
                    item["finishedAt"] = time.time()
                    item["progress"] = 100.0
                    item["speed"] = 0
                    item["timeLeft"] = 0
                    item["status"] = "completed"
                    self._cleanup_item_temp(item)
                    self.controllers.pop(item["id"], None)
                    self.save_state()
                    self.signals.completed.emit(item["id"])
                    break

                if st == "error":
                    raise RuntimeError(st_obj.get("errorMessage") or "Torrent download error")

        except Exception as err:
            self.controllers.pop(item["id"], None)
            if not ctrl["aborted"]:
                msg = str(err).strip()
                item["status"] = "error"
                item["errorMsg"] = msg[:160]
                item["speed"] = 0
                for s in item.get("segments") or []:
                    if s.get("status") != "completed":
                        s["status"] = "error"
                        s["info"] = msg[:60]
                self.save_state()
        finally:
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass

    def _move_torrent_output(self, bt_dir: str, save_dir: str, files: list) -> str:
        """Delete unselected leftovers, move finished torrent data into save_dir. Raises on failure with rollback."""
        for f_ in files or []:
            if str(f_.get("selected", "true")).lower() == "false" and f_.get("path"):
                try:
                    if os.path.isfile(f_["path"]):
                        os.remove(f_["path"])
                except Exception:
                    pass
        os.makedirs(save_dir, exist_ok=True)
        entries = [e for e in os.listdir(bt_dir) if not e.lower().endswith(".aria2")]
        if not entries:
            raise RuntimeError("لم يتم العثور على مخرجات التورنت لنقلها.")
        moved_pairs = []
        try:
            for name in entries:
                src_p = os.path.join(bt_dir, name)
                base, ext = os.path.splitext(name) if os.path.isfile(src_p) else (name, "")
                dest = os.path.join(save_dir, name)
                n = 1
                while os.path.exists(dest):
                    dest = os.path.join(save_dir, f"{base} ({n}){ext}")
                    n += 1
                shutil.move(src_p, dest)
                moved_pairs.append((src_p, dest))
        except Exception as err:
            for orig_src, dest in reversed(moved_pairs):
                try:
                    if os.path.exists(dest) and not os.path.exists(orig_src):
                        shutil.move(dest, orig_src)
                except Exception:
                    pass
            raise RuntimeError(f"فشل نقل مخرجات التورنت إلى مجلد الحفظ: {err}") from err
        moved = [dest for _, dest in moved_pairs]
        # Remove empty folders left behind by unselected files
        for d in moved:
            if os.path.isdir(d):
                for root, dirs, fnames in os.walk(d, topdown=False):
                    if not dirs and not fnames:
                        try:
                            os.rmdir(root)
                        except Exception:
                            pass
        if len(moved) == 1:
            return moved[0]
        return save_dir

    def _finalize(self, item: dict, ctrl: dict):
        try:
            ctrl["file"].close()
            if ctrl["aborted"]:
                return
            if not os.path.splitext(item.get("filename") or "")[1]:
                ext = _sniff_file_ext(item["tempFilePath"]) or _infer_ext_from_meta(item.get("url") or "", {})
                if ext:
                    item["filename"] = f"{item.get('filename') or 'download_file'}{ext}"
                    item["category"] = detect_category(item["filename"])
                    if not item.get("customSaveDir"):
                        item["saveDir"] = os.path.join(self.settings["downloadsRoot"], item["category"])
                    os.makedirs(item["saveDir"], exist_ok=True)
                    item["filePath"] = os.path.join(item["saveDir"], item["filename"])
            segs = item.get("segments") or []
            if any(s.get("status") != "completed" for s in segs):
                raise RuntimeError("بعض أجزاء التنزيل لم تكتمل بنجاح. أعد المحاولة.")
            actual_size = os.path.getsize(item["tempFilePath"])
            if item.get("totalSize") and actual_size != item["totalSize"]:
                raise RuntimeError("الملف لم يصل بحجمه الكامل. أعد المحاولة.")
            if item.get("category") == "Video" or item.get("expectedDuration"):
                item["phase"] = "verifying"
                item["actualDuration"] = self._validate_video_output(item["tempFilePath"], item)
            if ctrl["aborted"]:
                return
            item["phase"] = "saving"
            destination = self._available_media_path(item["filePath"], item["id"])
            shutil.move(item["tempFilePath"], destination)
            item["filePath"] = destination
            item["filename"] = os.path.basename(destination)
        except Exception as err:
            if not ctrl["aborted"]:
                item.update(status="error", speed=0, errorMsg=str(err)[:160])
                self.save_state()
            return
        finally:
            self.controllers.pop(item["id"], None)
        self._cleanup_item_temp(item)
        item["downloadedBytes"] = actual_size
        item["totalSize"] = item["downloadedBytes"]
        item["progress"] = 100.0
        item["speed"] = 0
        item["timeLeft"] = 0
        item["finishedAt"] = time.time()
        item["status"] = "completed"
        self.save_state()
        self.signals.completed.emit(item["id"])

    def apply_torrent_selection(self, dl_id: str, selection: list) -> bool:
        """Persists selected torrent file indices and applies live option update if aria2c is active."""
        with self.lock:
            item = self.downloads.get(dl_id)
            if not item or not selection:
                return False
            clean_sel = [int(i) for i in selection]
            item["torrentSelection"] = clean_sel
            ctrl = self.controllers.get(dl_id)
        if ctrl and ctrl.get("aria2_rpc_call") and ctrl.get("aria2_gid"):
            try:
                ctrl["aria2_rpc_call"](
                    "aria2.changeOption",
                    [ctrl["aria2_gid"], {"select-file": ",".join(str(i) for i in clean_sel)}],
                )
            except Exception:
                pass
        self.save_state()
        return True

    def pause_download(self, dl_id: str):
        # A transfer fed by a browser tab cannot be resumed from here: pausing it cancels it cleanly
        if self.cancel_browser_transfer(dl_id, "تم إلغاء التنزيل. اضغط زر التنزيل على الفيديو في المتصفح للبدء من جديد."):
            return
        ctrl = self.controllers.pop(dl_id, None)
        if ctrl:
            ctrl["aborted"] = True
            try:
                if "file" in ctrl and ctrl["file"]:
                    ctrl["file"].close()
            except Exception:
                pass
            for fh in ctrl.get("video_stream_files") or []:
                try:
                    if fh:
                        fh.close()
                except Exception:
                    pass
            proc = ctrl.get("aria2_proc")
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        item = self.downloads.get(dl_id)
        if item and item["status"] != "completed":
            item["status"] = "paused"
            item["speed"] = 0
            self.save_state()

    def pause_all(self):
        for k in list(self.controllers.keys()):
            self.pause_download(k)

    def delete_download(self, dl_id: str):
        self.pause_download(dl_id)
        with self.lock:
            item = self.downloads.pop(dl_id, None)
            recent = self.__dict__.get("_recent_captures")
            if isinstance(recent, dict):
                for k in [k for k, (_ts, did) in recent.items() if did == dl_id]:
                    recent.pop(k, None)
        if item:
            self._cleanup_item_temp(item)
        self.save_state()

    def delete_completed(self):
        with self.lock:
            for k in [k for k, v in list(self.downloads.items()) if v["status"] == "completed"]:
                self.downloads.pop(k, None)
        self.save_state()

    def compute_checksum(self, dl_id: str):
        item = self.downloads.get(dl_id)
        if not item or not os.path.exists(item["filePath"]):
            return None
        sha = hashlib.sha256()
        md5 = hashlib.md5()
        with open(item["filePath"], "rb") as f:
            while chunk := f.read(262144):
                sha.update(chunk)
                md5.update(chunk)
        item["checksumSha256"] = sha.hexdigest()
        item["checksumMd5"] = md5.hexdigest()
        return {"sha256": item["checksumSha256"], "md5": item["checksumMd5"]}

    def _speed_loop(self):
        while True:
            time.sleep(0.3)
            try:
                now = time.time()
                with self.lock:
                    downloads_snap = list(self.downloads.values())
                    ctrls_snap = [(dl_id, ctrl, self.downloads.get(dl_id)) for dl_id, ctrl in self.controllers.items()]
                # Total speed of all running downloads (used by the global speed limit)
                self.total_speed = sum(
                    int(it.get("speed") or 0) for it in downloads_snap if it.get("status") == "downloading"
                )
                for dl_id, ctrl, item in ctrls_snap:
                    if not item or item["status"] != "downloading":
                        continue
                    if item.get("isTorrent") or (item.get("isVideo") and not item.get("useRangeVideoEngine") and not item.get("browserTransfer")):
                        continue
                    elapsed = max(0.1, now - ctrl["last_time"])
                    delta = max(0, item["downloadedBytes"] - ctrl["last_bytes"])
                    inst = int(delta / elapsed)
                    item["speed"] = int(item["speed"] * 0.6 + inst * 0.4) if item["speed"] > 0 else inst
                    ctrl["last_bytes"] = item["downloadedBytes"]
                    ctrl["last_time"] = now
                    if item["totalSize"] > 0:
                        item["progress"] = min(99.9, round((item["downloadedBytes"] / item["totalSize"]) * 100, 2))
                        rem = max(0, item["totalSize"] - item["downloadedBytes"])
                        item["timeLeft"] = int(rem / item["speed"]) if item["speed"] > 0 else None
                    item["speedHistory"] = (item.get("speedHistory") or [])[-35:] + [item["speed"]]
            except Exception:
                pass


# ==============================================================================
# INTERACTIVE 3-SCREEN BROWSER SETUP WIZARD (CHROME / EDGE / BRAVE)
# ==============================================================================
EDGE_STORE_CRX_ID = "hgcdbjpjlfgnejhceobphikeebmhmgcj"
EDGE_STORE_URL = f"https://microsoftedge.microsoft.com/addons/detail/{EDGE_STORE_CRX_ID}"


def is_edge_store_extension_installed(user_data_dir: str = "") -> bool:
    """Read-only check whether the official Edge Add-ons Store CRX is installed in any Edge profile."""
    base = user_data_dir or os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\Edge\User Data")
    if not base or not os.path.isdir(base):
        return False
    try:
        entries = os.listdir(base)
    except OSError:
        return False
    for name in entries:
        if name == "Default" or name.startswith("Profile "):
            ext_dir = os.path.join(base, name, "Extensions", EDGE_STORE_CRX_ID)
            try:
                if os.path.isdir(ext_dir) and any(
                    os.path.isdir(os.path.join(ext_dir, sub)) for sub in os.listdir(ext_dir)
                ):
                    return True
            except OSError:
                continue
    return False


BROWSER_SPECS = [
    ("msedge", "Microsoft Edge", EDGE_STORE_URL, "#0284c7"),
    ("chrome", "Google Chrome", "chrome://extensions", "#2563eb"),
    ("brave", "Brave Browser", "brave://extensions", "#ea580c"),
]


class BrowserIconBadge(QWidget):
    """Paints a sleek vector circular badge for Chrome, Edge, or Brave."""

    def __init__(self, br_key: str, size: int = 44, parent=None):
        super().__init__(parent)
        self.br_key = br_key
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(2, 2, w - 4, h - 4)

        if self.br_key == "chrome":
            # Outer soft circle + 4-color ring + center blue core
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#e8effd" if not _is_dark_theme() else "#1e293b"))
            painter.drawEllipse(r)
            ring_r = QRectF(7, 7, w - 14, h - 14)
            for start_deg, span_deg, col in [
                (30, 120, "#ea4335"),
                (150, 120, "#34a853"),
                (270, 120, "#fbbc05"),
            ]:
                pen = QPen(QColor(col), 5.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.FlatCap)
                painter.setPen(pen)
                painter.drawArc(ring_r, start_deg * 16, span_deg * 16)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor("#1a73e8"))
            painter.drawEllipse(QRectF(w * 0.34, h * 0.34, w * 0.32, h * 0.32))
        elif self.br_key == "msedge":
            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0.0, QColor("#0078d4"))
            grad.setColorAt(1.0, QColor("#00c7b7"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawEllipse(r)
            painter.setPen(QColor("#ffffff"))
            f = painter.font()
            f.setBold(True)
            f.setPixelSize(int(h * 0.48))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "e")
        else:
            grad = QLinearGradient(0, 0, w, h)
            grad.setColorAt(0.0, QColor("#fb542b"))
            grad.setColorAt(1.0, QColor("#f59e0b"))
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(grad)
            painter.drawEllipse(r)
            painter.setPen(QColor("#ffffff"))
            f = painter.font()
            f.setBold(True)
            f.setPixelSize(int(h * 0.44))
            painter.setFont(f)
            painter.drawText(r, Qt.AlignmentFlag.AlignCenter, "B")


class BrowserStepDiagramWidget(QWidget):
    """Paints a visual 3-step illustration for either Official Store install or Developer Mode unpacked setup."""

    def __init__(self, is_ar: bool = True, parent=None):
        super().__init__(parent)
        self.is_ar = is_ar
        self.store_mode = False
        self.setMinimumHeight(195)

    def set_store_mode(self, store_mode: bool):
        self.store_mode = bool(store_mode)
        self.update()

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Three visual step cards side by side (in RTL: Step 1 on Right, Step 2 in Center, Step 3 on Left)
        gap = 12
        card_w = (w - gap * 2) / 3.0
        card_h = h - 4

        if self.store_mode:
            steps = [
                (
                    "1",
                    "متجر إضافات Edge الرسمي" if self.is_ar else "Official Edge Add-ons Store",
                    "فُتحت صفحة الإضافة تلقائياً" if self.is_ar else "Store page opened automatically",
                    "store_page",
                ),
                (
                    "2",
                    "اضغط زر Get (الحصول عليها)" if self.is_ar else "Click the blue Get button",
                    "أعلى صفحة الإضافة في المتجر" if self.is_ar else "Top right of the store listing",
                    "store_get",
                ),
                (
                    "3",
                    "اضغط Add extension" if self.is_ar else "Click Add extension",
                    "يتصل بالبرنامج تلقائياً ✓" if self.is_ar else "Connects automatically ✓",
                    "store_confirm",
                ),
            ]
        else:
            steps = [
                (
                    "1",
                    "فعّل وضع المطوّر" if self.is_ar else "Enable Developer mode",
                    "أعلى صفحة الإضافات في المتصفح" if self.is_ar else "Top corner of Extensions page",
                    "toggle",
                ),
                (
                    "2",
                    "اضغط Load unpacked" if self.is_ar else "Click Load unpacked",
                    "أو «تحميل غير محزوم» بالعربية" if self.is_ar else "Opens the folder picker dialog",
                    "button",
                ),
                (
                    "3",
                    "اضغط Ctrl + V ثم Enter" if self.is_ar else "Press Ctrl + V then Enter",
                    "المسار منسوخ جاهز في الحافظة ✓" if self.is_ar else "Path is already copied to clipboard ✓",
                    "keys",
                ),
            ]

        for idx, (num, title, sub, kind) in enumerate(steps):
            col_idx = (2 - idx) if self.is_ar else idx
            x = col_idx * (card_w + gap)
            rect = QRectF(x, 2, card_w, card_h)

            # Card surface
            painter.setPen(QPen(QColor(p["border"]), 1.2))
            painter.setBrush(QColor(p["surface2"]))
            painter.drawRoundedRect(rect, 10, 10)

            # Step number badge at top center
            badge_r = QRectF(x + (card_w - 28) / 2.0, 12, 28, 28)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(p["accent"]))
            painter.drawEllipse(badge_r)
            painter.setPen(QColor("#ffffff"))
            f_num = painter.font()
            f_num.setBold(True)
            f_num.setPixelSize(14)
            painter.setFont(f_num)
            painter.drawText(badge_r, Qt.AlignmentFlag.AlignCenter, num)

            # Visual graphic mockup inside a mini browser bar box (y: 48..116)
            vis_rect = QRectF(x + 12, 48, card_w - 24, 66)
            painter.setPen(QPen(QColor(p["border"]), 1.0))
            painter.setBrush(QColor(p["surface"]))
            painter.drawRoundedRect(vis_rect, 8, 8)

            if kind == "store_page":
                pill_w = min(vis_rect.width() - 18, 168)
                pill_r = QRectF(vis_rect.center().x() - pill_w / 2, vis_rect.center().y() - 16, pill_w, 32)
                painter.setPen(QPen(QColor("#0284c7"), 1.4))
                painter.setBrush(QColor(p["accent_soft"]))
                painter.drawRoundedRect(pill_r, 6, 6)
                painter.setPen(QColor("#0284c7"))
                f_lbl = painter.font()
                f_lbl.setBold(True)
                f_lbl.setPixelSize(11)
                painter.setFont(f_lbl)
                painter.drawText(pill_r, Qt.AlignmentFlag.AlignCenter, "Edge Add-ons  •  Live")

            elif kind == "store_get":
                btn_w = min(vis_rect.width() - 36, 130)
                btn_r = QRectF(vis_rect.center().x() - btn_w / 2, vis_rect.center().y() - 17, btn_w, 34)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor("#0078d4"))
                painter.drawRoundedRect(btn_r, 6, 6)
                painter.setPen(QColor("#ffffff"))
                f_btn = painter.font()
                f_btn.setBold(True)
                f_btn.setPixelSize(13)
                painter.setFont(f_btn)
                painter.drawText(btn_r, Qt.AlignmentFlag.AlignCenter, "Get")

            elif kind == "store_confirm":
                btn_w = min(vis_rect.width() - 20, 152)
                btn_r = QRectF(vis_rect.center().x() - btn_w / 2, vis_rect.center().y() - 17, btn_w, 34)
                painter.setPen(QPen(QColor(p["success"]), 1.8))
                painter.setBrush(QColor(p["accent_soft"]))
                painter.drawRoundedRect(btn_r, 6, 6)
                painter.setPen(QColor(p["success"]))
                f_btn = painter.font()
                f_btn.setBold(True)
                f_btn.setPixelSize(12)
                painter.setFont(f_btn)
                painter.drawText(btn_r, Qt.AlignmentFlag.AlignCenter, "Add extension ✓")

            elif kind == "toggle":
                # Draw "Developer mode" label + ON blue toggle switch centered inside vis_rect
                sw_w, sw_h = 38, 22
                total_w = sw_w + 8 + 94
                sw_x = vis_rect.center().x() - total_w / 2
                sw_y = vis_rect.center().y() - sw_h / 2
                sw_rect = QRectF(sw_x, sw_y, sw_w, sw_h)
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QColor(p["accent"]))
                painter.drawRoundedRect(sw_rect, 11, 11)
                painter.setBrush(QColor("#ffffff"))
                painter.drawEllipse(QRectF(sw_x + sw_w - 19, sw_y + 3, 16, 16))

                painter.setPen(QColor(p["text"]))
                f_lbl = painter.font()
                f_lbl.setBold(True)
                f_lbl.setPixelSize(11)
                painter.setFont(f_lbl)
                lbl_r = QRectF(sw_x + sw_w + 8, sw_y - 2, 100, sw_h + 4)
                painter.drawText(
                    lbl_r,
                    Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                    "Developer mode",
                )

            elif kind == "button":
                # Draw browser's "Load unpacked" button with highlight border
                btn_w = min(vis_rect.width() - 20, 154)
                btn_h = 34
                btn_r = QRectF(
                    vis_rect.center().x() - btn_w / 2,
                    vis_rect.center().y() - btn_h / 2,
                    btn_w,
                    btn_h,
                )
                painter.setPen(QPen(QColor(p["accent"]), 1.8))
                painter.setBrush(QColor(p["accent_soft"]))
                painter.drawRoundedRect(btn_r, 6, 6)
                painter.setPen(QColor(p["accent"]))
                f_btn = painter.font()
                f_btn.setBold(True)
                f_btn.setPixelSize(12)
                painter.setFont(f_btn)
                painter.drawText(btn_r, Qt.AlignmentFlag.AlignCenter, "Load unpacked")

            else:
                # Draw keyboard keys: [Ctrl] + [V] -> [Enter]
                cy = vis_rect.center().y()
                cx = vis_rect.center().x()
                keys = [("Ctrl", 42), ("V", 30), ("Enter ↵", 58)]
                total_kw = sum(kw for _, kw in keys) + 24
                kx = cx - total_kw / 2
                f_key = painter.font()
                f_key.setBold(True)
                f_key.setPixelSize(11)
                painter.setFont(f_key)
                for k_idx, (k_txt, kw) in enumerate(keys):
                    kr = QRectF(kx, cy - 15, kw, 30)
                    is_enter = k_idx == 2
                    painter.setPen(QPen(QColor(p["success"] if is_enter else p["accent"]), 1.4))
                    painter.setBrush(QColor(p["accent_soft"]))
                    painter.drawRoundedRect(kr, 5, 5)
                    painter.setPen(QColor(p["success"] if is_enter else p["text"]))
                    painter.drawText(kr, Qt.AlignmentFlag.AlignCenter, k_txt)
                    kx += kw + 12

            # Title & subtitle at bottom of card
            painter.setPen(QColor(p["text"]))
            f_t = painter.font()
            f_t.setBold(True)
            f_t.setPixelSize(13)
            painter.setFont(f_t)
            painter.drawText(
                QRectF(x + 6, 120, card_w - 12, 28),
                Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                title,
            )

            is_final = kind in ("keys", "store_confirm")
            painter.setPen(QColor(p["success"] if is_final else p["muted"]))
            f_s = painter.font()
            f_s.setBold(is_final)
            f_s.setPixelSize(11)
            painter.setFont(f_s)
            painter.drawText(
                QRectF(x + 8, 150, card_w - 16, 32),
                Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
                sub,
            )


class SuccessCheckBadge(QWidget):
    """Paints a large emerald success circle with a crisp checkmark for Screen 3."""

    def __init__(self, size: int = 84, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Soft outer glow ring
        painter.setPen(Qt.PenStyle.NoPen)
        c_outer = QColor(p["success"])
        c_outer.setAlpha(38)
        painter.setBrush(c_outer)
        painter.drawEllipse(QRectF(2, 2, w - 4, h - 4))

        # Solid inner circle
        painter.setBrush(QColor(p["success"]))
        painter.drawEllipse(QRectF(12, 12, w - 24, h - 24))

        # Crisp white checkmark
        pen = QPen(QColor("#ffffff"), 4.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(w * 0.33, h * 0.52)
        path.lineTo(w * 0.46, h * 0.65)
        path.lineTo(w * 0.68, h * 0.37)
        painter.drawPath(path)


class PulseWaitDot(QWidget):
    """Animated spinning/pulsing ring shown while waiting for the browser extension handshake."""

    def __init__(self, size: int = 28, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.angle = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(45)

    def _tick(self):
        self.angle = (self.angle + 12) % 360
        self.update()

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(3, 3, self.width() - 6, self.height() - 6)
        painter.setPen(QPen(QColor(p["track"]), 3.0))
        painter.drawEllipse(r)
        pen = QPen(QColor(p["accent"]), 3.2, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(r, -self.angle * 16, -110 * 16)


class BrowserSetupDialog(QDialog):
    """
    Interactive 3-Screen Browser Onboarding Wizard:
      Screen 0: Choose Browser (detects installed Chrome / Edge / Brave + shows connection status)
      Screen 1: Visual 3-Step Guide + Live Handshake Listener (auto-advances when extension loads)
      Screen 2: Automatic Success Confirmation Screen
    """

    def __init__(self, engine: ScorpionNativeEngine, lang: str = "ar", parent=None):
        super().__init__(parent)
        self.engine = engine
        self.is_ar = lang == "ar"
        self.parent_win = parent
        self.selected_browser_key = "chrome"
        self.selected_browser_name = "Google Chrome"
        self.selected_ext_url = "chrome://extensions"
        self.wait_started_at = 0.0

        p = pal()
        self.setWindowTitle(
            "معالج ربط المتصفحات الذكي — Scorpion Download Manager"
            if self.is_ar
            else "Smart Browser Setup Wizard — Scorpion Download Manager"
        )
        self.resize(740, 540)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # ------------------------------------------------------------------
        # Wizard Top Step Bar (1 -> 2 -> 3)
        # ------------------------------------------------------------------
        top_bar = QFrame()
        top_bar.setObjectName("CardFrame")
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(16, 12, 16, 12)
        tb_layout.setSpacing(10)

        wiz_icon = QLabel()
        wiz_icon.setFixedSize(26, 26)
        wiz_icon.setPixmap(scorpion_emblem_pixmap(26, small=False))
        tb_layout.addWidget(wiz_icon)
        wiz_title = QLabel(
            "معالج ربط المتصفحات التفاعلي" if self.is_ar else "Interactive Browser Setup Wizard"
        )
        wiz_title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {p['text']};")
        tb_layout.addWidget(wiz_title)
        tb_layout.addStretch()

        self.step_pills = []
        step_names = (
            ["1. اختيار المتصفح", "2. تفعيل الإضافة", "3. تم الربط"]
            if self.is_ar
            else ["1. Select Browser", "2. Enable Extension", "3. Connected"]
        )
        for s_txt in step_names:
            pill = QLabel(s_txt)
            pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            tb_layout.addWidget(pill)
            self.step_pills.append(pill)

        root.addWidget(top_bar)

        # ------------------------------------------------------------------
        # QStackedWidget for the 3 Screens
        # ------------------------------------------------------------------
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)

        self._build_screen_1_select()
        self._build_screen_2_guide()
        self._build_screen_3_success()

        # Connect live handshake signal + polling timer
        self.engine.signals.extension_connected.connect(self._on_extension_ping_received)
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_connection_state)
        self._poll_timer.start(450)

        self.go_to_screen(0)

    def _update_step_pills(self, current_idx: int):
        p = pal()
        for idx, pill in enumerate(self.step_pills):
            if idx == current_idx:
                pill.setStyleSheet(
                    f"background: {p['primary_bg']}; color: {p['primary_text']}; font-weight: 700; font-size: 12px; "
                    f"padding: 4px 12px; border-radius: 12px;"
                )
            elif idx < current_idx:
                pill.setStyleSheet(
                    f"background: {p['accent_soft']}; color: {p['success']}; font-weight: 700; font-size: 12px; "
                    f"padding: 4px 12px; border-radius: 12px;"
                )
            else:
                pill.setStyleSheet(
                    f"background: {p['surface2']}; color: {p['muted']}; font-weight: 600; font-size: 12px; "
                    f"padding: 4px 12px; border-radius: 12px;"
                )

    def go_to_screen(self, idx: int):
        self._update_step_pills(idx)
        if idx == 0:
            self._refresh_screen_1_cards()
        self.stack.setCurrentIndex(idx)

    # ==========================================================================
    # SCREEN 1: BROWSER SELECTION
    # ==========================================================================
    def _build_screen_1_select(self):
        p = pal()
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(10)

        intro_card = QFrame()
        intro_card.setObjectName("CardFrame")
        ic_lay = QVBoxLayout(intro_card)
        ic_lay.setContentsMargins(16, 12, 16, 12)
        ic_lay.setSpacing(4)

        h_lbl = QLabel(
            "اختر المتصفح الذي تريد ربطه ببرنامج Scorpion Download Manager:"
            if self.is_ar
            else "Select the browser you want to integrate with Scorpion Download Manager:"
        )
        h_lbl.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {p['text']};")
        ic_lay.addWidget(h_lbl)

        s_lbl = QLabel(
            "ثبّت الإضافة الرسمية مباشرة من متجر Microsoft Edge بضغطة واحدة، أو اربط Chrome وBrave من مسار النظام الدائم مع اكتشاف فوري للتفعيل."
            if self.is_ar
            else "Install directly from the official Microsoft Edge Add-ons Store in 1 click, or link Chrome & Brave from the permanent system path with live auto-detection."
        )
        s_lbl.setWordWrap(True)
        s_lbl.setStyleSheet(f"font-size: 12px; color: {p['muted']};")
        ic_lay.addWidget(s_lbl)
        lay.addWidget(intro_card)

        # Browser cards container
        self.br_cards_widgets = {}
        for br_key, br_name, ext_url, _accent in BROWSER_SPECS:
            card = QFrame()
            card.setObjectName("CardFrame")
            row = QHBoxLayout(card)
            row.setContentsMargins(16, 12, 16, 12)
            row.setSpacing(14)

            badge = BrowserIconBadge(br_key, 44)
            row.addWidget(badge)

            info_col = QVBoxLayout()
            info_col.setSpacing(3)
            align_side = (
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
                if self.is_ar
                else Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
            )
            name_lbl = QLabel(L(br_name))
            name_lbl.setAlignment(align_side)
            name_lbl.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {p['text']};")
            status_lbl = QLabel()
            status_lbl.setWordWrap(True)
            status_lbl.setAlignment(align_side)
            status_lbl.setStyleSheet(f"font-size: 12px; color: {p['muted']};")
            info_col.addWidget(name_lbl)
            info_col.addWidget(status_lbl)
            row.addLayout(info_col, 1)

            conn_pill = QLabel()
            conn_pill.setAlignment(Qt.AlignmentFlag.AlignCenter)
            row.addWidget(conn_pill)

            btn_connect = QPushButton()
            btn_connect.setCursor(Qt.CursorShape.PointingHandCursor)
            btn_connect.setMinimumWidth(155)
            btn_connect.setMinimumHeight(36)
            btn_connect.clicked.connect(
                lambda _c, k=br_key, n=br_name, u=ext_url: self.start_browser_wizard(k, n, u)
            )
            row.addWidget(btn_connect)

            lay.addWidget(card)
            self.br_cards_widgets[br_key] = {
                "card": card,
                "status_lbl": status_lbl,
                "conn_pill": conn_pill,
                "btn": btn_connect,
            }

        # Auto-start option card
        opts_card = QFrame()
        opts_card.setObjectName("CardFrame")
        opts_lay = QHBoxLayout(opts_card)
        opts_lay.setContentsMargins(16, 10, 16, 10)
        self.chk_auto_start = QCheckBox(
            "بدء التحميل تلقائياً وبأقصى سرعة فور الضغط على أي رابط أو زر فيديو في المتصفح"
            if self.is_ar
            else "Automatically start downloads immediately when clicked in browser"
        )
        self.chk_auto_start.setChecked(bool(self.engine.settings.get("autoStartFromBrowser", True)))
        self.chk_auto_start.toggled.connect(self.on_auto_start_toggled)
        opts_lay.addWidget(self.chk_auto_start)
        lay.addWidget(opts_card)

        lay.addStretch()

        # Footer bar
        footer = QHBoxLayout()
        self.lbl_bridge_status = QLabel()
        footer.addWidget(self.lbl_bridge_status)
        footer.addStretch()

        btn_skip = QPushButton("تخطي الآن / إغلاق" if self.is_ar else "Skip / Close")
        btn_skip.setMinimumWidth(130)
        btn_skip.clicked.connect(self.accept)
        footer.addWidget(btn_skip)
        lay.addLayout(footer)

        self.stack.addWidget(page)

    def _refresh_screen_1_cards(self):
        p = pal()
        self.engine.sync_and_repair_browser_extensions()
        connected_list = set(self.engine.settings.get("connectedBrowsers") or []) | set(self.engine.last_ext_seen.keys())
        edge_store_installed = is_edge_store_extension_installed()

        for br_key, br_name, _ext_url, _accent in BROWSER_SPECS:
            w = self.br_cards_widgets[br_key]
            exe_path = self._find_browser_exe(br_key)
            installed = os.path.exists(exe_path)
            is_conn = (br_key in connected_list) or (br_key == "msedge" and edge_store_installed)

            if br_key == "msedge" and is_conn and not edge_store_installed:
                w["conn_pill"].setText("نسخة يدوية نشطة" if self.is_ar else "Manual Copy")
                w["conn_pill"].setStyleSheet(
                    f"background: {p['surface2']}; color: {p['warn']}; font-weight: 700; "
                    f"font-size: 12px; padding: 4px 12px; border-radius: 11px;"
                )
                w["conn_pill"].show()
                w["status_lbl"].setText(
                    "متصل بنسخة يدوية سابقة — يُنصح بالترقية لنسخة متجر Edge الرسمية وحذف اليدوية"
                    if self.is_ar
                    else "Connected via manual copy — Upgrade to the official Edge Store version"
                )
                w["btn"].setText("الترقية لنسخة المتجر  ←" if self.is_ar else "Upgrade to Store  →")
                w["btn"].setObjectName("PrimaryBtn")
            elif is_conn:
                w["conn_pill"].setText(
                    ("✓ متصل (نسخة المتجر)" if br_key == "msedge" else "✓ متصل ومفعّل")
                    if self.is_ar
                    else ("✓ Official Store" if br_key == "msedge" else "✓ Connected")
                )
                w["conn_pill"].setStyleSheet(
                    f"background: {p['accent_soft']}; color: {p['success']}; font-weight: 700; "
                    f"font-size: 12px; padding: 4px 12px; border-radius: 11px;"
                )
                w["conn_pill"].show()
                w["status_lbl"].setText(
                    (
                        "الإضافة الرسمية من متجر Microsoft Edge مفعّلة وتلتقط التحميلات والفيديوهات تلقائياً"
                        if br_key == "msedge"
                        else "الإضافة مفعّلة في المتصفح وتلتقط التحميلات والفيديوهات تلقائياً"
                    )
                    if self.is_ar
                    else (
                        "Official Microsoft Edge Store extension is active and capturing downloads & videos"
                        if br_key == "msedge"
                        else "Extension is active and capturing downloads & videos automatically"
                    )
                )
                w["btn"].setText(
                    ("صفحة المتجر / فحص" if br_key == "msedge" else "إعادة الفتح / فحص")
                    if self.is_ar
                    else ("Store Page / Check" if br_key == "msedge" else "Re-open / Check")
                )
                w["btn"].setObjectName("")
            elif installed:
                w["conn_pill"].hide()
                if br_key == "msedge":
                    w["status_lbl"].setText(
                        "متاحة رسمياً على متجر Microsoft Edge — تثبيت مباشر بضغطة واحدة"
                        if self.is_ar
                        else "Official Microsoft Edge Add-ons Store — 1-click direct install"
                    )
                    w["btn"].setText("تثبيت من متجر Edge  ←" if self.is_ar else "Install from Store  →")
                else:
                    w["status_lbl"].setText(
                        "مثبّت على جهازك — جاهز للربط في 3 خطوات سريعة"
                        if self.is_ar
                        else "Installed on this PC — Ready for 3-step quick setup"
                    )
                    w["btn"].setText("ربط المتصفح الآن  ←" if self.is_ar else "Connect Browser  →")
                w["btn"].setObjectName("PrimaryBtn")
            else:
                w["conn_pill"].hide()
                w["status_lbl"].setText(
                    "غير مثبّت في المسار الافتراضي" if self.is_ar else "Not detected in default path"
                )
                w["btn"].setText("محاولة الربط" if self.is_ar else "Try Setup")
                w["btn"].setObjectName("")

            w["btn"].style().unpolish(w["btn"])
            w["btn"].style().polish(w["btn"])

        if self.engine.rpc_alive:
            self.lbl_bridge_status.setText(
                f"🟢 جسر الاتصال المحلي نشط ({L('Port ' + str(self.engine.rpc_port))})"
                if self.is_ar
                else f"🟢 Local Browser Bridge Active (Port {self.engine.rpc_port})"
            )
            self.lbl_bridge_status.setStyleSheet(f"color: {p['success']}; font-weight: 600; font-size: 12px;")
        else:
            self.lbl_bridge_status.setText(
                "🟠 جاري تشغيل جسر الاتصال..." if self.is_ar else "🟠 Starting local bridge..."
            )
            self.lbl_bridge_status.setStyleSheet(f"color: {p['warn']}; font-weight: 600; font-size: 12px;")

    # ==========================================================================
    # SCREEN 2: VISUAL 3-STEP GUIDE + LIVE AUTO-DETECTION
    # ==========================================================================
    def _build_screen_2_guide(self):
        p = pal()
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 2, 0, 0)
        lay.setSpacing(10)

        # Top info banner
        banner = QFrame()
        banner.setObjectName("CardFrame")
        b_lay = QVBoxLayout(banner)
        b_lay.setContentsMargins(16, 12, 16, 12)
        b_lay.setSpacing(6)

        self.lbl_s2_title = QLabel()
        self.lbl_s2_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {p['accent']};")
        b_lay.addWidget(self.lbl_s2_title)

        self.lbl_s2_sub = QLabel()
        self.lbl_s2_sub.setWordWrap(True)
        self.lbl_s2_sub.setStyleSheet(f"font-size: 12px; color: {p['text']};")
        b_lay.addWidget(self.lbl_s2_sub)

        # Read-only copied path box + Re-copy button
        path_row = QHBoxLayout()
        path_row.setSpacing(8)
        self.txt_ext_path = QLineEdit()
        self.txt_ext_path.setReadOnly(True)
        self.txt_ext_path.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        path_row.addWidget(self.txt_ext_path, 1)

        self.btn_recopy = QPushButton("نسخ المسار ✓" if self.is_ar else "Copy Path ✓")
        self.btn_recopy.clicked.connect(self.copy_ext_path)
        path_row.addWidget(self.btn_recopy)

        self.btn_edge_ext_mgr = QPushButton("إدارة الإضافات (حذف النسخة اليدوية)" if self.is_ar else "Manage Extensions")
        self.btn_edge_ext_mgr.clicked.connect(self._open_edge_extensions_manager)
        self.btn_edge_ext_mgr.setVisible(False)
        path_row.addWidget(self.btn_edge_ext_mgr)

        btn_reopen = QPushButton("إعادة فتح المتصفح" if self.is_ar else "Re-open Browser")
        btn_reopen.clicked.connect(self._reopen_current_browser_ext_page)
        path_row.addWidget(btn_reopen)

        b_lay.addLayout(path_row)
        lay.addWidget(banner)

        # Visual 3-Step Painted Diagram
        self.diagram = BrowserStepDiagramWidget(self.is_ar)
        lay.addWidget(self.diagram, 1)

        # Live waiting bar
        wait_card = QFrame()
        wait_card.setObjectName("CardFrame")
        w_lay = QHBoxLayout(wait_card)
        w_lay.setContentsMargins(16, 12, 16, 12)
        w_lay.setSpacing(12)

        self.pulse_dot = PulseWaitDot(26)
        w_lay.addWidget(self.pulse_dot)

        self.lbl_wait_status = QLabel(
            "في انتظار تفعيل الإضافة في المتصفح... (سيتم الانتقال تلقائياً فور التفعيل)"
            if self.is_ar
            else "Waiting for extension activation in browser... (Will advance automatically)"
        )
        self.lbl_wait_status.setStyleSheet(f"font-size: 13px; font-weight: 700; color: {p['accent']};")
        w_lay.addWidget(self.lbl_wait_status, 1)

        lay.addWidget(wait_card)

        # Footer navigation
        footer = QHBoxLayout()
        btn_back = QPushButton("→ رجوع لاختيار متصفح آخر" if self.is_ar else "← Back to Browsers")
        btn_back.clicked.connect(lambda: self.go_to_screen(0))
        footer.addWidget(btn_back)
        footer.addStretch()

        btn_manual_done = QPushButton("تم التفعيل يدوياً ✓" if self.is_ar else "I Enabled It ✓")
        btn_manual_done.clicked.connect(self._manual_confirm_connected)
        footer.addWidget(btn_manual_done)
        lay.addLayout(footer)

        self.stack.addWidget(page)

    # ==========================================================================
    # SCREEN 3: AUTOMATIC SUCCESS CONFIRMATION
    # ==========================================================================
    def _build_screen_3_success(self):
        p = pal()
        page = QWidget()
        lay = QVBoxLayout(page)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(14)

        card = QFrame()
        card.setObjectName("CardFrame")
        c_lay = QVBoxLayout(card)
        c_lay.setContentsMargins(28, 28, 28, 24)
        c_lay.setSpacing(12)

        badge_row = QHBoxLayout()
        badge_row.addStretch()
        badge_row.addWidget(SuccessCheckBadge(86))
        badge_row.addStretch()
        c_lay.addLayout(badge_row)

        self.lbl_s3_title = QLabel()
        self.lbl_s3_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_s3_title.setStyleSheet(f"font-size: 19px; font-weight: 800; color: {p['success']};")
        c_lay.addWidget(self.lbl_s3_title)

        self.lbl_s3_sub = QLabel(
            "تم الاتصال بنجاح بين إضافة المتصفح وبرنامج Scorpion Download Manager!"
            if self.is_ar
            else "Browser extension is now actively linked to Scorpion Download Manager!"
        )
        self.lbl_s3_sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_s3_sub.setStyleSheet(f"font-size: 13px; color: {p['muted']};")
        c_lay.addWidget(self.lbl_s3_sub)

        c_lay.addSpacing(6)

        for feat_ar, feat_en in [
            (
                "✓  اعتراض جميع التحميلات تلقائياً وتحميلها بأقصى سرعة (16 قناة متوازية)",
                "✓  All browser downloads are automatically intercepted at full speed (16 channels)",
            ),
            (
                "✓  ظهور زر «تحميل الفيديو بواسطة Scorpion Download Manager» تلقائياً أعلى أي فيديو مع اختيار الجودة",
                "✓  Floating 'Download Video with Scorpion Download Manager' button appears on video players",
            ),
            (
                "✓  المسار محفوظ بشكل دائم في النظام ولن تحتاج لإعادة تفعيله مرة أخرى",
                "✓  Extension path is permanently synced in your system folder",
            ),
        ]:
            fl = QLabel(feat_ar if self.is_ar else feat_en)
            fl.setStyleSheet(
                f"background: {p['surface2']}; color: {p['text']}; font-weight: 600; font-size: 12.5px; "
                f"padding: 9px 14px; border-radius: 8px;"
            )
            c_lay.addWidget(fl)

        lay.addWidget(card, 1)

        footer = QHBoxLayout()
        btn_another = QPushButton("ربط متصفح آخر" if self.is_ar else "Connect Another Browser")
        btn_another.setMinimumHeight(38)
        btn_another.clicked.connect(lambda: self.go_to_screen(0))
        footer.addWidget(btn_another)

        footer.addStretch()

        btn_finish = QPushButton("إنهاء وبدء الاستخدام  ✓" if self.is_ar else "Finish & Start Using  ✓")
        btn_finish.setObjectName("PrimaryBtn")
        btn_finish.setMinimumWidth(190)
        btn_finish.setMinimumHeight(38)
        btn_finish.clicked.connect(self.accept)
        footer.addWidget(btn_finish)
        lay.addLayout(footer)

        self.stack.addWidget(page)

    # ==========================================================================
    # ACTIONS & AUTO-DETECTION LOGIC
    # ==========================================================================
    def _find_browser_exe(self, br_key: str) -> str:
        candidates = {
            "chrome": [
                r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            ],
            "msedge": [
                r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            ],
            "brave": [
                r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
                os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            ],
        }
        for p in candidates.get(br_key, []):
            if os.path.exists(p):
                return p
        return br_key

    def _is_store_setup(self) -> bool:
        return self.selected_browser_key == "msedge" and self.selected_ext_url.startswith("https://")

    def copy_ext_path(self) -> str:
        val = self.selected_ext_url if self._is_store_setup() else self.engine.get_permanent_ext_dir()
        if self.parent_win:
            self.parent_win.last_clip = val
        QApplication.clipboard().setText(val)
        return val

    def _open_edge_extensions_manager(self):
        exe = self._find_browser_exe("msedge")
        try:
            subprocess.Popen([exe, "edge://extensions"])
        except Exception:
            pass

    def start_browser_wizard(self, br_key: str, br_name: str, ext_url: str):
        self.selected_browser_key = br_key
        self.selected_browser_name = br_name
        self.selected_ext_url = ext_url
        self.wait_started_at = time.time()

        is_store = self._is_store_setup()
        store_already = is_edge_store_extension_installed() if is_store else False
        prev_edge_conn = br_key in (self.engine.settings.get("connectedBrowsers") or []) or (
            self.engine.last_ext_seen.get("msedge", 0.0) > 0
        )
        self._edge_store_at_start = store_already
        self._upgrading_manual_edge = bool(is_store and not store_already and prev_edge_conn)
        self.diagram.set_store_mode(is_store)
        self.btn_edge_ext_mgr.setVisible(is_store)
        self.btn_recopy.setText(
            ("نسخ رابط المتجر ✓" if self.is_ar else "Copy Store Link ✓")
            if is_store
            else ("نسخ المسار ✓" if self.is_ar else "Copy Path ✓")
        )

        if is_store:
            self.txt_ext_path.setText(ext_url)
            self.txt_ext_path.setCursorPosition(0)
            self.lbl_s2_title.setText(
                "✓ تم فتح صفحة الإضافة الرسمية على متجر Microsoft Edge!"
                if self.is_ar
                else "✓ Official Microsoft Edge Add-ons Store page opened!"
            )
            self.lbl_s2_sub.setText(
                "اضغط زر «Get / الحصول عليها» ثم «Add extension» في المتصفح — وسينتقل هذا المعالج تلقائياً فور التفعيل.\n"
                "تنبيه: إذا كنت قد ركّبت نسخة يدوية سابقة عبر Load unpacked، احذفها من زر «إدارة الإضافات» لعدم تكرار الشريط."
                if self.is_ar
                else "Click 'Get' then 'Add extension' in Microsoft Edge — this wizard will advance automatically.\n"
                "Note: If you previously installed a manual unpacked copy, remove it via 'Manage Extensions' to avoid duplicates."
            )
        else:
            perm_dir = self.copy_ext_path()
            self.txt_ext_path.setText(perm_dir)
            self.txt_ext_path.setCursorPosition(0)
            self.lbl_s2_title.setText(
                f"✓ تم نسخ مسار الإضافة تلقائياً وفتح صفحة إضافات {L(br_name)}!"
                if self.is_ar
                else f"✓ Extension path copied & {br_name} extensions page opened!"
            )
            self.lbl_s2_sub.setText(
                "نفّذ هذه الـ 3 خطوات السريعة في نافذة المتصفح التي فتحت الآن — وسينتقل هذا المعالج تلقائياً فور التفعيل:"
                if self.is_ar
                else "Follow these 3 quick steps in the browser window that just opened — this wizard will advance automatically:"
            )

        self.go_to_screen(1)
        self._reopen_current_browser_ext_page()

    def _reopen_current_browser_ext_page(self):
        if not self._is_store_setup():
            self.copy_ext_path()
        exe = self._find_browser_exe(self.selected_browser_key)
        try:
            subprocess.Popen([exe, self.selected_ext_url])
        except Exception:
            pass

    def _on_extension_ping_received(self, br_key: str):
        if self.stack.currentIndex() == 1:
            if getattr(self, "_upgrading_manual_edge", False):
                if is_edge_store_extension_installed():
                    self._transition_to_success("msedge")
                return
            if br_key == self.selected_browser_key:
                self._transition_to_success(br_key)
        elif self.stack.currentIndex() == 0:
            self._refresh_screen_1_cards()

    def _poll_connection_state(self):
        if self.stack.currentIndex() == 1 and self.wait_started_at > 0:
            if self._is_store_setup():
                if not getattr(self, "_edge_store_at_start", False) and is_edge_store_extension_installed():
                    self.engine.record_browser_connection("msedge")
                    self._transition_to_success("msedge")
                    return
                if getattr(self, "_upgrading_manual_edge", False):
                    return
            seen_ts = self.engine.last_ext_seen.get(self.selected_browser_key, 0.0)
            if seen_ts >= self.wait_started_at - 0.5:
                self._transition_to_success(self.selected_browser_key)

    def _manual_confirm_connected(self):
        self.engine.record_browser_connection(self.selected_browser_key)
        self._transition_to_success(self.selected_browser_key)

    def _transition_to_success(self, br_key: str):
        br_label = self.selected_browser_name
        for k, n, _u, _c in BROWSER_SPECS:
            if k == br_key:
                br_label = n
                break
        self.lbl_s3_title.setText(
            f"تم ربط {L(br_label)} بنجاح!"
            if self.is_ar
            else f"{br_label} Connected Successfully!"
        )
        self.go_to_screen(2)

    def on_auto_start_toggled(self, checked: bool):
        self.engine.settings["autoStartFromBrowser"] = checked
        self.engine.save_state()


# ==============================================================================
# MAIN WINDOW HELPERS: PROGRESS DELEGATE + FILE TYPE ICONS
# ==============================================================================
ROLE_ID = Qt.ItemDataRole.UserRole
ROLE_PCT = Qt.ItemDataRole.UserRole + 1
ROLE_MODE = Qt.ItemDataRole.UserRole + 2
ROLE_RAW_NAME = Qt.ItemDataRole.UserRole + 3


class FilenameDelegate(QStyledItemDelegate):
    """Elides raw filenames BEFORE BiDi isolation so compact columns never split isolate pairs."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        raw = index.data(ROLE_RAW_NAME)
        if raw:
            icon_pad = (opt.decorationSize.width() + 12) if not opt.icon.isNull() else 0
            avail_w = max(60, opt.rect.width() - icon_pad - 20)
            elided = opt.fontMetrics.elidedText(str(raw), Qt.TextElideMode.ElideMiddle, avail_w)
            opt.text = bidi_filename(elided)
        elif not opt.text:
            opt.text = bidi_filename(str(index.data(Qt.ItemDataRole.DisplayRole) or ""))
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)


class ProgressDelegate(QStyledItemDelegate):
    """Draws a slim progress bar + percentage inside a table cell."""

    def paint(self, painter, option, index):
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.ControlElement.CE_ItemViewItem, opt, painter, opt.widget)

        pct = float(index.data(ROLE_PCT) or 0.0)
        mode = index.data(ROLE_MODE) or "active"
        c = pal()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(option.rect.adjusted(12, 0, -12, 0))
        txt_w = 50.0
        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        bar_h = 6.0
        mid = r.center().y()
        if rtl:
            bar = QRectF(r.left() + txt_w, mid - bar_h / 2, max(10.0, r.width() - txt_w), bar_h)
            txt_rect = QRectF(r.left(), r.top(), txt_w - 6, r.height())
        else:
            bar = QRectF(r.left(), mid - bar_h / 2, max(10.0, r.width() - txt_w), bar_h)
            txt_rect = QRectF(r.right() - txt_w + 6, r.top(), txt_w - 6, r.height())

        track = QPainterPath()
        track.addRoundedRect(bar, bar_h / 2, bar_h / 2)
        painter.fillPath(track, QColor(c["track"]))
        fw = bar.width() * (100.0 if mode == "done" else min(100.0, pct)) / 100.0
        if fw > 0:
            painter.save()
            painter.setClipPath(track)
            fill = QRectF(bar.right() - fw, bar.top(), fw, bar_h) if rtl else QRectF(bar.left(), bar.top(), fw, bar_h)
            fp = QPainterPath()
            fp.addRoundedRect(fill, bar_h / 2, bar_h / 2)
            painter.fillPath(fp, QColor(mode_color(mode)))
            painter.restore()

        f = QFont(opt.font)
        f.setPixelSize(12)
        f.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f)
        painter.setPen(QColor(c["text"] if mode != "done" else c["success"]))
        painter.drawText(txt_rect, Qt.AlignmentFlag.AlignCenter, "✓" if mode == "done" else f"{pct:.0f}%")
        painter.restore()


_FILE_ICON_CACHE = {}


def file_type_icon(filename: str) -> QIcon:
    ext = os.path.splitext(filename or "")[1].lower() or ".bin"
    if ext not in _FILE_ICON_CACHE:
        try:
            from PyQt6.QtWidgets import QFileIconProvider
            from PyQt6.QtCore import QFileInfo

            _FILE_ICON_CACHE[ext] = QFileIconProvider().icon(QFileInfo("file" + ext))
        except Exception:
            _FILE_ICON_CACHE[ext] = QIcon()
    return _FILE_ICON_CACHE[ext]


# ==============================================================================
# SETTINGS DIALOG + TORRENT FILE PICKER
# ==============================================================================
class SettingsDialog(QDialog):
    def __init__(self, engine, lang: str = "ar", parent=None):
        super().__init__(parent)
        self.engine = engine
        self.is_ar = lang == "ar"
        T = (lambda ar, en: ar) if self.is_ar else (lambda ar, en: en)
        self.T = T
        s = engine.settings
        self.setWindowTitle(T("الإعدادات — Scorpion Download Manager", "Settings — Scorpion Download Manager"))
        self.setMinimumSize(460, 300)
        try:
            avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
            self.resize(min(640, max(460, avail.width() - 40)), min(640, max(320, avail.height() - 40)))
        except Exception:
            self.resize(640, 610)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }")
        content = QWidget()
        content_lay = QVBoxLayout(content)
        content_lay.setContentsMargins(0, 0, 4, 0)
        content_lay.setSpacing(12)
        scroll.setWidget(content)
        self._scroll_area = scroll

        def card(title: str):
            fr = QFrame()
            fr.setObjectName("CardFrame")
            lay = QGridLayout(fr)
            lay.setContentsMargins(16, 12, 16, 14)
            lay.setHorizontalSpacing(12)
            lay.setVerticalSpacing(10)
            lay.setColumnStretch(1, 1)
            hdr = QLabel(title)
            hdr.setStyleSheet("font-size: 14px; font-weight: 700;")
            lay.addWidget(hdr, 0, 0, 1, 3)
            content_lay.addWidget(fr)
            return lay

        # --- Downloads ---
        g = card(T("التحميل", "Downloads"))
        g.addWidget(QLabel(T("مجلد الحفظ:", "Save folder:")), 1, 0)
        self.txt_root = QLineEdit(s.get("downloadsRoot", ""))
        self.txt_root.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.txt_root.setCursorPosition(0)
        g.addWidget(self.txt_root, 1, 1)
        b = QPushButton(T("تصفح", "Browse"))
        b.clicked.connect(self._browse_root)
        g.addWidget(b, 1, 2)

        g.addWidget(QLabel(T("عدد الأجزاء الافتراضي:", "Default parts per download:")), 2, 0)
        self.cmb_conn = FluentComboBox()
        self.cmb_conn.setMaximumWidth(140)
        self.cmb_conn.addItems(["1", "4", "8", "16", "32", "64"])
        self.cmb_conn.setCurrentText(str(s.get("defaultConnections", 32)))
        g.addWidget(self.cmb_conn, 2, 1)

        g.addWidget(QLabel(T("أقصى عدد تحميلات في نفس الوقت:", "Max simultaneous downloads:")), 3, 0)
        self.spin_max = QSpinBox()
        self.spin_max.setMaximumWidth(140)
        self.spin_max.setRange(1, 20)
        self.spin_max.setValue(int(s.get("maxConcurrent", 4)))
        g.addWidget(self.spin_max, 3, 1)

        g.addWidget(QLabel(T("حد السرعة الكلي (KB/s) — 0 بدون حد:", "Global speed limit (KB/s) — 0 = none:")), 4, 0)
        self.spin_glimit = QSpinBox()
        self.spin_glimit.setMaximumWidth(160)
        self.spin_glimit.setRange(0, 10_000_000)
        self.spin_glimit.setValue(int(s.get("globalSpeedLimitKbps", 0)))
        g.addWidget(self.spin_glimit, 4, 1)

        # --- Behaviour ---
        g2 = card(T("السلوك", "Behaviour"))
        self.chk_clip = QCheckBox(T("مراقبة الحافظة (فتح نافذة التحميل عند نسخ رابط)", "Watch clipboard for download links"))
        self.chk_clip.setChecked(bool(s.get("clipboardMonitor", True)))
        g2.addWidget(self.chk_clip, 1, 0, 1, 3)
        self.chk_auto = QCheckBox(T("بدء تحميلات المتصفح فوراً بدون سؤال", "Start browser downloads immediately"))
        self.chk_auto.setChecked(bool(s.get("autoStartFromBrowser", True)))
        g2.addWidget(self.chk_auto, 2, 0, 1, 3)
        self.chk_startup = QCheckBox(T("تشغيل البرنامج تلقائياً مع ويندوز (في الخلفية)", "Start with Windows (in the tray)"))
        self.chk_startup.setChecked(bool(s.get("startWithWindows", True)))
        g2.addWidget(self.chk_startup, 3, 0, 1, 3)
        # The Store package declares its own startup task, which only Windows Settings can switch on
        self.chk_startup.setVisible(not is_msix_packaged())
        self.chk_assoc = QCheckBox(T("فتح ملفات التورنت وروابط ماجنت بالبرنامج","Open .torrent files and Magnet links with Scorpion"))
        self.chk_assoc.setChecked(bool(s.get("associateTorrents", True)))
        g2.addWidget(self.chk_assoc, 4, 0, 1, 3)
        g2.addWidget(QLabel(T("عند بدء أي تحميل يظهر:", "When a download starts, show:")), 5, 0)
        self.cmb_on_start = FluentComboBox()
        for text, val in ((T("كارت صغير في ركن الشاشة", "A small card in the screen corner"), "card"),
                          (T("نافذة التقدم الكاملة", "The full progress window"), "window"),
                          (T("لا شيء", "Nothing"), "none")):
            self.cmb_on_start.addItem(text, val)
        self.cmb_on_start.setCurrentIndex(max(0, self.cmb_on_start.findData(s.get("onStartShow", "card"))))
        g2.addWidget(self.cmb_on_start, 5, 1, 1, 2)

        # --- Scheduler ---
        g3 = card(T("الجدولة", "Scheduler"))
        self.chk_sched = QCheckBox(T("تشغيل تحميلات «لاحقاً» يومياً في الساعة:", "Start “Download later” items daily at:"))
        self.chk_sched.setChecked(bool(s.get("schedEnabled", False)))
        g3.addWidget(self.chk_sched, 1, 0, 1, 2)
        self.time_sched = QTimeEdit()
        self.time_sched.setDisplayFormat("HH:mm")
        self.time_sched.setFixedWidth(105)
        hh, mm = (s.get("schedTime") or "02:00").split(":")[:2]
        self.time_sched.setTime(QTime(int(hh), int(mm)))
        self.time_sched.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        self.time_sched.setEnabled(self.chk_sched.isChecked())
        self.chk_sched.toggled.connect(self.time_sched.setEnabled)
        g3.addWidget(self.time_sched, 1, 2)

        content_lay.addStretch()
        root.addWidget(scroll, 1)
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton(T("إلغاء", "Cancel"))
        cancel.clicked.connect(self.reject)
        save = QPushButton(T("حفظ", "Save"))
        save.setObjectName("PrimaryBtn")
        save.setMinimumWidth(120)
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        root.addLayout(btns)

    def _browse_root(self):
        d = QFileDialog.getExistingDirectory(self, self.T("اختر مجلد الحفظ", "Choose save folder"), self.txt_root.text())
        if d:
            self.txt_root.setText(os.path.normpath(d))
            self.txt_root.setCursorPosition(0)

    def _save(self):
        s = self.engine.settings
        new_root = self.txt_root.text().strip() or self.engine.default_dl_root
        try:
            os.makedirs(new_root, exist_ok=True)
            for cat in list(CATEGORY_MAP.keys()) + ["General"]:
                os.makedirs(os.path.join(new_root, cat), exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "Scorpion Download Manager", str(e))
            return
        s["downloadsRoot"] = new_root
        s["defaultConnections"] = int(self.cmb_conn.currentText())
        s["maxConcurrent"] = self.spin_max.value()
        s["globalSpeedLimitKbps"] = self.spin_glimit.value()
        s["clipboardMonitor"] = self.chk_clip.isChecked()
        s["autoStartFromBrowser"] = self.chk_auto.isChecked()
        s["startWithWindows"] = self.chk_startup.isChecked()
        s["associateTorrents"] = self.chk_assoc.isChecked()
        s["onStartShow"] = self.cmb_on_start.currentData() or "card"
        s["schedEnabled"] = self.chk_sched.isChecked()
        new_time = self.time_sched.time().toString("HH:mm")
        if new_time != s.get("schedTime"):
            s["schedLastFired"] = ""
        s["schedTime"] = new_time
        self.engine.save_state()
        apply_shell_integration_async(s)
        self.accept()


class UpdateDialog(QDialog):
    """In-App Update Manager & Release Notes ('What's New') Dialog."""

    progress_sig = pyqtSignal(int, str)
    finished_sig = pyqtSignal(bool, str)
    check_done_sig = pyqtSignal(dict)

    def __init__(
        self,
        engine: ScorpionNativeEngine,
        lang: str = "ar",
        parent=None,
        update_info: dict = None,
        just_updated: bool = False,
    ):
        super().__init__(parent)
        self.engine = engine
        self.is_ar = lang == "ar"
        self.T = (lambda ar, en: ar) if self.is_ar else (lambda ar, en: en)
        self.just_updated = just_updated
        self.info = update_info or {"hasUpdate": False, "latestVersion": APP_VERSION, "publishedAt": CHANGELOG_HISTORY[0]["date"]}
        self._updating = False

        self.setWindowTitle(
            self.T("تحديثات البرنامج وسجل الإضافات — Scorpion Download Manager", "Software Updates & What's New — Scorpion Download Manager")
        )
        self.resize(650, 560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        self.progress_sig.connect(self._on_progress)
        self.finished_sig.connect(self._on_finished)
        self.check_done_sig.connect(self._on_check_done)

        c = pal()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # 1) Top Banner Card
        banner = QFrame()
        banner.setObjectName("CardFrame")
        bl = QVBoxLayout(banner)
        bl.setContentsMargins(16, 14, 16, 14)
        bl.setSpacing(6)

        lead = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute) if self.is_ar else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        self.lbl_headline = QLabel()
        self.lbl_headline.setWordWrap(True)
        self.lbl_headline.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_headline.setStyleSheet("font-size: 16px; font-weight: 700;")
        bl.addWidget(self.lbl_headline)

        self.lbl_sub = QLabel()
        self.lbl_sub.setObjectName("Muted")
        self.lbl_sub.setWordWrap(True)
        self.lbl_sub.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
        bl.addWidget(self.lbl_sub)
        root.addWidget(banner)

        # 2) Release Notes ("What's New") Card
        notes_card = QFrame()
        notes_card.setObjectName("CardFrame")
        nl = QVBoxLayout(notes_card)
        nl.setContentsMargins(16, 14, 16, 14)
        nl.setSpacing(8)

        self.lbl_notes_title = QLabel()
        self.lbl_notes_title.setWordWrap(True)
        self.lbl_notes_title.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
        self.lbl_notes_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {c['accent']};")
        nl.addWidget(self.lbl_notes_title)

        self.notes_view = QTextBrowser()
        self.notes_view.setReadOnly(True)
        self.notes_view.setOpenExternalLinks(True)
        self.notes_view.setFrameShape(QFrame.Shape.NoFrame)
        self.notes_view.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        nl.addWidget(self.notes_view, 1)
        root.addWidget(notes_card, 1)

        # 3) Live Update Progress Card (shown during download/install)
        self.prog_card = QFrame()
        self.prog_card.setObjectName("CardFrame")
        pl = QVBoxLayout(self.prog_card)
        pl.setContentsMargins(16, 12, 16, 12)
        pl.setSpacing(6)
        self.lbl_prog = QLabel(self.T("جاري تحضير التحديث...", "Preparing update..."))
        self.lbl_prog.setStyleSheet("font-weight: 600;")
        self.prog_bar = QProgressBar()
        self.prog_bar.setRange(0, 100)
        self.prog_bar.setValue(0)
        self.prog_bar.setFixedHeight(20)
        pl.addWidget(self.lbl_prog)
        pl.addWidget(self.prog_bar)
        self.prog_card.setVisible(False)
        root.addWidget(self.prog_card)

        # 4) Bottom Action Buttons
        btns = QHBoxLayout()
        self.btn_check = QPushButton(self.T("فحص التحديثات الآن", "Check for Updates"))
        self.btn_check.setIcon(glyph_icon(ICONS["update"], c["text"]))
        self.btn_check.clicked.connect(self._check_now)
        btns.addWidget(self.btn_check)

        btns.addStretch()

        self.btn_close = QPushButton(self.T("إغلاق", "Close"))
        self.btn_close.clicked.connect(self._save_and_close)

        self.btn_update_now = QPushButton(self.T("تحديث البرنامج الآن", "Update Now"))
        self.btn_update_now.setObjectName("PrimaryBtn")
        self.btn_update_now.setIcon(glyph_icon(ICONS["download"], c["primary_text"]))
        self.btn_update_now.setMinimumWidth(165)
        self.btn_update_now.clicked.connect(self._start_update_now)

        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_update_now)
        root.addLayout(btns)

        self._refresh_view()
        if update_info is None and not just_updated and not is_msix_packaged():
            QTimer.singleShot(80, self._check_now)

    def _save_prefs(self):
        self.engine.settings["autoCheckUpdates"] = True
        self.engine.save_state()

    def _save_and_close(self):
        self._save_prefs()
        self.accept()

    def _refresh_view(self):
        c = pal()
        msix_mode = is_msix_packaged()
        has_upd = False if msix_mode else bool(self.info.get("hasUpdate"))
        error = "" if msix_mode else (self.info.get("error") or "").strip()
        if " / " in error:  # friendly errors are stored as "Arabic / English"
            error = error.split(" / ", 1)[0 if self.is_ar else 1]
        lat_ver = self.info.get("latestVersion") or APP_VERSION
        pub_date = self.info.get("publishedAt") or CHANGELOG_HISTORY[0]["date"]
        checked = self.info.get("checkedAt") or ""
        checked_txt = self.T(f"آخر فحص: {L(checked)}", f"Last checked: {checked}") if checked else ""
        self.btn_check.setVisible(not msix_mode)
        # "Update Now" only exists when there is something to install
        self.btn_update_now.setVisible(has_upd)
        if not self._updating:
            self.btn_update_now.setEnabled(has_upd)

        if msix_mode:
            headline, color = self.T(
                f"✅ الإصدار المثبّت من المتجر: {L('v' + APP_VERSION)}",
                f"✅ Microsoft Store Edition (v{APP_VERSION})",
            ), c["success"]
            sub = self.T(
                "تُدار التحديثات تلقائياً بواسطة متجر Microsoft Store.",
                "Updates are managed and delivered automatically by Microsoft Store.",
            )
        elif has_upd:
            headline, color = self.T(
                f"🚀 يتوفر تحديث جديد للبرنامج: الإصدار {L('v' + lat_ver)}",
                f"🚀 New Update Available: Version v{lat_ver}",
            ), c["accent"]
            sub = self.T(
                f"الإصدار الحالي على جهازك: {L('v' + APP_VERSION)}  •  تاريخ إصدار التحديث: {L(pub_date)}\n"
                "اضغط «تحديث البرنامج الآن» لتحميل وتثبيت التحديث تلقائياً وإعادة تشغيل البرنامج.",
                f"Current version: v{APP_VERSION}  •  Released: {pub_date}\n"
                "Click “Update Now” to download, install, and restart automatically.",
            )
        elif error:
            headline, color = self.T("⚠️ تعذر فحص التحديثات", "⚠️ Couldn't check for updates"), c["warn"]
            sub = self.T(
                f"الإصدار الحالي: {L('v' + APP_VERSION)}  •  السبب: {error[:160]}\n"
                "تأكد من الاتصال بالإنترنت ثم اضغط «فحص التحديثات الآن».",
                f"Current version: v{APP_VERSION}  •  Reason: {error[:160]}\n"
                "Check your internet connection, then click “Check for Updates”.",
            )
        elif self.just_updated:
            headline, color = self.T(
                f"🎉 تم تحديث البرنامج بنجاح إلى الإصدار {L('v' + APP_VERSION)}",
                f"🎉 Successfully Updated to Version v{APP_VERSION}!",
            ), c["success"]
            sub = self.T("إليك ما الجديد في هذا الإصدار:", "Here is what's new in this version:")
        else:
            headline, color = self.T(
                f"✅ برنامجك محدث إلى آخر إصدار ({L('v' + APP_VERSION)})",
                f"✅ Scorpion Download Manager is up to date (v{APP_VERSION})",
            ), c["success"]
            sub = checked_txt or self.T(f"الإصدار الحالي: {L('v' + APP_VERSION)}", f"Current version: v{APP_VERSION}")
        if checked_txt and sub != checked_txt:
            sub = f"{sub}\n{checked_txt}"
        self.lbl_headline.setText(headline)
        self.lbl_headline.setStyleSheet(f"font-size: 16px; font-weight: 700; color: {color};")
        self.lbl_sub.setText(sub)

        if has_upd:
            # Notes of the new version, as published on the server
            title_txt = self.info.get("title_ar" if self.is_ar else "title_en") or self.T(
                f"الإصدار {lat_ver}", f"Version {lat_ver}"
            )
            notes_list = self.info.get("changelog_ar" if self.is_ar else "changelog_en") or []
            history = []
        else:
            # Notes of the installed version, then every earlier version
            cur = CHANGELOG_HISTORY[0]
            title_txt = cur["title_ar" if self.is_ar else "title_en"]
            notes_list = cur["ar" if self.is_ar else "en"]
            history = CHANGELOG_HISTORY[1:]
        self.lbl_notes_title.setText(self.T(f"📋 ما الجديد في {title_txt}:", f"📋 What's New in {title_txt}:"))
        dir_attr = "rtl" if self.is_ar else "ltr"
        align_css = "right" if self.is_ar else "left"
        blocks = [
            f"<p style='margin: 0 0 7px 0;'>•&nbsp;&nbsp;{html.escape(str(line))}</p>"
            for line in notes_list
        ]
        for prev in history:
            hdr = html.escape(str(prev["title_ar" if self.is_ar else "title_en"]))
            dt = html.escape(str(prev["date"]))
            blocks.append(
                f"<div style='margin: 14px 0 8px 0; padding-top: 10px; border-top: 1px solid {c['border']}; "
                f"font-weight: 700; color: {c['accent']};'>{hdr} ({L(dt)})</div>"
            )
            for pline in prev["ar" if self.is_ar else "en"]:
                blocks.append(f"<p style='margin: 0 0 7px 0;'>•&nbsp;&nbsp;{html.escape(str(pline))}</p>")
        self.notes_view.setHtml(
            f"<div dir='{dir_attr}' style='text-align: {align_css}; font-family: \"Segoe UI\", Tahoma; "
            f"font-size: 13px; color: {c['text']}; line-height: 165%;'>{''.join(blocks)}</div>"
        )

    def _check_now(self):
        if self._updating:
            return
        self._save_prefs()
        self.btn_check.setEnabled(False)
        self.btn_check.setText(self.T("جاري الفحص...", "Checking..."))

        def worker():
            res = self.engine.check_for_updates()
            self.check_done_sig.emit(res)

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_done(self, res: dict):
        self.btn_check.setEnabled(True)
        self.btn_check.setText(self.T("فحص التحديثات الآن", "Check for Updates"))
        self.just_updated = False
        self.info = res
        self._refresh_view()

    def _start_update_now(self):
        if self._updating:
            return
        self._save_prefs()
        local_pkg = (self.info.get("localPackage") or "").strip()
        dl_url = (
            (self.info.get("downloadUrl") or "").strip()
            or "https://github.com/Mahmoud-847/scorpion-idm/raw/main/release/Scorpion-Update-Payload.zip"
        )
        self._run_update_from_path_or_url(
            local_pkg=local_pkg, dl_url=dl_url, expected_sha256=self.info.get("sha256") or ""
        )

    def _run_update_from_path_or_url(self, local_pkg: str = "", dl_url: str = "", expected_sha256: str = ""):
        self._updating = True
        self.prog_card.setVisible(True)
        self.btn_update_now.setEnabled(False)
        self.btn_check.setEnabled(False)
        self.prog_bar.setValue(2)
        self.lbl_prog.setText(self.T("جاري تجهيز وتثبيت التحديث...", "Downloading and installing update..."))

        def worker():
            try:
                target_pkg = local_pkg
                if not target_pkg and dl_url:
                    if not dl_url.lower().startswith("https://"):
                        raise ValueError("Update URL must use HTTPS")
                    ext = ".exe" if dl_url.lower().split("?")[0].endswith(".exe") else ".zip"
                    target_pkg = os.path.join(self.engine.temp_root, f"Scorpion_Update_Pkg{ext}")
                    os.makedirs(self.engine.temp_root, exist_ok=True)
                    with requests.get(
                        dl_url, headers={"User-Agent": BROWSER_UA}, stream=True, timeout=25
                    ) as r:
                        r.raise_for_status()
                        total = int(r.headers.get("Content-Length") or 0)
                        done = 0
                        with open(target_pkg, "wb") as f:
                            for chunk in r.iter_content(chunk_size=65536):
                                if not chunk:
                                    continue
                                f.write(chunk)
                                done += len(chunk)
                                if total > 0:
                                    pct = int(min(50, 50 * done / total))
                                    self.progress_sig.emit(
                                        pct,
                                        self.T(
                                            f"جاري تحميل التحديث... {L(format_bytes(done))} / {L(format_bytes(total))}",
                                            f"Downloading update... {format_bytes(done)} / {format_bytes(total)}",
                                        ),
                                    )
                self.progress_sig.emit(
                    55,
                    self.T(
                        "جاري تطبيق التحديث وتحديث الملفات وإعادة تشغيل البرنامج...",
                        "Applying update files and restarting Scorpion Download Manager...",
                    ),
                )
                ok, msg = self.engine.install_update_package(
                    target_pkg,
                    expected_sha256=expected_sha256,
                    progress_cb=lambda p: self.progress_sig.emit(
                        p,
                        self.T(
                            f"جاري تحديث ملفات البرنامج... {L(str(p) + '%')}",
                            f"Updating application files... {p}%",
                        ),
                    ),
                )
                self.finished_sig.emit(ok, msg)
            except requests.exceptions.RequestException:
                self.finished_sig.emit(
                    False, self.T("تعذر تحميل التحديث من خادم التحديثات", "Couldn't download the update from the update server")
                )
            except Exception as e:
                self.finished_sig.emit(False, str(e))

        threading.Thread(target=worker, daemon=True).start()

    def _on_progress(self, pct: int, text: str):
        self.prog_bar.setValue(pct)
        self.lbl_prog.setText(text)

    def _on_finished(self, ok: bool, msg: str):
        self._updating = False
        self.btn_update_now.setEnabled(bool(self.info.get("hasUpdate")))
        self.btn_check.setEnabled(True)
        if ok:
            self.prog_bar.setValue(100)
            if str(msg or "").startswith("installed_restart_failed"):
                self.lbl_prog.setText(
                    self.T(
                        "⚠️ اكتمل تثبيت التحديث بنجاح، لكن تعذّر إعادة التشغيل تلقائياً. أعد تشغيل البرنامج يدوياً.",
                        "⚠️ Update installed successfully, but automatic restart failed. Please restart Scorpion Download Manager manually.",
                    )
                )
            else:
                self.lbl_prog.setText(
                    self.T("✅ اكتمل التحديث! جاري إعادة تشغيل البرنامج الآن...", "✅ Update complete! Restarting now...")
                )
                QTimer.singleShot(400, self.accept)
        else:
            self.lbl_prog.setText(self.T(f"❌ تعذر التحديث: {msg}", f"❌ Update failed: {msg}"))


class TorrentFilesDialog(QDialog):
    """Lets the user choose which files of a multi-file torrent to download."""

    def __init__(self, item: dict, lang: str = "ar", parent=None):
        super().__init__(parent)
        self.item = item
        self.is_ar = lang == "ar"
        T = (lambda ar, en: ar) if self.is_ar else (lambda ar, en: en)
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowIcon(parent.windowIcon() if parent is not None and not parent.windowIcon().isNull() else scorpion_emblem_icon())
        self.setWindowTitle(T("اختيار ملفات التورنت", "Select torrent files") + f" — {item.get('filename', '')}")
        self.resize(680, 480)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.lbl_total = QLabel()
        self.lbl_total.setStyleSheet("font-weight: 700;")
        lay.addWidget(self.lbl_total)

        self.tree = QTreeWidget()
        self.tree.setObjectName("DialogTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderLabels([T("الملف", "File"), T("الحجم", "Size")])
        self.tree.setRootIsDecorated(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        for f in item.get("torrentFiles") or []:
            it = QTreeWidgetItem(self.tree, [f.get("path") or f"#{f.get('index')}", L(format_bytes(f.get("length") or 0))])
            it.setData(0, Qt.ItemDataRole.UserRole, int(f.get("index") or 0))
            it.setData(1, Qt.ItemDataRole.UserRole, int(f.get("length") or 0))
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(0, Qt.CheckState.Checked)
        self.tree.itemChanged.connect(lambda *_: self._update_total())
        lay.addWidget(self.tree, 1)

        row = QHBoxLayout()
        b_all = QPushButton(T("تحديد الكل", "Select all"))
        b_all.clicked.connect(lambda: self._set_all(True))
        b_none = QPushButton(T("إلغاء التحديد", "Select none"))
        b_none.clicked.connect(lambda: self._set_all(False))
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch()
        ok = QPushButton(T("بدء التحميل", "Start download"))
        ok.setObjectName("PrimaryBtn")
        ok.setMinimumWidth(140)
        ok.clicked.connect(self.accept)
        row.addWidget(ok)
        lay.addLayout(row)
        self._update_total()

    def _items(self):
        return [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]

    def _set_all(self, on: bool):
        for it in self._items():
            it.setCheckState(0, Qt.CheckState.Checked if on else Qt.CheckState.Unchecked)

    def _update_total(self):
        sel = [it for it in self._items() if it.checkState(0) == Qt.CheckState.Checked]
        size = sum(int(it.data(1, Qt.ItemDataRole.UserRole) or 0) for it in sel)
        if self.is_ar:
            self.lbl_total.setText(f"المحدد: {L(len(sel))} من {L(len(self._items()))} ملف — {L(format_bytes(size))}")
        else:
            self.lbl_total.setText(f"Selected: {len(sel)} of {len(self._items())} files — {format_bytes(size)}")

    def selected_indices(self) -> list:
        sel = [int(it.data(0, Qt.ItemDataRole.UserRole)) for it in self._items() if it.checkState(0) == Qt.CheckState.Checked]
        # Nothing selected means "everything"
        return sel or [int(it.data(0, Qt.ItemDataRole.UserRole)) for it in self._items()]


# ==============================================================================
# WINDOWS SHELL INTEGRATION (per-user, HKCU — no admin rights needed)
# ==============================================================================
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "ScorpionIDM"
TORRENT_PROGID = "ScorpionIDM.torrent"


def app_launch_command() -> str:
    """Command used by Windows to start Scorpion (only meaningful for the installed .exe)."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    return f'"{pyw if os.path.exists(pyw) else sys.executable}" "{os.path.abspath(__file__)}"'


def set_start_with_windows(enabled: bool):
    if os.name != "nt" or not INSTALLED or is_msix_packaged():
        return
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            if enabled:
                winreg.SetValueEx(k, APP_RUN_NAME, 0, winreg.REG_SZ, f"{app_launch_command()} --tray")
            else:
                try:
                    winreg.DeleteValue(k, APP_RUN_NAME)
                except FileNotFoundError:
                    pass
    except Exception:
        pass


def _reg_set(path: str, name, value: str):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, path) as k:
        winreg.SetValueEx(k, name, 0, winreg.REG_SZ, value)


def _reg_delete_tree(path: str):
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_ALL_ACCESS) as k:
            while True:
                try:
                    sub = winreg.EnumKey(k, 0)
                except OSError:
                    break
                _reg_delete_tree(path + "\\" + sub)
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
    except Exception:
        pass


def set_torrent_association(enabled: bool):
    """Registers Scorpion as handler for .torrent files and magnet: links (current user only)."""
    if os.name != "nt" or not INSTALLED or is_msix_packaged():
        return
    import winreg
    cmd = f'{app_launch_command()} "%1"'
    # The runtime exe carries Python's icon (changing it would break its signature), so point at ours
    scorpion_ico = os.path.join(RESOURCE_ROOT, "build", "icon.ico")
    icon = scorpion_ico if EMBEDDED_RUNTIME and os.path.isfile(scorpion_ico) else f"{sys.executable},0"
    try:
        if enabled:
            base = rf"Software\Classes\{TORRENT_PROGID}"
            _reg_set(base, "", "Torrent File (Scorpion Download Manager)")
            _reg_set(base + r"\DefaultIcon", "", icon)
            _reg_set(base + r"\shell\open\command", "", cmd)
            _reg_set(r"Software\Classes\.torrent", "", TORRENT_PROGID)
            _reg_set(r"Software\Classes\.torrent", "Content Type", "application/x-bittorrent")
            _reg_set(r"Software\Classes\.torrent\OpenWithProgids", TORRENT_PROGID, "")
            _reg_set(r"Software\Classes\magnet", "", "URL:Magnet Link")
            _reg_set(r"Software\Classes\magnet", "URL Protocol", "")
            _reg_set(r"Software\Classes\magnet\DefaultIcon", "", icon)
            _reg_set(r"Software\Classes\magnet\shell\open\command", "", cmd)
        else:
            _reg_delete_tree(rf"Software\Classes\{TORRENT_PROGID}")
            # Only remove handlers that still point to Scorpion
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\.torrent") as k:
                    if winreg.QueryValueEx(k, "")[0] == TORRENT_PROGID:
                        _reg_delete_tree(r"Software\Classes\.torrent")
            except Exception:
                pass
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Classes\magnet\shell\open\command") as k:
                    if "ScorpionIDM" in winreg.QueryValueEx(k, "")[0]:
                        _reg_delete_tree(r"Software\Classes\magnet")
            except Exception:
                pass
        import ctypes
        ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)  # SHCNE_ASSOCCHANGED
    except Exception:
        pass


def create_shortcut_native(lnk_path: str, target_path: str, work_dir: str, icon_path: str) -> bool:
    """Creates a Windows .lnk shortcut in pure Python via Win32 COM (IShellLinkW + IPersistFile)."""
    if os.name != "nt":
        return False
    import ctypes
    from ctypes import wintypes

    ole32 = ctypes.windll.ole32
    ole32.CoInitialize(None)
    try:
        class GUID(ctypes.Structure):
            _fields_ = [
                ("Data1", wintypes.DWORD),
                ("Data2", wintypes.WORD),
                ("Data3", wintypes.WORD),
                ("Data4", wintypes.BYTE * 8),
            ]

            def __init__(self, d1, d2, d3, d4):
                super().__init__(d1, d2, d3, (wintypes.BYTE * 8)(*d4))

        CLSID_ShellLink = GUID(0x00021401, 0x0000, 0x0000, [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])
        IID_IShellLinkW = GUID(0x000214F9, 0x0000, 0x0000, [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])
        IID_IPersistFile = GUID(0x0000010B, 0x0000, 0x0000, [0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])

        psl = ctypes.c_void_p()
        hr = ole32.CoCreateInstance(
            ctypes.byref(CLSID_ShellLink), None, 1, ctypes.byref(IID_IShellLinkW), ctypes.byref(psl)
        )
        if hr != 0 or not psl:
            return False

        vtbl = ctypes.cast(ctypes.cast(psl, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
        WSTRING_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR)
        ICON_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, ctypes.c_int)
        QI_FN = ctypes.WINFUNCTYPE(
            ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p)
        )
        REL_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)

        WSTRING_FN(vtbl[20])(psl, target_path)
        WSTRING_FN(vtbl[9])(psl, work_dir)
        WSTRING_FN(vtbl[7])(psl, "Scorpion Download Manager")
        ICON_FN(vtbl[17])(psl, icon_path, 0)

        ppf = ctypes.c_void_p()
        hr = QI_FN(vtbl[0])(psl, ctypes.byref(IID_IPersistFile), ctypes.byref(ppf))
        if hr == 0 and ppf:
            ppf_vtbl = ctypes.cast(
                ctypes.cast(ppf, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p)
            )
            SAVE_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.LPCWSTR, wintypes.BOOL)
            os.makedirs(os.path.dirname(lnk_path), exist_ok=True)
            SAVE_FN(ppf_vtbl[6])(ppf, lnk_path, True)
            REL_FN(ppf_vtbl[2])(ppf)

        REL_FN(vtbl[2])(psl)
        return os.path.exists(lnk_path)
    except Exception:
        return False
    finally:
        ole32.CoUninitialize()


def ensure_app_shortcuts(settings: dict):
    """Self-heals Start Menu and Desktop shortcuts whenever the installed app runs."""
    if os.name != "nt" or is_msix_packaged():
        return
    installed_exe = os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Programs", "ScorpionIDM", "ScorpionIDM.exe"
    )
    target_exe = sys.executable if INSTALLED else installed_exe
    if not os.path.exists(target_exe):
        return
    work_dir = os.path.dirname(target_exe)
    icon_path = os.path.join(work_dir, "build", "icon.ico")
    if not os.path.exists(icon_path):
        icon_path = target_exe

    force_refresh = settings.get("shortcutIconVer") != APP_VERSION
    start_lnk = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Scorpion Download Manager.lnk",
    )
    changed = False
    if force_refresh or not os.path.exists(start_lnk):
        if create_shortcut_native(start_lnk, target_exe, work_dir, icon_path):
            changed = True

    desktop_lnk = os.path.join(os.path.expanduser("~"), "Desktop", "Scorpion Download Manager.lnk")
    if settings.get("desktopShortcut", True) and (force_refresh or not os.path.exists(desktop_lnk)):
        if create_shortcut_native(desktop_lnk, target_exe, work_dir, icon_path):
            changed = True

    if force_refresh:
        settings["shortcutIconVer"] = APP_VERSION
    if changed:
        try:
            import ctypes

            ctypes.windll.shell32.SHChangeNotify(0x08000000, 0, None, None)
        except Exception:
            pass


def apply_shell_integration(settings: dict):
    set_start_with_windows(bool(settings.get("startWithWindows", True)))
    set_torrent_association(bool(settings.get("associateTorrents", True)))
    ensure_app_shortcuts(settings)
    # The browser bridge host is registered by the engine's extension sync (in the background at startup)


def apply_shell_integration_async(settings: dict):
    """Registry and shortcut work, off the window's thread."""
    threading.Thread(target=apply_shell_integration, args=(dict(settings),), daemon=True).start()


def item_mode(it: dict) -> str:
    st = it.get("status")
    if st == "completed":
        return "done"
    if st == "error":
        return "error"
    if st in ("paused", "queued", "scheduled"):
        return "paused"
    if st == "downloading":
        ph = it.get("phase")
        if ph in ("merging", "verifying", "saving"):
            return ph
        if ph in ("connecting", "selecting") or not it.get("downloadedBytes"):
            return "connecting"
    return "active"


def item_status_text(it: dict, is_ar: bool) -> str:
    m = item_mode(it)
    st = it.get("status")
    if st == "queued":
        return "في الانتظار" if is_ar else "Queued"
    if st == "scheduled":
        return "مجدول" if is_ar else "Scheduled"
    if m == "merging":
        return "جاري الدمج..." if is_ar else "Merging..."
    if m == "verifying":
        return "جاري التحقق..." if is_ar else "Verifying file..."
    if m == "saving":
        return "جاري الحفظ..." if is_ar else "Saving file..."
    if it.get("phase") == "selecting":
        return "اختيار الملفات" if is_ar else "Select files"
    if m == "connecting":
        if it.get("isTorrent"):
            return "البحث عن Peers" if is_ar else "Finding peers"
        if it.get("category") == "Music" or it.get("videoQuality") == "audio":
            return "تجهيز الصوت..." if is_ar else "Preparing audio..."
        if it.get("isVideo"):
            return "تجهيز الفيديو..." if is_ar else "Preparing video..."
        return "جاري الاتصال..." if is_ar else "Connecting..."
    return {
        "done": ("مكتمل", "Completed"),
        "error": ("فشل", "Failed"),
        "paused": ("متوقف", "Paused"),
        "active": ("جاري التحميل", "Downloading"),
    }[m][0 if is_ar else 1]


class DownloadCard(QWidget):
    """Compact corner progress card matching the obsidian reference UI without stealing focus."""

    action = pyqtSignal(str, str)  # download id, action

    W, H = 400, 114

    def __init__(self, dl_id: str, is_ar: bool):
        super().__init__(
            None, Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.dl_id, self.is_ar = dl_id, is_ar
        self.T = (lambda ar, en: ar) if is_ar else (lambda ar, en: en)
        self.hovered = False
        self.dismiss_at = None
        self.state = None
        self._lead_align = (
            (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
            if is_ar
            else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        )
        self.setFixedSize(self.W, self.H)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight)
        c = pal()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(6, 6, 6, 6)
        self.body = QFrame()
        self.body.setObjectName("ToastCard")
        self.body.setStyleSheet(
            f"#ToastCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 11px; }}"
            f"#ToastCard QLabel {{ background: transparent; }}"
        )
        outer.addWidget(self.body)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(14, 10, 12, 10)
        lay.setSpacing(5)

        # Row 1: Stage heading + Dismiss button (never cancels the download)
        top = QHBoxLayout()
        top.setSpacing(6)
        self.icon = QLabel()
        self.icon.setFixedSize(16, 16)
        top.addWidget(self.icon)
        self.lbl_stage = QLabel(self.T("جاري التحميل:", "Downloading:"))
        self.lbl_stage.setStyleSheet(f"color: {c['muted']}; font-size: 11.5px; font-weight: 500;")
        self.lbl_stage.setAlignment(self._lead_align | Qt.AlignmentFlag.AlignVCenter)
        top.addWidget(self.lbl_stage, 1)

        self.btn_close = QPushButton()
        self.btn_close.setObjectName("ToolBtn")
        self.btn_close.setFixedSize(22, 22)
        self.btn_close.setIcon(outline_icon("close", c["muted"], 11, 2.0))
        self.btn_close.setAccessibleName(self.T("إغلاق البطاقة", "Dismiss card"))
        self.btn_close.setToolTip(self.T("إخفاء البطاقة (يستمر التحميل)", "Dismiss card (download continues)"))
        self.btn_close.clicked.connect(lambda: self.action.emit(self.dl_id, "close"))
        top.addWidget(self.btn_close)
        lay.addLayout(top)

        # Row 2: Filename (clickable for full details) + optional error line
        self.name = QLabel()
        self.name.setAlignment(self._lead_align | Qt.AlignmentFlag.AlignVCenter)
        self.name.setStyleSheet(f"font-size: 13px; font-weight: 600; color: {c['text']};")
        lay.addWidget(self.name)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        self.status.setVisible(False)
        self.status.setAlignment(self._lead_align | Qt.AlignmentFlag.AlignVCenter)
        lay.addWidget(self.status)

        # Row 3: Glowing progress bar + percentage + contextual action button(s)
        prog_row = QHBoxLayout()
        prog_row.setSpacing(8)
        self.bar = SlimProgressBar()
        self.bar.setFixedHeight(6)
        prog_row.addWidget(self.bar, 1)

        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setStyleSheet(f"font-size: 12px; font-weight: 600; color: {c['text_sec']};")
        self.lbl_pct.setMinimumWidth(34)
        self.lbl_pct.setAlignment(Qt.AlignmentFlag.AlignCenter)
        prog_row.addWidget(self.lbl_pct)

        self.btn_a = QPushButton()
        self.btn_b = QPushButton()
        self.btn_c = QPushButton()
        for b in (self.btn_a, self.btn_b, self.btn_c):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(26)
            b.setStyleSheet("padding: 2px 11px; font-size: 11.5px; border-radius: 7px;")
            prog_row.addWidget(b)
        self.btn_a.clicked.connect(lambda: self.action.emit(self.dl_id, self.btn_a.property("act")))
        self.btn_b.clicked.connect(lambda: self.action.emit(self.dl_id, self.btn_b.property("act")))
        self.btn_c.clicked.connect(lambda: self.action.emit(self.dl_id, self.btn_c.property("act")))
        lay.addLayout(prog_row)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_anim)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.body.geometry())
        for expand, dy, alpha in ((5, 3, 18), (3, 2, 28), (1, 1, 40)):
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, alpha))
            p.drawRoundedRect(r.adjusted(-expand, -expand + dy, expand, expand + dy), 13, 13)

    def _tick_anim(self):
        if prefers_reduced_motion():
            self._anim_timer.stop()
            return
        if self.state in ("connecting", "active", "merging", "verifying", "saving"):
            self.bar.tick()
        else:
            self._anim_timer.stop()

    def _set_buttons(self, a: tuple, b: tuple, c: tuple | None = None, primary_a: bool = False, danger_c: bool = False):
        pal_c = pal()
        for btn, spec in ((self.btn_a, a), (self.btn_b, b), (self.btn_c, c)):
            if spec is None:
                btn.setVisible(False)
                btn.setText("")
                btn.setIcon(QIcon())
                btn.setProperty("act", "")
            else:
                text, act = spec
                btn.setVisible(True)
                if act == "cancel" and not text:
                    btn.setFixedWidth(26)
                    btn.setText("")
                    btn.setIcon(outline_icon("stop", "#FF6B2B", 11, 2.0))
                    btn.setAccessibleName(self.T("إلغاء التحميل", "Cancel download"))
                    btn.setToolTip(btn.accessibleName())
                else:
                    btn.setMinimumWidth(0)
                    btn.setMaximumWidth(160)
                    btn.setText(text)
                    btn.setIcon(QIcon())
                    btn.setAccessibleName(text)
                    btn.setToolTip("")
                btn.setProperty("act", act)
        self.btn_a.setObjectName("PrimaryBtn" if primary_a else "")
        self.btn_c.setObjectName("DangerBtn" if (c and danger_c) else "")
        for btn in (self.btn_a, self.btn_c):
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if primary_a:
            self.btn_a.setStyleSheet(f"background: {pal_c['primary_bg']}; color: {pal_c['primary_text']}; border: 1px solid {pal_c['primary_bg']}; padding: 2px 11px; font-size: 11.5px; border-radius: 7px; font-weight: 700;")
        else:
            self.btn_a.setStyleSheet("padding: 2px 11px; font-size: 11.5px; border-radius: 7px;")

    def update_from(self, item: dict):
        T = self.T
        c = pal()
        mode = item_mode(item)
        pct = 100.0 if item.get("status") == "completed" else float(item.get("progress") or 0)
        name = item.get("filename") or ""
        if getattr(self, "_full_name", None) != name:
            self._full_name = name
            self._elide_name()
            self.icon.setPixmap(scorpion_emblem_pixmap(16, small=True))

        # Stage title + border emphasis
        stage_labels = {
            "connecting": T("جاري الاتصال:", "Connecting:"),
            "active": T("جاري التحميل:", "Downloading:"),
            "merging": T("جاري الدمج:", "Finalizing (Merging):"),
            "verifying": T("جاري التحقق:", "Finalizing (Verifying):"),
            "saving": T("جاري الحفظ:", "Finalizing (Saving):"),
            "paused": T("متوقف مؤقتاً:", "Paused:"),
            "done": T("اكتمل التحميل:", "Completed:"),
            "error": T("تعذر التحميل:", "Download Failed:"),
        }
        stage_txt = stage_labels.get(mode, T("جاري التحميل:", "Downloading:"))
        spd = int(item.get("speed") or 0)
        if mode == "active" and spd > 0:
            stage_txt = f"{stage_txt}  {L(_fmt_speed_card(spd))}"
        self.lbl_stage.setText(stage_txt)

        if mode == "error":
            reason = localize_error_msg(item.get("errorMsg") or T("سبب غير معروف", "Unknown reason"), self.is_ar)
            if self.is_ar and not re.search(r"[؀-ۿ]", reason):
                reason = "⁦" + reason + "⁩"
            self.status.setVisible(True)
            self.status.setWordWrap(True)
            self.status.setStyleSheet(f"color: {c['danger']}; font-size: 11.5px;")
            self.status.setToolTip(reason)
            fm = self.status.fontMetrics()
            self.status.setText(fm.elidedText(reason, Qt.TextElideMode.ElideRight, max(240, self.W - 50) * 2))
            if self.height() != 136:
                self.setFixedSize(self.W, 136)
        else:
            if self.status.isVisible():
                self.status.setVisible(False)
            if self.height() != self.H:
                self.setFixedSize(self.W, self.H)

        self.lbl_pct.setText(L("100%") if mode == "done" else L(f"{pct:.0f}%"))
        self.bar.set_state(pct, mode)
        self.bar.tick()

        is_drm_err = mode == "error" and (
            is_drm_video_url(item.get("url", "")) or "drm" in str(item.get("errorMsg", "")).lower()
        )
        if mode != self.state:
            self.state = mode
            self.body.setStyleSheet(
                f"#ToastCard {{ background: {c['surface']}; "
                f"border: 1px solid {c['border_amber'] if mode in ('active', 'merging', 'verifying', 'saving') else (c['danger'] if mode == 'error' else c['border'])}; "
                f"border-radius: 11px; }}"
                f"#ToastCard QLabel {{ background: transparent; }}"
            )
            if self.isVisible() and mode in ("connecting", "active", "merging", "verifying", "saving") and not prefers_reduced_motion():
                if not self._anim_timer.isActive():
                    self._anim_timer.start(40)
            else:
                self._anim_timer.stop()
            browser_owned = item.get("browserTransfer")
            if is_drm_err or (browser_owned and mode == "error"):
                self._set_buttons((T("التفاصيل", "Details"), "details"), None, None)
                self.dismiss_at = time.time() + 15
            elif browser_owned and mode != "done":
                self._set_buttons((T("التفاصيل", "Details"), "details"), None, ("", "cancel"))
                self.dismiss_at = None
            elif mode == "done":
                self._set_buttons(
                    (T("تشغيل", "Open"), "open"),
                    (T("المجلد", "Folder"), "folder"),
                    None,
                    primary_a=True,
                )
                self.dismiss_at = time.time() + 6
            elif mode == "error":
                self._set_buttons((T("إعادة", "Retry"), "retry"), None, ("", "cancel"), primary_a=True)
                self.dismiss_at = time.time() + 15
            elif mode == "paused":
                self._set_buttons((T("استئناف", "Resume"), "resume"), None, ("", "cancel"), primary_a=True)
                self.dismiss_at = None
            else:
                self._set_buttons((T("إيقاف مؤقت", "Pause"), "pause"), None, ("", "cancel"))
                self.dismiss_at = None
        if mode in ("connecting", "active", "merging", "verifying", "saving"):
            self.btn_a.setEnabled(mode not in ("merging", "verifying", "saving"))
        else:
            self.btn_a.setEnabled(True)

    def _elide_name(self):
        if self.name.width() > 20:
            _elide_filename(self.name, self._full_name)
        else:
            self.name.setText(bidi_filename(self._full_name))

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._elide_name)
        if self.state in ("connecting", "active", "merging", "verifying", "saving") and not prefers_reduced_motion():
            if not self._anim_timer.isActive():
                self._anim_timer.start(40)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._anim_timer.stop()

    def due(self) -> bool:
        return bool(self.dismiss_at) and not self.hovered and time.time() >= self.dismiss_at

    def enterEvent(self, event):
        self.hovered = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered = False
        if self.dismiss_at:
            self.dismiss_at = max(self.dismiss_at, time.time() + 3)
        super().leaveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.action.emit(self.dl_id, "details")
        super().mouseReleaseEvent(event)


def _fmt_speed_card(bps: int) -> str:
    return format_speed(bps)


class DownloadCardManager(QObject):
    """Stacks download cards in the bottom-right screen corner without stealing focus."""

    MAX = 3

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.cards = {}
        self._anims = []

    def show_for(self, dl_id: str):
        item = self.win.engine.downloads.get(dl_id)
        if not item:
            return
        card = self.cards.get(dl_id)
        if card is None:
            card = DownloadCard(dl_id, self.win.lang == "ar")
            card.action.connect(self._on_action)
            self.cards[dl_id] = card
            card.update_from(item)
            self._layout(new=card)
        else:
            card.update_from(item)

    def remove(self, dl_id: str):
        card = self.cards.pop(dl_id, None)
        if card is None:
            return
        if prefers_reduced_motion():
            card.close()
            card.deleteLater()
            self._layout()
            return
        anim = QPropertyAnimation(card, b"windowOpacity", self)
        anim.setDuration(160)
        anim.setStartValue(card.windowOpacity())
        anim.setEndValue(0.0)
        anim.finished.connect(card.close)
        anim.finished.connect(card.deleteLater)
        self._keep(anim)
        self._layout()

    def clear(self):
        for dl_id in list(self.cards):
            self.remove(dl_id)

    def refresh(self):
        for dl_id, card in list(self.cards.items()):
            item = self.win.engine.downloads.get(dl_id)
            if not item:
                self.remove(dl_id)
                continue
            card.update_from(item)
            if card.due():
                self.remove(dl_id)

    def _keep(self, anim):
        self._anims = [a for a in self._anims if a.state() == QPropertyAnimation.State.Running] + [anim]
        anim.start()

    def _layout(self, new=None):
        avail = QApplication.primaryScreen().availableGeometry()
        visible = list(self.cards.values())[-self.MAX:]
        for card in list(self.cards.values())[: -self.MAX] if len(self.cards) > self.MAX else []:
            card.hide()
        y_cursor = avail.bottom() - 8
        for card in reversed(visible):
            ch = card.height() or card.H
            target = QPoint(avail.right() - card.W - 8, y_cursor - ch)
            y_cursor = target.y() - 6
            if prefers_reduced_motion():
                card.setWindowOpacity(1.0)
                card.move(target)
                card.show()
                continue
            if card is new:
                card.setWindowOpacity(0.0)
                card.move(target + QPoint(0, 14))
                card.show()
                fade = QPropertyAnimation(card, b"windowOpacity", self)
                fade.setDuration(180)
                fade.setStartValue(0.0)
                fade.setEndValue(1.0)
                self._keep(fade)
            elif not card.isVisible():
                card.setWindowOpacity(1.0)
                card.move(target)
                card.show()
            slide = QPropertyAnimation(card, b"pos", self)
            slide.setDuration(220)
            slide.setStartValue(card.pos())
            slide.setEndValue(target)
            slide.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._keep(slide)

    def _on_action(self, dl_id: str, act: str):
        eng = self.win.engine
        item = eng.downloads.get(dl_id) or {}
        path = item.get("filePath") or ""
        if act == "close":
            self.remove(dl_id)
        elif act == "details":
            self.remove(dl_id)
            self.win.open_progress_window(dl_id)
        elif act == "pause":
            eng.pause_download(dl_id)
        elif act == "cancel":
            if getattr(self, "_confirming_cancel", False):
                return
            if item.get("status") not in ("completed", "error") and int(item.get("downloadedBytes") or 0) > 0:
                is_ar = self.win.lang == "ar"
                card = self.cards.get(dl_id)
                self._confirming_cancel = True
                try:
                    if card is not None:
                        card.hide()
                    confirmed = confirm_action_dialog(
                        "إلغاء التحميل" if is_ar else "Cancel download",
                        (
                            f"إلغاء وحذف «{item.get('filename', '')}»؟\nسيتم حذف الأجزاء المحمّلة."
                            if is_ar
                            else f"Cancel and remove “{item.get('filename', '')}”?\nDownloaded parts will be discarded."
                        ),
                        is_ar,
                    )
                finally:
                    self._confirming_cancel = False
                if not confirmed:
                    if card is not None and dl_id in self.cards:
                        card.show()
                        card.raise_()
                    return
            dlg = self.win.open_progress_dialogs.pop(dl_id, None)
            if dlg is not None:
                dlg.close()
            self.remove(dl_id)
            eng.delete_download(dl_id)
            self.win.refresh_all()
        elif act in ("resume", "retry"):
            if item.get("status") == "error":
                item["status"] = "paused"
            eng.start_download(dl_id)
        elif act == "open" and os.path.exists(path):
            os.startfile(path)
            self.remove(dl_id)
        elif act == "folder" and os.path.exists(path):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            self.remove(dl_id)


class TaskbarProgress:
    """Progress on the app's taskbar button (ITaskbarList3), like Windows shows while copying files."""

    NOPROGRESS, INDETERMINATE, NORMAL, ERROR, PAUSED = 0, 1, 2, 4, 8

    def __init__(self):
        self._tbl = None
        self._last = None
        if os.name != "nt":
            return
        try:
            import ctypes
            from ctypes import wintypes

            class GUID(ctypes.Structure):
                _fields_ = [("Data1", wintypes.DWORD), ("Data2", wintypes.WORD), ("Data3", wintypes.WORD),
                            ("Data4", wintypes.BYTE * 8)]

                def __init__(self, d1, d2, d3, d4):
                    super().__init__(d1, d2, d3, (wintypes.BYTE * 8)(*d4))

            clsid = GUID(0x56FDF344, 0xFD6D, 0x11D0, [0x95, 0x8A, 0x00, 0x60, 0x97, 0xC9, 0xA0, 0x90])
            iid = GUID(0xEA1AFB91, 0x9E28, 0x4B86, [0x90, 0xE9, 0x9E, 0x9F, 0x8A, 0x5E, 0xEF, 0xAF])
            ptr = ctypes.c_void_p()
            if ctypes.windll.ole32.CoCreateInstance(ctypes.byref(clsid), None, 1, ctypes.byref(iid), ctypes.byref(ptr)) != 0:
                return
            vtbl = ctypes.cast(ctypes.cast(ptr, ctypes.POINTER(ctypes.c_void_p))[0], ctypes.POINTER(ctypes.c_void_p))
            ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)(vtbl[3])(ptr)  # HrInit
            self._set_value = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_ulonglong, ctypes.c_ulonglong)(vtbl[9])
            self._set_state = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, wintypes.HWND, ctypes.c_int)(vtbl[10])
            self._tbl = ptr
        except Exception:
            self._tbl = None

    def update(self, hwnd: int, state: int, done: int = 0, total: int = 0):
        if not self._tbl or not hwnd:
            return
        key = (hwnd, state, done * 1000 // total if total else 0)
        if key == self._last:
            return
        self._last = key
        try:
            self._set_state(self._tbl, hwnd, state)
            if state in (self.NORMAL, self.PAUSED, self.ERROR) and total:
                self._set_value(self._tbl, hwnd, int(done), int(total))
        except Exception:
            pass


# ==============================================================================
# MAIN NATIVE DESKTOP APPLICATION WINDOW (SCORPION IDM)
# ==============================================================================
class ScorpionMainWindow(QMainWindow):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        self.engine = ScorpionNativeEngine()
        self.theme = self.engine.settings.get("theme", "dark")
        self.lang = self.engine.settings.get("lang", "ar")
        self.filter_state = "all"
        self.filter_cat = "ALL"
        self.open_progress_dialogs = {}
        self._expanded_torrents: set[str] = set()
        self._expanded_panels: dict[str, TorrentInlinePanel] = {}
        self._free_space_cache = (0.0, 0)
        self.cards = DownloadCardManager(self)
        self.taskbar = TaskbarProgress()
        self._seen_status = {}
        self._tray_badge_count = None
        self._edge_cursor_active = False

        self.setWindowFlags(
            Qt.WindowType.Window
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowMinMaxButtonsHint
            | Qt.WindowType.WindowSystemMenuHint
        )
        self.setMinimumSize(640, 480)
        self.setMouseTracking(True)

        self.app_icon = scorpion_emblem_icon()
        if self.app_icon.isNull():
            icon_path = os.path.join(RESOURCE_ROOT, "build", "icon.ico")
            self.app_icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        if not self.app_icon.isNull():
            self.setWindowIcon(self.app_icon)

        avail = QApplication.primaryScreen().availableGeometry()
        self.resize(min(980, avail.width() - 40), min(680, avail.height() - 40))
        self.setup_ui()
        self.setup_tray()
        self.apply_theme_and_lang()
        self._restore_window_geometry()
        apply_win32_window_effects(self, self.theme == "dark")

        # Clipboard monitoring for direct links
        self.clipboard = QApplication.clipboard()
        self.last_clip = self.clipboard.text().strip()
        self.clipboard.dataChanged.connect(self.on_clipboard_changed)

        # UI refresh timer (250ms)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_refresh_tick)
        self.timer.start(250)

        self.engine.signals.completed.connect(self.on_download_completed)
        self.engine.signals.browser_captured.connect(self.on_browser_captured)
        self.engine.signals.focus_requested.connect(self.bring_to_front)
        self.engine.signals.torrent_files_ready.connect(self.on_torrent_files_ready)
        self.engine.signals.lang_changed.connect(self._on_remote_lang_changed)
        self.engine.signals.quit_requested.connect(self.quit_app)
        self.engine.signals.update_available.connect(self._on_update_available)
        apply_shell_integration_async(self.engine.settings)

        if not self.engine.settings.get("connectedBrowsers") and not self.engine.settings.get("wizardShownOnce"):
            self.engine.settings["wizardShownOnce"] = True
            self.engine.save_state()
            QTimer.singleShot(900, self.open_browser_setup_dialog)
        elif self.engine.settings.get("lastSeenVersion") != APP_VERSION:
            self.engine.settings["lastSeenVersion"] = APP_VERSION
            self.engine.save_state()
            QTimer.singleShot(700, lambda: self.open_update_dialog(just_updated=True))

        if self.engine.settings.get("autoCheckUpdates", True):
            QTimer.singleShot(3000, self._background_check_updates)
        self.engine._ui_platform = QApplication.platformName()
        self.engine._ui_ready = True
        self.app.installEventFilter(self)

    def _hit_resize_edges(self, global_pos) -> Qt.Edge:
        if not self.isVisible() or self.isMaximized() or self.isMinimized():
            return Qt.Edge(0)
        lp = self.mapFromGlobal(global_pos)
        x, y, w, h = lp.x(), lp.y(), self.width(), self.height()
        if x < 0 or y < 0 or x >= w or y >= h:
            return Qt.Edge(0)
        bw = 6
        edges = Qt.Edge(0)
        if x < bw:
            edges |= Qt.Edge.LeftEdge
        elif x >= w - bw:
            edges |= Qt.Edge.RightEdge
        if y < bw:
            edges |= Qt.Edge.TopEdge
        elif y >= h - bw:
            edges |= Qt.Edge.BottomEdge
        return edges

    def _set_edge_cursor(self, shape):
        if shape is None:
            if getattr(self, "_edge_cursor_active", False):
                QApplication.restoreOverrideCursor()
                self._edge_cursor_active = False
            return
        if getattr(self, "_edge_cursor_active", False):
            QApplication.changeOverrideCursor(shape)
        else:
            QApplication.setOverrideCursor(shape)
            self._edge_cursor_active = True

    def eventFilter(self, obj, event):
        etype = event.type()
        if etype not in (QEvent.Type.MouseMove, QEvent.Type.MouseButtonPress, QEvent.Type.Leave):
            return False
        try:
            if not isinstance(obj, QWidget) or obj.window() is not self:
                return False
            if etype == QEvent.Type.Leave:
                if obj is self:
                    self._set_edge_cursor(None)
                return False
            if self.isMaximized() or not self.isVisible():
                self._set_edge_cursor(None)
                return False
            edges = self._hit_resize_edges(event.globalPosition().toPoint())
            if etype == QEvent.Type.MouseMove:
                if event.buttons() != Qt.MouseButton.NoButton or not edges:
                    self._set_edge_cursor(None)
                elif (edges == (Qt.Edge.LeftEdge | Qt.Edge.TopEdge)) or (edges == (Qt.Edge.RightEdge | Qt.Edge.BottomEdge)):
                    self._set_edge_cursor(Qt.CursorShape.SizeFDiagCursor)
                elif (edges == (Qt.Edge.RightEdge | Qt.Edge.TopEdge)) or (edges == (Qt.Edge.LeftEdge | Qt.Edge.BottomEdge)):
                    self._set_edge_cursor(Qt.CursorShape.SizeBDiagCursor)
                elif edges & (Qt.Edge.LeftEdge | Qt.Edge.RightEdge):
                    self._set_edge_cursor(Qt.CursorShape.SizeHorCursor)
                else:
                    self._set_edge_cursor(Qt.CursorShape.SizeVerCursor)
                return False
            if etype == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and edges:
                wh = self.windowHandle()
                if wh is not None:
                    self._set_edge_cursor(None)
                    if wh.startSystemResize(edges):
                        return True
        except Exception:
            pass
        return False

    def changeEvent(self, event):
        if event.type() == event.Type.WindowStateChange and hasattr(self, "title_bar"):
            self.title_bar.refresh_max_icon()
        super().changeEvent(event)

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip(f"Scorpion Download Manager v{APP_VERSION}")
        self._rebuild_tray_menu()
        self.tray_icon.activated.connect(
            lambda reason: self.bring_to_front()
            if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick)
            else None
        )
        self.tray_icon.show()

    def _rebuild_tray_menu(self):
        if getattr(self, "tray_icon", None) is None:
            return
        is_ar = self.lang == "ar"
        tray_menu = QMenu(self)
        for text, slot in [
            ("إظهار البرنامج" if is_ar else "Show Scorpion Download Manager", self.bring_to_front),
            ("إضافة رابط" if is_ar else "Add URL", lambda: self.open_add_dialog("", False)),
            ("ربط المتصفحات" if is_ar else "Browser Integration", self.open_browser_setup_dialog),
            ("التحديثات وسجل الإضافات" if is_ar else "Updates & What's New", self.open_update_dialog),
            ("الإعدادات" if is_ar else "Settings", self.open_settings_dialog),
            (None, None),
            ("خروج" if is_ar else "Exit", self.quit_app),
        ]:
            if text is None:
                tray_menu.addSeparator()
                continue
            act = QAction(text, self)
            act.triggered.connect(slot)
            tray_menu.addAction(act)
        self.tray_icon.setContextMenu(tray_menu)

    def bring_to_front(self):
        self.show()
        self.setWindowState((self.windowState() & ~Qt.WindowState.WindowMinimized) | Qt.WindowState.WindowActive)
        self.raise_()
        self.activateWindow()
        if os.name == "nt" and QApplication.platformName() == "windows":
            try:
                import ctypes

                hwnd = int(self.winId())
                u32 = ctypes.windll.user32
                swp = 0x0001 | 0x0002 | 0x0040  # SWP_NOSIZE | SWP_NOMOVE | SWP_SHOWWINDOW
                u32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, swp)
                u32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, swp)
                u32.SetForegroundWindow(hwnd)
            except Exception:
                pass
        self.refresh_all()

    def setup_ui(self):
        central = QWidget()
        central.setObjectName("MainShell")
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Custom Reference Title Bar + Menu Bar Row
        self.title_bar = ScorpionTitleBar(self)
        root_layout.addWidget(self.title_bar)

        menu_row = QFrame()
        menu_row.setObjectName("MenuRowBar")
        menu_row.setFixedHeight(BRAND_TOKENS["menubar_h"])
        mr_lay = QHBoxLayout(menu_row)
        mr_lay.setContentsMargins(6, 0, 12, 0)
        mr_lay.setSpacing(0)
        self.menu_bar = QMenuBar()
        self.menu_bar.setObjectName("TopMenuBar")
        self.menu_bar.setNativeMenuBar(False)
        mr_lay.addWidget(self.menu_bar)
        mr_lay.addStretch(1)
        root_layout.addWidget(menu_row)

        # 2. Body: Left Navigation Sidebar + Main Download Cards Column
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(0)

        self.sidebar_frame = QFrame()
        self.sidebar_frame.setObjectName("SidebarPanel")
        self.sidebar_frame.setFixedWidth(BRAND_TOKENS["sidebar_w_full"])
        sb_lay = QVBoxLayout(self.sidebar_frame)
        sb_lay.setContentsMargins(14, 14, 14, 12)
        sb_lay.setSpacing(10)

        self.txt_search = QLineEdit()
        self.txt_search.setObjectName("SidebarSearch")
        self.txt_search.setClearButtonEnabled(True)
        self.txt_search.setMinimumHeight(34)
        self._search_act = self.txt_search.addAction(
            outline_icon("search", pal()["muted"], 14),
            QLineEdit.ActionPosition.TrailingPosition,
        )
        self.txt_search.textChanged.connect(lambda _t: self.refresh_all())
        sb_lay.addWidget(self.txt_search)

        sb_lay.addSpacing(2)
        self.lbl_categories = QLabel("Categories")
        self.lbl_categories.setObjectName("CategoriesHdr")
        sb_lay.addWidget(self.lbl_categories)

        self.tree = QTreeWidget()
        self.tree.setObjectName("SidebarTree")
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(0)
        self.tree.setMouseTracking(True)
        self.tree.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.tree.setItemDelegate(SidebarDelegate(self.tree))
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().resizeSection(1, 32)
        self.tree.itemClicked.connect(self.on_tree_clicked)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self.on_tree_clicked(cur))
        sb_lay.addWidget(self.tree, 1)

        self.btn_ext_status = QPushButton()
        self.btn_ext_status.setObjectName("ExtStatusPill")
        self.btn_ext_status.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_ext_status.setIconSize(QSize(16, 16))
        self.btn_ext_status.clicked.connect(self.open_browser_setup_dialog)
        sb_lay.addWidget(self.btn_ext_status)
        bl.addWidget(self.sidebar_frame)

        # Right content column
        content_col = QWidget()
        cl = QVBoxLayout(content_col)
        cl.setContentsMargins(18, 14, 18, 10)
        cl.setSpacing(12)

        toolbar = QFrame()
        toolbar.setObjectName("ToolbarFrame")
        toolbar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        toolbar.setMinimumWidth(0)
        self._toolbar_frame = toolbar
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(0, 0, 0, 2)
        tb.setSpacing(8)

        self._toolbar_buttons = []

        def tool(name, slot, primary=False, add_to_bar=True):
            b = QPushButton()
            b.setObjectName("PrimaryBtn" if primary else "ToolbarSecondaryBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIconSize(QSize(15, 15))
            b.setFixedHeight(BRAND_TOKENS["control_h"])
            b.clicked.connect(slot)
            setattr(self, name, b)
            if add_to_bar:
                self._toolbar_buttons.append(b)
                tb.addWidget(b)
            else:
                b.setParent(self)
                b.hide()
            return b

        tool("btn_add", lambda: self.open_add_dialog("", False), primary=True, add_to_bar=True)
        tool("btn_start_all", self.start_all_downloads, primary=False, add_to_bar=True)
        tool("btn_stop_all", self._pause_all_clicked, primary=False, add_to_bar=True)
        tool("btn_scheduler", self.open_queue_scheduler_dialog, primary=False, add_to_bar=True)
        tool("btn_settings", self.open_settings_dialog, primary=False, add_to_bar=True)
        tb.addStretch(1)

        tool("btn_video", lambda: self.open_add_dialog("", True), add_to_bar=False)
        tool("btn_torrent", lambda: self.open_add_dialog("", False, True), add_to_bar=False)
        tool("btn_resume", self.resume_selected, add_to_bar=False)
        tool("btn_pause", self.pause_selected, add_to_bar=False)
        tool("btn_delete", self.delete_selected, add_to_bar=False)
        tool("btn_clear_done", self.clear_completed, add_to_bar=False)
        tool("btn_browser_setup", self.open_browser_setup_dialog, add_to_bar=False)
        tool("btn_updates", self.open_update_dialog, add_to_bar=False)
        tool("btn_theme", self.toggle_theme, add_to_bar=False)
        tool("btn_lang", self.toggle_lang, add_to_bar=False)

        cl.addWidget(toolbar)

        self.queue_banner = QFrame()
        self.queue_banner.setObjectName("CardFrame")
        qbl = QHBoxLayout(self.queue_banner)
        qbl.setContentsMargins(14, 10, 14, 10)
        qbl.setSpacing(10)
        self.lbl_queue_info = QLabel()
        self.lbl_queue_info.setStyleSheet("font-size: 12.5px; font-weight: 500;")
        qbl.addWidget(self.lbl_queue_info, 1)
        self.btn_open_queue_mgr = QPushButton()
        self.btn_open_queue_mgr.setObjectName("PrimaryBtn")
        self.btn_open_queue_mgr.setFixedHeight(30)
        self.btn_open_queue_mgr.clicked.connect(self.open_queue_scheduler_dialog)
        qbl.addWidget(self.btn_open_queue_mgr)
        self.queue_banner.setVisible(False)
        cl.addWidget(self.queue_banner)

        self.stack = QStackedWidget()
        self.table = DownloadCardTableWidget()
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setTextElideMode(Qt.TextElideMode.ElideMiddle)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.table.setVerticalScrollMode(QTableWidget.ScrollMode.ScrollPerPixel)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(BRAND_TOKENS["card_h"] + BRAND_TOKENS["card_gap"])
        hh = self.table.horizontalHeader()
        hh.setVisible(False)
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 6):
            self.table.setColumnHidden(col, True)
        self.table.setItemDelegateForColumn(0, DownloadCardRowDelegate(self.table, self))
        self.table.card_action.connect(self._on_card_action)
        self.table.itemSelectionChanged.connect(self._sync_toolbar_selection)
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)
        self.table.cellPressed.connect(lambda _r, _c: self.txt_search.clearFocus())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.stack.addWidget(self.table)

        empty_card = QFrame()
        empty_card.setObjectName("CardFrame")
        el = QVBoxLayout(empty_card)
        el.setSpacing(12)
        el.addStretch(1)
        empty_emblem = QLabel()
        empty_emblem.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_emblem.setPixmap(scorpion_emblem_pixmap(56))
        el.addWidget(empty_emblem)
        self.empty_label = QLabel()
        self.empty_label.setObjectName("EmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        el.addWidget(self.empty_label)
        empty_cta_row = QHBoxLayout()
        empty_cta_row.addStretch()
        self.btn_empty_add = QPushButton()
        self.btn_empty_add.setObjectName("PrimaryBtn")
        self.btn_empty_add.setFixedHeight(34)
        self.btn_empty_add.clicked.connect(lambda: self.open_add_dialog("", False))
        empty_cta_row.addWidget(self.btn_empty_add)
        empty_cta_row.addStretch()
        el.addLayout(empty_cta_row)
        el.addStretch(1)
        self.stack.addWidget(empty_card)

        cl.addWidget(self.stack, 1)
        bl.addWidget(content_col, 1)
        root_layout.addWidget(body, 1)

        # 3. Bottom Aggregate Status Strip
        self.status_strip_frame = QFrame()
        self.status_strip_frame.setObjectName("StatusStripFrame")
        st_lay = QHBoxLayout(self.status_strip_frame)
        st_lay.setContentsMargins(0, 0, 0, 0)
        st_lay.setSpacing(0)
        self.lbl_status_bar = QLabel()
        self.lbl_status_bar.setObjectName("StatusBar")
        st_lay.addWidget(self.lbl_status_bar, 1)
        root_layout.addWidget(self.status_strip_frame)

        self.nav_items = {}
        self._setup_shortcuts()

    def _rebuild_menu_bar(self):
        if not hasattr(self, "menu_bar"):
            return
        is_ar = self.lang == "ar"
        T = (lambda ar, en: ar) if is_ar else (lambda ar, en: en)
        self.menu_bar.clear()

        m_file = self.menu_bar.addMenu(T("ملف", "File"))
        m_file.addAction(T("إضافة رابط جديد\tCtrl+N", "Add URL\tCtrl+N"), lambda: self.open_add_dialog("", False))
        m_file.addAction(T("سحب فيديو من رابط", "Grab Video URL"), lambda: self.open_add_dialog("", True))
        m_file.addAction(T("إضافة ملف تورنت / Magnet", "Add Torrent / Magnet"), lambda: self.open_add_dialog("", False, True))
        m_file.addAction(T("لصق من الحافظة\tCtrl+V", "Paste URL from Clipboard\tCtrl+V"), self._paste_shortcut)
        m_file.addSeparator()
        m_file.addAction(T("خروج", "Exit"), self.quit_app)

        m_edit = self.menu_bar.addMenu(T("تحرير", "Edit"))
        m_edit.addAction(T("بحث في التحميلات\tCtrl+F", "Find Downloads\tCtrl+F"), lambda: (self.txt_search.setFocus(), self.txt_search.selectAll()))
        m_edit.addSeparator()
        m_edit.addAction(T("استئناف المحدد", "Resume Selected"), self.resume_selected)
        m_edit.addAction(T("إيقاف مؤقت للمحدد", "Pause Selected"), self.pause_selected)
        m_edit.addAction(T("حذف المحدد\tDel", "Delete Selected\tDel"), self.delete_selected)
        m_edit.addAction(T("مسح المكتمل", "Clear Completed"), self.clear_completed)

        m_view = self.menu_bar.addMenu(T("عرض", "View"))
        m_view.addAction(
            T("الوضع الداكن", "Dark Mode") if self.theme == "light" else T("الوضع الفاتح", "Light Mode"),
            self.toggle_theme,
        )
        m_view.addAction("English" if is_ar else "العربية", self.toggle_lang)
        m_view.addSeparator()
        m_view.addAction(T("كل التحميلات", "All Downloads"), lambda: self._set_nav_filter("all", "ALL"))
        m_view.addAction(T("غير المكتملة", "Unfinished"), lambda: self._set_nav_filter("unfinished", "ALL"))
        m_view.addAction(T("المكتملة", "Completed"), lambda: self._set_nav_filter("completed", "ALL"))

        m_queue = self.menu_bar.addMenu(T("الطابور", "Queue"))
        m_queue.addAction(T("بدء جميع التحميلات", "Start All"), self.start_all_downloads)
        m_queue.addAction(T("إيقاف جميع التحميلات", "Pause All"), self._pause_all_clicked)
        m_queue.addSeparator()
        m_queue.addAction(T("إدارة الطوابير والجدولة...", "Queues & Scheduler Manager..."), self.open_queue_scheduler_dialog)

        m_tools = self.menu_bar.addMenu(T("أدوات", "Tools"))
        m_tools.addAction(T("معالج ربط المتصفحات...", "Browser Integration Wizard..."), self.open_browser_setup_dialog)
        m_tools.addAction(T("الإعدادات...", "Settings..."), self.open_settings_dialog)

        m_help = self.menu_bar.addMenu(T("مساعدة", "Help"))
        m_help.addAction(T("فحص التحديثات وسجل الإصدارات...", "Updates & Release Notes..."), self.open_update_dialog)
        def _open_privacy():
            import webbrowser
            webbrowser.open("https://github.com/Mahmoud-847/scorpion-idm/blob/main/PRIVACY.md")
        m_help.addAction(T("سياسة الخصوصية", "Privacy Policy"), _open_privacy)
        m_help.addSeparator()
        m_help.addAction(T("حول Scorpion Download Manager", "About Scorpion Download Manager"), self._show_about_dialog)

    def _set_nav_filter(self, state: str, cat: str):
        self.filter_state, self.filter_cat = state, cat
        for _k, it in self.nav_items.items():
            if it.data(0, Qt.ItemDataRole.UserRole) == (state, cat):
                self._rebuilding_tree = True
                try:
                    self.tree.setCurrentItem(it)
                finally:
                    self._rebuilding_tree = False
                break
        self.refresh_all()

    def _show_about_dialog(self):
        is_ar = self.lang == "ar"
        QMessageBox.information(
            self,
            "Scorpion Download Manager",
            (
                f"Scorpion Download Manager v{APP_VERSION}\n"
                "مدير تحميلات سريع متعدد القنوات ومتكامل مع المتصفح والتورنت."
                if is_ar
                else f"Scorpion Download Manager v{APP_VERSION}\nFast multi-connection, browser, and torrent download manager."
            ),
        )

    def start_all_downloads(self):
        with self.engine.lock:
            ids = [
                it["id"]
                for it in self.engine.downloads.values()
                if it.get("status") in ("paused", "queued", "scheduled", "error")
                and not it.get("browserTransfer")
            ]
        for dl_id in ids:
            it = self.engine.downloads.get(dl_id)
            if it and it.get("status") == "error":
                it["status"] = "paused"
            self.engine.start_download(dl_id)
        self.refresh_all()

    def _pause_all_clicked(self):
        self.engine.pause_all()
        self.refresh_all()

    def open_queue_scheduler_dialog(self):
        dlg = QueueSchedulerDialog(self.engine, self.lang, self)
        dlg.exec()
        self.refresh_all()

    def _on_card_action(self, dl_id: str, action: str):
        item = self.engine.downloads.get(dl_id)
        if not item:
            return
        if action == "toggle_torrent":
            if dl_id in self._expanded_torrents:
                self._expanded_torrents.discard(dl_id)
                panel = self._expanded_panels.pop(dl_id, None)
                if panel is not None:
                    panel.deleteLater()
            else:
                self._expanded_torrents.add(dl_id)
            self._row_states.clear()
            self.refresh_all()
        elif action == "pause":
            self.engine.pause_download(dl_id)
            self.refresh_all()
        elif action in ("resume", "retry"):
            if item.get("status") == "error":
                item["status"] = "paused"
            self.engine.start_download(dl_id)
            self.refresh_all()
        elif action == "cancel":
            self.reveal_download_in_table(dl_id)
            self.delete_selected()
        elif action == "open":
            fp = item.get("filePath") or ""
            if fp and os.path.exists(fp):
                os.startfile(fp)
        elif action == "folder":
            self._open_item_folder(item)

    def _on_inline_torrent_applied(self, dl_id: str, indices: list):
        self.engine.apply_torrent_selection(dl_id, indices)
        self._row_states.clear()
        self.refresh_all()

    def _setup_shortcuts(self):
        def bind(seq, slot):
            QShortcut(QKeySequence(seq), self, activated=slot)

        bind("Ctrl+N", lambda: self.open_add_dialog("", False))
        bind("Ctrl+V", self._paste_shortcut)
        bind("Ctrl+F", lambda: (self.txt_search.setFocus(), self.txt_search.selectAll()))
        bind("Delete", lambda: None if self._typing() else self.delete_selected())
        bind("Return", self._open_selected_shortcut)
        bind("Enter", self._open_selected_shortcut)
        bind("Escape", lambda: (self.txt_search.clear(), self.txt_search.clearFocus()) if self.txt_search.hasFocus() else None)

    def _typing(self) -> bool:
        return isinstance(QApplication.focusWidget(), QLineEdit)

    def _paste_shortcut(self):
        """Ctrl+V pastes into a text field, otherwise opens the Add dialog with the copied link."""
        fw = QApplication.focusWidget()
        if isinstance(fw, QLineEdit):
            fw.paste()
            return
        text = QApplication.clipboard().text().strip()
        if text.lower().startswith("magnet:?") or text.split("?")[0].lower().endswith(".torrent"):
            self.open_add_dialog(text, False, True)
        else:
            self.open_add_dialog(text if text.startswith(("http://", "https://")) else "", False)

    def _open_selected_shortcut(self):
        if self._typing():
            return
        dl_id = self.get_selected_id()
        if dl_id:
            self.open_progress_window(dl_id)

    def apply_theme_and_lang(self):
        is_ar = self.lang == "ar"
        T = (lambda ar, en: ar) if is_ar else (lambda ar, en: en)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight)
        self.app.setProperty("scorpionTheme", self.theme)
        stylesheet = LIGHT_QSS if self.theme == "light" else DARK_QSS
        if self.app.styleSheet() != stylesheet:
            self.app.setStyleSheet(stylesheet)
        apply_win32_window_effects(self, self.theme == "dark")
        c = pal()
        self.setWindowTitle("Scorpion Download Manager")
        self.title_bar.refresh_theme(is_ar=is_ar)
        self._rebuild_menu_bar()

        self.sidebar_frame.setProperty("rtl", "true" if is_ar else "false")
        self.sidebar_frame.style().unpolish(self.sidebar_frame)
        self.sidebar_frame.style().polish(self.sidebar_frame)
        self.lbl_categories.setText(T("التصنيفات", "Categories"))
        self.btn_open_queue_mgr.setText(T("إدارة الطوابير والجدول...", "Manage Queue & Schedule..."))
        self.btn_empty_add.setText(T("+ إضافة رابط", "+ Add URL"))

        labels = [
            (self.btn_add, T("إضافة رابط", "Add URL"), "add", c["primary_text"]),
            (self.btn_start_all, T("بدء الكل", "Start All"), "play", c["text_sec"]),
            (self.btn_stop_all, T("إيقاف الكل", "Pause All"), "pause", c["text_sec"]),
            (self.btn_scheduler, T("الجدولة", "Scheduler"), "calendar", c["text_sec"]),
            (self.btn_settings, T("الإعدادات", "Settings"), "settings", c["text_sec"]),
            (self.btn_video, T("تحميل فيديو", "Grab video"), "video", c["text_sec"]),
            (self.btn_torrent, T("تحميل تورنت", "Torrent"), "torrent", c["text_sec"]),
            (self.btn_resume, T("استئناف", "Resume"), "play", c["text_sec"]),
            (self.btn_pause, T("إيقاف مؤقت", "Pause"), "pause", c["text_sec"]),
            (self.btn_delete, T("حذف", "Delete"), "delete", c["text_sec"]),
            (self.btn_clear_done, T("حذف المكتمل", "Clear completed"), "clear", c["text_sec"]),
            (self.btn_browser_setup, T("ربط المتصفحات", "Browsers"), "browser", c["text_sec"]),
            (self.btn_updates, T("التحديثات", "Updates"), "update", c["text_sec"]),
            (self.btn_theme, T("الوضع الداكن", "Dark") if self.theme == "light" else T("الوضع الفاتح", "Light"),
             "moon" if self.theme == "light" else "sun", c["text_sec"]),
            (self.btn_lang, "English" if is_ar else "العربية", "lang", c["text_sec"]),
        ]
        for btn, text, icon, color in labels:
            btn.setProperty("fullText", text)
            btn.setAccessibleName(text)
            btn.setText(text)
            btn.setIcon(glyph_icon(ICONS[icon], color, 15))
        self.txt_search.setAccessibleName(T("بحث في التحميلات", "Search downloads"))
        self.tree.setAccessibleName(T("تصنيفات التحميلات", "Download categories"))
        self.table.setAccessibleName(T("قائمة التحميلات", "Downloads list"))
        if getattr(self, "_search_act", None) is not None:
            self._search_act.setIcon(outline_icon("search", c["muted"], 14))
        self._apply_layout_mode(force=True)

        self._rebuilding_tree = True
        try:
            self.tree.clear()
            self.nav_items = {}

            def nav(key, text, data, icon_key):
                it = QTreeWidgetItem(self.tree, [text, ""])
                it.setData(0, Qt.ItemDataRole.UserRole, data)
                it.setData(0, SIDEBAR_ROLE_ICON, icon_key)
                it.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
                self.nav_items[key] = it
                return it

            nav("all", T("كل التحميلات", "All Downloads"), ("all", "ALL"), "all_downloads")
            nav("Video", T("الفيديو", "Videos"), ("all", "Video"), "video")
            nav("Music", T("الصوتيات", "Music"), ("all", "Music"), "music")
            nav("Programs", T("البرامج", "Programs"), ("all", "Programs"), "programs")
            nav("Compressed", T("المضغوطة", "Compressed"), ("all", "Compressed"), "compressed")
            nav("Documents", T("المستندات", "Documents"), ("all", "Documents"), "documents")
            nav("Torrents", T("التورنت", "Torrents"), ("torrent", "ALL"), "torrents")
            nav("Queues", T("الطوابير والجدولة", "Queues & Scheduler"), ("queue", "ALL"), "queues")

            matched = False
            for _key, it in self.nav_items.items():
                if it.data(0, Qt.ItemDataRole.UserRole) == (self.filter_state, self.filter_cat):
                    self.tree.setCurrentItem(it)
                    matched = True
                    break
            if not matched and "all" in self.nav_items:
                self.tree.setCurrentItem(self.nav_items["all"])
        finally:
            self._rebuilding_tree = False

        self.table.setHorizontalHeaderLabels(
            [T("اسم الملف", "File name"), T("الحجم", "Size"), T("التقدم", "Progress"),
             T("السرعة", "Speed"), T("الوقت المتبقي", "Time left"), T("الحالة", "Status")]
        )
        self.empty_label.setText(
            T("لا توجد تحميلات هنا بعد\n\nاضغط «+ إضافة رابط» أو استخدم إضافة المتصفح",
              "No downloads here yet\n\nClick “+ Add URL” or capture a download from your browser")
        )
        self._row_ids = []
        self._row_states = {}
        self._last_nav_counts = None
        for panel in list(self._expanded_panels.values()):
            panel.deleteLater()
        self._expanded_panels.clear()
        self.refresh_all()

    def _restyle_cards(self):
        for dl_id in list(self.cards.cards):
            self.cards.cards.pop(dl_id).close()
            self.cards.show_for(dl_id)

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.engine.settings["theme"] = self.theme
        self.engine.save_state()
        self.apply_theme_and_lang()
        self._restyle_cards()
        for dlg in list(self.open_progress_dialogs.values()):
            if hasattr(dlg, "apply_theme"):
                dlg.apply_theme()

    def clear_completed(self):
        for dl_id, dlg in list(self.open_progress_dialogs.items()):
            it = self.engine.downloads.get(dl_id)
            if not it or it.get("status") == "completed":
                self.open_progress_dialogs.pop(dl_id, None)
                dlg.close()
        self.engine.delete_completed()
        self.refresh_all()

    def _sync_open_dialogs_lang(self):
        is_ar = self.lang == "ar"
        T = (lambda ar, en: ar) if is_ar else (lambda ar, en: en)
        ldir = Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight
        lead = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute) if is_ar else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        for dlg in list(self.open_progress_dialogs.values()):
            dlg.is_ar = is_ar
            dlg.T = T
            dlg.setLayoutDirection(ldir)
            dlg.lbl_filename.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
            dlg.lbl_url.setAlignment(lead | Qt.AlignmentFlag.AlignVCenter)
            dlg._update_details_button()
            dlg.refresh_ui()

    def toggle_lang(self):
        self.lang = "en" if self.lang == "ar" else "ar"
        self.engine.settings["lang"] = self.lang
        self.engine.save_state()
        self.apply_theme_and_lang()
        self._rebuild_tray_menu()
        self._sync_open_dialogs_lang()
        self._restyle_cards()

    def _on_remote_lang_changed(self, new_lang: str):
        if new_lang in ("ar", "en") and self.lang != new_lang:
            self.lang = new_lang
            self.apply_theme_and_lang()
            self._rebuild_tray_menu()
            self._sync_open_dialogs_lang()
            self._restyle_cards()

    def on_table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.setCurrentCell(row, 0)
        dl_id = self.get_selected_id()
        item = self.engine.downloads.get(dl_id) if dl_id else None
        if not item:
            return

        is_ar = self.lang == "ar"
        T = (lambda ar, en: ar) if is_ar else (lambda ar, en: en)
        c = pal()
        menu = QMenu(self)

        def add(text, icon, slot):
            act = menu.addAction(glyph_icon(ICONS[icon], c["text"]), text)
            act.triggered.connect(slot)

        if item["status"] == "completed" and os.path.exists(item["filePath"]):
            add(T("تشغيل الملف", "Open File"), "open", lambda: os.startfile(item["filePath"]))
        add(T("فتح المجلد", "Show in Folder"), "folder", lambda: self._open_item_folder(item))
        add(T("تفاصيل التحميل", "Download Details"), "download", lambda: self.open_progress_window(dl_id))
        if item.get("isTorrent") and item["status"] != "completed":
            add(T("تحديد ملفات التورنت", "Select Torrent Files"), "torrent", lambda: self._on_card_action(dl_id, "toggle_torrent"))
        if item["status"] != "completed":
            if item["status"] == "downloading":
                add(T("إيقاف مؤقت", "Pause"), "pause", lambda: self.engine.pause_download(dl_id))
            else:
                add(T("استئناف", "Resume"), "play",
                    lambda: (self.engine.start_download(dl_id), self.refresh_all()))
        menu.addSeparator()
        add(T("نسخ الرابط", "Copy URL"), "browser", lambda: self._copy_url_safely(item["url"]))
        add(T("حذف", "Delete"), "delete", self.delete_selected)
        menu.exec(self.table.viewport().mapToGlobal(pos))

    def _open_item_folder(self, item: dict):
        target = item["filePath"] if os.path.exists(item["filePath"]) else item["tempFilePath"]
        if os.path.exists(target):
            subprocess.Popen(["explorer", "/select,", os.path.normpath(target)])
        elif os.path.exists(item["saveDir"]):
            os.startfile(item["saveDir"])

    def _copy_url_safely(self, url: str):
        self.last_clip = url
        self.clipboard.setText(url)

    def on_tree_clicked(self, item: QTreeWidgetItem):
        if getattr(self, "_rebuilding_tree", False) or item is None:
            return
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.filter_state, self.filter_cat = data
            self.refresh_all()

    def open_browser_setup_dialog(self):
        if is_msix_packaged():
            self.open_store_pairing_dialog()
            return
        dlg = BrowserSetupDialog(self.engine, self.lang, self)
        dlg.exec()
        self.refresh_all()

    def open_store_pairing_dialog(self):
        ar = self.lang == "ar"
        dialog = QDialog(self)
        dialog.setWindowTitle("ربط المتصفح" if ar else "Connect Browser")
        layout = QVBoxLayout(dialog)
        hint = QLabel(
            "ولّد رمزًا ثم أدخله في نافذة إضافة سكوربيون. الرمز صالح لمدة خمس دقائق ولمرة واحدة."
            if ar else "Generate a code and enter it in the Scorpion extension. The code lasts five minutes and works once."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        code = QLineEdit()
        code.setReadOnly(True)
        code.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        code.setAccessibleName("رمز الربط" if ar else "Pairing code")
        layout.addWidget(code)
        addon_url = f"https://microsoftedge.microsoft.com/addons/detail/{OFFICIAL_EXTENSION_ID}"
        addon = QLabel(
            f'ثبّت <a href="{addon_url}">إضافة سكوربيون لإيدج</a>.'
            if ar else f'Install the <a href="{addon_url}">Scorpion extension for Edge</a>.'
        )
        addon.setOpenExternalLinks(True)
        layout.addWidget(addon)
        buttons = QHBoxLayout()
        generate = QPushButton("ولّد رمزًا" if ar else "Generate code")
        copy = QPushButton("نسخ الرمز" if ar else "Copy code")
        copy.setEnabled(False)
        close = QPushButton("إغلاق" if ar else "Close")
        for button in (generate, copy, close):
            buttons.addWidget(button)
        layout.addLayout(buttons)

        def show_code():
            code.setText(self.engine.create_store_pairing_code())
            code.selectAll()
            copy.setEnabled(True)

        generate.clicked.connect(show_code)
        copy.clicked.connect(lambda: self.clipboard.setText(code.text()))
        close.clicked.connect(dialog.accept)
        dialog.resize(445, dialog.sizeHint().height())
        dialog.exec()
        self.refresh_all()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self.engine, self.lang, self)
        dlg.exec()
        self.refresh_all()

    def open_update_dialog(self, update_info: dict = None, just_updated: bool = False):
        if not isinstance(update_info, dict):
            update_info = None
        dlg = UpdateDialog(self.engine, self.lang, self, update_info=update_info, just_updated=just_updated)
        dlg.exec()

    def _background_check_updates(self):
        if is_msix_packaged():
            return
        def worker():
            res = self.engine.check_for_updates()
            if res.get("hasUpdate"):
                self.engine.signals.update_available.emit(res)
            elif res.get("tools"):
                self.engine.ensure_tools(res["tools"])

        threading.Thread(target=worker, daemon=True).start()

    def _on_update_available(self, res: dict):
        self.open_update_dialog(update_info=res, just_updated=False)

    def on_torrent_files_ready(self, dl_id: str):
        item = self.engine.downloads.get(dl_id)
        if not item or item.get("torrentSelection"):
            return
        if self.isVisible():
            self._expanded_torrents.add(dl_id)
            self.reveal_download_in_table(dl_id)
            return
        dlg = TorrentFilesDialog(item, self.lang, None)
        dlg.exec()
        item["torrentSelection"] = dlg.selected_indices()

    def on_browser_captured(self, payload: dict):
        if payload.get("browserTransferId"):
            tid = payload["browserTransferId"]
            self.reveal_download_in_table(tid)
            self.show_download_started(tid)
            return
        url = (payload.get("url") or "").strip()
        if not url:
            return

        is_torrent = (
            payload.get("type") == "torrent"
            or url.lower().startswith("magnet:?")
            or url.lower().split("?")[0].endswith(".torrent")
        )
        ptype = (payload.get("type") or "").strip().lower()
        quality = payload.get("quality") or "best"
        ref_url = (payload.get("referer") or payload.get("pageUrl") or "").strip()
        u_plus_ref = (url + " " + ref_url).lower()
        is_music_site = any(
            d in u_plus_ref
            for d in ("spotify.com", "soundcloud.com", "anghami.com", "deezer.com", "music.apple.com", "widevine-license")
        )
        if is_music_site and not is_torrent:
            ptype = "audio"
            quality = "audio"
            if any(x in url.lower() for x in ("widevine-license", "spclient.spotify.com", "/license")) and ref_url:
                url = ref_url
        is_audio = (ptype == "audio" or quality == "audio") and not is_torrent
        is_video = ptype in ("video", "audio") and not is_torrent
        cap_quality = "audio" if is_audio else (
            quality if quality in ("best", "audio") or re.fullmatch(r"\d{3,4}p", quality or "") else "best"
        )
        cap_type = "torrent" if is_torrent else ("audio" if is_audio else ("video" if is_video else "file"))
        existing_id = self.engine.should_ignore_duplicate_capture(url, cap_quality, cap_type)
        if existing_id:
            self.reveal_download_in_table(existing_id)
            self.show_download_started(existing_id)
            return
        title = (payload.get("title") or "").strip()
        filename = (payload.get("filename") or "").strip()

        if is_video and not filename and title:
            ext = ".mp3" if is_audio else ".mp4"
            filename = sanitize_filename(title) + ext

        if self.engine.settings.get("autoStartFromBrowser", True):
            cat = "Music" if is_audio else ("Video" if (is_video or is_torrent) else "")
            opts = {
                "url": url,
                "filename": filename,
                "referer": (payload.get("referer") or payload.get("pageUrl") or "").strip(),
                "tabUrl": (payload.get("tabUrl") or "").strip(),
                "candidates": payload.get("candidates") or [],
                "strictTarget": bool(payload.get("strictTarget", False)),
                "userAgent": (payload.get("userAgent") or "").strip(),
                "acceptLanguage": (payload.get("acceptLanguage") or "").strip(),
                "cookies": payload.get("cookies") or [],
                "expectedDuration": payload.get("expectedDuration") or 0,
                "category": cat,
                "totalSize": int(payload.get("totalSize") or 0),
                "connections": 32,
                "startImmediately": True,
                "fromBrowser": True,
                "incognito": bool(payload.get("incognito")),
                "_captureQuality": cap_quality,
                "_captureType": cap_type,
                "isVideo": is_video and quality != "direct",
                "isTorrent": is_torrent,
                "videoQuality": cap_quality,
            }
            item = self.engine.add_download(opts)
            self.reveal_download_in_table(item["id"])
            self.show_download_started(item["id"])
        else:
            dlg = AddDownloadDialog(self.engine, url, is_video and quality != "direct", self.lang, self, is_torrent=is_torrent)
            if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_opts:
                dlg.result_opts.update({
                    "referer": ref_url, "tabUrl": payload.get("tabUrl") or "",
                    "candidates": payload.get("candidates") or [], "cookies": payload.get("cookies") or [],
                    "strictTarget": bool(payload.get("strictTarget", False)),
                    "userAgent": (payload.get("userAgent") or "").strip(),
                    "acceptLanguage": (payload.get("acceptLanguage") or "").strip(),
                    "expectedDuration": payload.get("expectedDuration") or 0,
                    "fromBrowser": True,
                    "incognito": bool(payload.get("incognito")),
                    "_captureQuality": cap_quality,
                    "_captureType": cap_type,
                })
                item = self.engine.add_download(dlg.result_opts)
                self.reveal_download_in_table(item["id"])
                if dlg.result_opts.get("startImmediately", True):
                    self.show_download_started(item["id"])

    def open_add_dialog(self, initial_url: str = "", is_video: bool = False, is_torrent: bool = False):
        dlg = AddDownloadDialog(self.engine, initial_url, is_video, self.lang, self, is_torrent=is_torrent)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_opts:
            item = self.engine.add_download(dlg.result_opts)
            self.reveal_download_in_table(item["id"])
            if dlg.result_opts.get("startImmediately"):
                self.show_download_started(item["id"])

    def reveal_download_in_table(self, dl_id: str):
        """Ensure an added/captured download is never hidden by active filters and scroll to it."""
        item = self.engine.downloads.get(dl_id)
        if not item:
            self.refresh_all()
            return
        st = item.get("status")
        cat = item.get("category") or "General"
        hidden_state = (
            (self.filter_state == "unfinished" and st == "completed")
            or (self.filter_state == "completed" and st != "completed")
            or (self.filter_state == "torrent" and not item.get("isTorrent"))
            or (self.filter_state == "queue" and st not in ("queued", "scheduled"))
        )
        hidden_cat = self.filter_cat != "ALL" and cat != self.filter_cat
        if hidden_state or hidden_cat:
            self.filter_state = "all"
            self.filter_cat = "ALL"
            if "all" in getattr(self, "nav_items", {}):
                self._rebuilding_tree = True
                try:
                    self.tree.setCurrentItem(self.nav_items["all"])
                finally:
                    self._rebuilding_tree = False
        q = self.txt_search.text().strip().lower()
        if q and q not in (item.get("filename") or "").lower() and q not in (item.get("url") or "").lower():
            self.txt_search.blockSignals(True)
            self.txt_search.clear()
            self.txt_search.blockSignals(False)
        self.refresh_all()
        for r in range(self.table.rowCount()):
            cell = self.table.item(r, 0)
            if cell is not None and cell.data(ROLE_ID) == dl_id:
                self.table.scrollToItem(cell, QTableWidget.ScrollHint.PositionAtTop)
                self.table.setCurrentCell(r, 0)
                break

    def show_download_started(self, dl_id: str):
        mode = self.engine.settings.get("onStartShow", "card")
        if mode == "window":
            self.open_progress_window(dl_id)
        elif mode == "card":
            self.cards.show_for(dl_id)

    def open_progress_window(self, dl_id: str):
        w = self.open_progress_dialogs.get(dl_id)
        if w is None:
            w = IDMProgressDialog(self.engine, dl_id, self.lang, self)
            self.open_progress_dialogs[dl_id] = w
        w.refresh_ui()
        w.bring_to_front()

    def on_row_double_clicked(self, row: int, _col: int):
        id_item = self.table.item(row, 0)
        if id_item:
            dl_id = id_item.data(Qt.ItemDataRole.UserRole)
            if dl_id:
                self.open_progress_window(dl_id)

    def get_selected_id(self):
        row = self.table.currentRow()
        if row < 0:
            return None
        it = self.table.item(row, 0)
        return it.data(Qt.ItemDataRole.UserRole) if it else None

    def resume_selected(self):
        dl_id = self.get_selected_id()
        if dl_id:
            self.engine.start_download(dl_id)
            self.refresh_all()
            self.show_download_started(dl_id)

    def pause_selected(self):
        dl_id = self.get_selected_id()
        if dl_id:
            self.engine.pause_download(dl_id)

    def delete_selected(self):
        dl_id = self.get_selected_id()
        if not dl_id:
            return
        item = self.engine.downloads.get(dl_id) or {}
        if item.get("status") != "completed":
            is_ar = self.lang == "ar"
            if not confirm_action_dialog(
                "حذف التحميل" if is_ar else "Delete download",
                (
                    f"حذف «{item.get('filename', '')}»؟\nسيتم حذف الأجزاء التي تم تحميلها."
                    if is_ar
                    else f"Delete “{item.get('filename', '')}”?\nThe downloaded parts will be discarded."
                ),
                is_ar,
                yes_label="نعم، حذف" if is_ar else "Yes, delete",
                no_label="إلغاء" if is_ar else "Cancel",
            ):
                return
        dlg = self.open_progress_dialogs.pop(dl_id, None)
        if dlg is not None:
            dlg.close()
        self._expanded_torrents.discard(dl_id)
        panel = self._expanded_panels.pop(dl_id, None)
        if panel is not None:
            panel.deleteLater()
        self.cards.remove(dl_id)
        self.engine.delete_download(dl_id)
        self.refresh_all()

    def on_clipboard_changed(self):
        text = self.clipboard.text().strip()
        if not text or text == self.last_clip:
            return
        self.last_clip = text
        if not self.engine.settings.get("clipboardMonitor", True):
            return
        if text.lower().startswith("magnet:?xt=urn:btih:"):
            self.open_add_dialog(text, False, True)
            return
        exts = tuple(
            CATEGORY_MAP["Video"]
            + CATEGORY_MAP["Music"]
            + [".torrent", ".zip", ".rar", ".7z", ".exe", ".msi", ".iso", ".pdf", ".apk"]
        )
        if text.startswith(("http://", "https://")) and text.split("?")[0].lower().endswith(exts):
            is_tor = text.split("?")[0].lower().endswith(".torrent")
            self.open_add_dialog(text, False, is_tor)

    def on_download_completed(self, dl_id: str):
        item = self.engine.downloads.get(dl_id)
        if not item:
            return
        if item.get("fromBrowser") and not item.get("incognito") and item.get("status") == "completed":
            with self.engine.lock:
                completed_ids = self.engine.settings.get("extensionCompletedIds") or []
                changed = len(completed_ids) < 3 and dl_id not in completed_ids
                if changed:
                    self.engine.settings["extensionCompletedIds"] = [*completed_ids, dl_id]
            if changed:
                self.engine.save_state()
        dlg = self.open_progress_dialogs.get(dl_id)
        if dlg is not None and dlg.isVisible():
            return
        self.cards.show_for(dl_id)

    def _update_status_surfaces(self, items: list):
        """Corner card on errors, progress on the taskbar button, number of active downloads on the tray icon."""
        for it in items:
            st, prev = it.get("status"), self._seen_status.get(it["id"])
            if st == "error" and prev not in (None, "error"):
                dlg = self.open_progress_dialogs.get(it["id"])
                if not (dlg is not None and dlg.isVisible()):
                    self.cards.show_for(it["id"])
            self._seen_status[it["id"]] = st
        self.cards.refresh()

        active = [it for it in items if it.get("status") == "downloading"]
        total = sum(int(it.get("totalSize") or 0) for it in active)
        done = sum(int(it.get("downloadedBytes") or 0) for it in active)
        if active:
            state = TaskbarProgress.NORMAL if total else TaskbarProgress.INDETERMINATE
        elif any(it.get("status") == "error" and self._seen_status.get(it["id"]) == "error"
                 and time.time() - (it.get("createdAt", 0) / 1000) < 600 for it in items[:1]):
            state = TaskbarProgress.ERROR
        else:
            state = TaskbarProgress.NOPROGRESS
        if self.isVisible():
            self.taskbar.update(int(self.winId()), state, done, total or 1)

        n = len(active)
        if getattr(self, "tray_icon", None) is not None and n != self._tray_badge_count:
            self._tray_badge_count = n
            self.tray_icon.setIcon(self._tray_icon_with_badge(n))
            self.tray_icon.setToolTip(
                f"Scorpion Download Manager v{APP_VERSION}"
                + ((f" — {n} تحميل شغال" if self.lang == "ar" else f" — {n} downloading") if n else "")
            )

    def _tray_icon_with_badge(self, n: int) -> QIcon:
        if not n:
            return self.app_icon
        pm = self.app_icon.pixmap(64, 64)
        if pm.isNull():
            return self.app_icon
        p = QPainter(pm)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(pal()["accent"]))
        p.drawEllipse(QRectF(30, 30, 34, 34))
        p.setPen(QColor(pal()["primary_text"]))
        f = QFont()
        f.setPixelSize(22)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(30, 30, 34, 34), Qt.AlignmentFlag.AlignCenter, str(n) if n < 10 else "9+")
        p.end()
        return QIcon(pm)

    def _apply_layout_mode(self, force: bool = False):
        """Adapts toolbar buttons and sidebar cleanly down to small laptop/split windows."""
        is_ar = self.lang == "ar"
        labeled_standard = {self.btn_add, self.btn_start_all, self.btn_stop_all, self.btn_scheduler, self.btn_settings}

        def set_texts(m):
            self._toolbar_frame.layout().setSpacing(4 if m == "tiny" else 8)
            if m == "tiny":
                self.txt_search.setPlaceholderText("بحث..." if is_ar else "Search")
            elif m == "full":
                self.txt_search.setPlaceholderText("بحث (Ctrl+F)" if is_ar else "Search")
            else:
                self.txt_search.setPlaceholderText("بحث..." if is_ar else "Search")
            for btn in self._toolbar_buttons:
                full = btn.property("fullText") or ""
                if btn is self.btn_add:
                    # The button already shows a plus icon: no second "+" in the text
                    btn.setText(full if m != "tiny" else "")
                    btn.setToolTip("" if m != "tiny" else full)
                    continue
                keep_text = (m == "full") or (m == "standard" and btn in labeled_standard)
                btn.setText(full if keep_text else "")
                btn.setToolTip("" if keep_text else full)

        key = (self.lang, tuple(b.property("fullText") or "" for b in self._toolbar_buttons))
        if force or getattr(self, "_mode_widths_key", None) != key:
            self._mode_widths = {}
            for m in ("full", "standard", "compact", "tiny"):
                set_texts(m)
                sb_w = {
                    "full": BRAND_TOKENS["sidebar_w_full"],
                    "standard": BRAND_TOKENS["sidebar_w_standard"],
                    "compact": BRAND_TOKENS["sidebar_w_compact"],
                    "tiny": BRAND_TOKENS["sidebar_w_tiny"],
                }[m]
                self._mode_widths[m] = self._toolbar_frame.layout().sizeHint().width() + sb_w + 48
            self._mode_widths_key = key
            self._layout_mode = None

        w = self.width()
        mode = (
            "full" if self._mode_widths["full"] <= w
            else ("standard" if self._mode_widths["standard"] <= w
                  else ("compact" if self._mode_widths["compact"] <= w else "tiny"))
        )
        if mode == getattr(self, "_layout_mode", None):
            return
        self._layout_mode = mode
        set_texts(mode)
        sb_width = {
            "full": BRAND_TOKENS["sidebar_w_full"],
            "standard": BRAND_TOKENS["sidebar_w_standard"],
            "compact": BRAND_TOKENS["sidebar_w_compact"],
            "tiny": BRAND_TOKENS["sidebar_w_tiny"],
        }[mode]
        self.sidebar_frame.setFixedWidth(sb_width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "sidebar_frame"):
            self._apply_layout_mode()

    def _restore_window_geometry(self):
        raw = self.engine.settings.get("windowGeometry") or ""
        if raw:
            try:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
            except Exception:
                pass
        avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = min(max(640, self.width()), avail.width()), min(max(480, self.height()), avail.height())
        x = min(max(self.x(), avail.left()), avail.right() - w + 1)
        y = min(max(self.y(), avail.top()), avail.bottom() - h + 1)
        self.setGeometry(x, y, w, h)
        self._apply_layout_mode(force=True)

    def _save_window_geometry(self):
        try:
            self.engine.settings["windowGeometry"] = bytes(self.saveGeometry().toBase64()).decode("ascii")
            self.engine.save_state()
        except Exception:
            pass

    def closeEvent(self, event):
        self._set_edge_cursor(None)
        self._save_window_geometry()
        if getattr(self, "tray_icon", None) is not None and not getattr(self, "_really_quit", False):
            event.ignore()
            self.hide()
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                self.tray_icon.showMessage(
                    "Scorpion Download Manager",
                    "البرنامج شغال في الخلفية بجوار الساعة ويستقبل التحميلات من المتصفح"
                    if self.lang == "ar"
                    else "Scorpion keeps running in the tray to catch browser downloads",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            return
        try:
            self.app.removeEventFilter(self)
        except Exception:
            pass
        super().closeEvent(event)
        self.app.quit()

    def quit_app(self):
        if self.isVisible():
            self._save_window_geometry()
        self._really_quit = True
        self.engine.pause_all()
        self.app.quit()

    def showEvent(self, event):
        super().showEvent(event)
        apply_win32_window_effects(self, self.theme == "dark")
        QTimer.singleShot(0, self.refresh_all)

    def _on_refresh_tick(self):
        visible = self.isVisible()
        self.engine._ui_visible = visible
        if not visible:
            if getattr(self, "cards", None) and (self.cards.cards or getattr(self.engine, "controllers", None)):
                with self.engine.lock:
                    raw_items = list(self.engine.downloads.values())
                try:
                    self._update_status_surfaces(raw_items)
                except Exception:
                    pass
            return
        self.refresh_all()

    def _cached_free_space(self) -> int:
        now = time.monotonic()
        if now - self._free_space_cache[0] < 5.0 and self._free_space_cache[1] > 0:
            return self._free_space_cache[1]
        free_b = 0
        try:
            dl_root = self.engine.settings.get("downloadsRoot") or getattr(self.engine, "default_dl_root", "") or os.path.expanduser("~")
            target = dl_root if os.path.exists(dl_root) else os.path.dirname(dl_root) or os.path.expanduser("~")
            free_b = shutil.disk_usage(target).free
        except Exception:
            free_b = 0
        self._free_space_cache = (now, free_b)
        return free_b

    def refresh_all(self):
        self.engine._ui_visible = self.isVisible()
        is_ar = self.lang == "ar"
        c = pal()
        with self.engine.lock:
            raw_items = list(self.engine.downloads.values())
        items = sorted(raw_items, key=lambda x: int(x.get("createdAt") or 0), reverse=True)
        try:
            self._update_status_surfaces(items)
        except Exception:
            pass

        counts = {k: 0 for k in self.nav_items}
        total_spd = 0
        active_n = 0
        queued_n = 0
        resumable_n = 0
        for it in items:
            st_val = it.get("status") or "paused"
            if st_val == "downloading":
                total_spd += int(it.get("speed") or 0)
                active_n += 1
            elif st_val in ("queued", "scheduled"):
                queued_n += 1
                resumable_n += 1
            elif st_val in ("paused", "error") and not it.get("browserTransfer"):
                resumable_n += 1
            counts["all"] = counts.get("all", 0) + 1
            cat = it.get("category") or "General"
            if cat in counts:
                counts[cat] += 1
            if it.get("isTorrent"):
                counts["Torrents"] = counts.get("Torrents", 0) + 1
            if st_val in ("queued", "scheduled"):
                counts["Queues"] = counts.get("Queues", 0) + 1

        if counts != getattr(self, "_last_nav_counts", None):
            for key, nav_it in self.nav_items.items():
                n = counts.get(key, 0)
                nav_it.setText(1, str(n) if n else "")
            self._last_nav_counts = dict(counts)

        show_q_banner = self.filter_state == "queue"
        if self.queue_banner.isVisible() != show_q_banner:
            self.queue_banner.setVisible(show_q_banner)
        if show_q_banner:
            sched_on = bool(self.engine.settings.get("schedEnabled"))
            sched_t = self.engine.settings.get("schedTime") or "02:00"
            max_c = int(self.engine.settings.get("maxConcurrent") or 4)
            self.lbl_queue_info.setText(
                (
                    f"الحد الأقصى المتزامن: {L(max_c)}   •   الجدول اليومي: {L(sched_t) if sched_on else 'معطّل'}"
                    if is_ar
                    else f"Max simultaneous: {max_c}   •   Daily schedule: {sched_t if sched_on else 'Off'}"
                )
            )

        query = self.txt_search.text().strip().lower()
        filtered = []
        for it in items:
            st_val = it.get("status") or "paused"
            if self.filter_state == "unfinished" and st_val == "completed":
                continue
            if self.filter_state == "completed" and st_val != "completed":
                continue
            if self.filter_state == "torrent" and not it.get("isTorrent"):
                continue
            if self.filter_state == "queue" and st_val not in ("queued", "scheduled"):
                continue
            if self.filter_cat != "ALL" and (it.get("category") or "General") != self.filter_cat:
                continue
            if query and query not in (it.get("filename") or "").lower() and query not in (it.get("url") or "").lower():
                continue
            filtered.append(it)

        self.stack.setCurrentIndex(0 if filtered else 1)
        if not filtered:
            if query:
                self.empty_label.setText(f"لا توجد نتائج لـ «{query}»" if is_ar else f"No results for “{query}”")
            elif self.filter_state == "queue":
                self.empty_label.setText(
                    "لا توجد تحميلات في الطابور أو الجدولة حالياً" if is_ar else "No queued or scheduled downloads right now"
                )
            else:
                self.empty_label.setText(
                    "لا توجد تحميلات هنا بعد\n\nاضغط «+ إضافة رابط» أو استخدم إضافة المتصفح"
                    if is_ar
                    else "No downloads here yet\n\nClick “+ Add URL” or capture a download from your browser"
                )

        sel_id = self.get_selected_id()
        ids = [it["id"] for it in filtered]
        prev_states = getattr(self, "_row_states", {})
        new_states = {}
        ids_changed = ids != getattr(self, "_row_ids", [])
        if ids_changed:
            for dl_id in list(self._expanded_panels):
                if dl_id not in ids or dl_id not in self._expanded_torrents:
                    panel = self._expanded_panels.pop(dl_id, None)
                    if panel is not None:
                        panel.deleteLater()
            self.table.setRowCount(len(filtered))
            self._row_ids = ids

        standard_h = BRAND_TOKENS["card_h"] + BRAND_TOKENS["card_gap"]
        expanded_h = BRAND_TOKENS["card_torrent_expanded_h"] + BRAND_TOKENS["card_gap"]

        for r, it in enumerate(filtered):
            dl_id = it["id"]
            st_val = it.get("status") or "paused"
            mode = item_mode(it)
            total = int(it.get("totalSize") or 0)
            done = int(it.get("downloadedBytes") or 0)
            spd = int(it.get("speed") or 0) if mode == "active" else 0
            eta = it.get("timeLeft") if mode == "active" else None
            pct = 100.0 if mode == "done" else round(float(it.get("progress") or 0), 2)
            raw_name = it.get("filename") or ""
            file_path = it.get("filePath") or ""
            err_msg = (it.get("errorMsg") or "").strip() if st_val == "error" else ""
            is_tor = bool(it.get("isTorrent"))
            expanded = is_tor and (dl_id in self._expanded_torrents) and mode != "done"
            t_peers = int(it.get("torrentPeers") or it.get("peers") or 0) if is_tor else 0
            segs = it.get("segments") or []
            conn_n = int(it.get("connections") or len(segs) or 0)
            t_files_cnt = len(it.get("torrentFiles") or []) if expanded else 0
            t_sel_sig = tuple(it.get("torrentSelection") or ()) if expanded else ()

            row_sig = (
                dl_id, st_val, mode, total, done, pct, spd, eta, raw_name, file_path,
                err_msg, expanded, t_peers, conn_n, is_ar, t_files_cnt, t_sel_sig,
            )
            new_states[r] = row_sig
            if not ids_changed and prev_states.get(r) == row_sig and self.table.item(r, 0) is not None:
                if dl_id == sel_id and self.table.currentRow() != r:
                    self.table.setCurrentCell(r, 0)
                continue

            if total > 0 and 0 < done < total and st_val != "completed":
                size_line = L(f"{format_bytes(done)} / {format_bytes(total)}")
            elif total > 0:
                size_line = L(format_bytes(total))
            elif done > 0:
                size_line = L(format_bytes(done))
            else:
                size_line = "—"

            browser_owned = bool(it.get("browserTransfer"))
            supports_resume = bool(it.get("supportsRange") or it.get("isVideo") or is_tor) and not browser_owned
            restart_only = bool(browser_owned or is_drm_video_url(it.get("url", "")) or "drm" in err_msg.lower())
            if mode == "done":
                stats_line = "100%"
            elif is_tor and mode == "active":
                pts = [L(f"{pct:.0f}%"), L(format_speed(spd))]
                if t_peers > 0:
                    pts.append(f"{'النظراء' if is_ar else 'Peer'}: {L(t_peers)}")
                stats_line = "  |  ".join(pts)
            elif mode == "active":
                pts = [L(f"{pct:.0f}%"), L(format_speed(spd))]
                if eta is not None and int(eta) > 0:
                    pts.append(("المتبقي: " if is_ar else "ETA: ") + L(format_eta(eta)))
                stats_line = "  |  ".join(pts)
            elif mode == "paused" and st_val == "paused":
                if supports_resume:
                    stats_line = "متوقف مؤقتاً (يدعم الاستئناف)" if is_ar else "Paused (Resume supported)"
                else:
                    stats_line = "متوقف مؤقتاً (لا يدعم الاستئناف)" if is_ar else "Paused (Restart required)"
                if pct > 0:
                    stats_line = f"{stats_line}  •  {L(f'{pct:.0f}%')}"
            elif mode == "error":
                stats_line = "فشل (أعد البدء من المتصفح)" if (is_ar and restart_only) else (
                    "Failed (Restart in browser)" if restart_only else ("فشل التحميل" if is_ar else "Failed")
                )
            else:
                stats_line = item_status_text(it, is_ar)

            err_short = ""
            if st_val == "error":
                reason = localize_error_msg(err_msg, is_ar) if err_msg else ("سبب غير معروف" if is_ar else "Unknown failure")
                err_short = reason

            meta = {
                "id": dl_id,
                "mode": mode,
                "status": st_val,
                "progress": pct,
                "rawName": raw_name,
                "category": it.get("category") or "General",
                "isTorrent": is_tor,
                "browserTransfer": browser_owned,
                "restartOnly": restart_only,
                "expanded": expanded,
                "connCount": conn_n if st_val == "downloading" else 0,
                "sizeLine": size_line,
                "statsLine": stats_line,
                "errorShort": err_short,
                "isAr": is_ar,
            }

            cell0 = self.table.item(r, 0)
            if cell0 is None:
                cell0 = QTableWidgetItem()
                self.table.setItem(r, 0, cell0)
            if cell0.data(ROLE_ID) != dl_id:
                cell0.setData(ROLE_ID, dl_id)
            if cell0.data(ROLE_RAW_NAME) != raw_name:
                cell0.setData(ROLE_RAW_NAME, raw_name)
            cell0.setData(ROLE_PCT, float(pct))
            cell0.setData(ROLE_MODE, mode)
            cell0.setData(ROLE_CARD_META, meta)
            disp_txt = f"{raw_name} — {stats_line}" if stats_line else raw_name
            acc_desc = " | ".join(x for x in (size_line, stats_line, err_short) if x and x != "—")
            if cell0.text() != disp_txt:
                cell0.setText(disp_txt)
            if cell0.data(Qt.ItemDataRole.AccessibleTextRole) != disp_txt:
                cell0.setData(Qt.ItemDataRole.AccessibleTextRole, disp_txt)
            if cell0.data(Qt.ItemDataRole.AccessibleDescriptionRole) != acc_desc:
                cell0.setData(Qt.ItemDataRole.AccessibleDescriptionRole, acc_desc)
            tip_val = f"{file_path}\n{err_short}" if err_short else file_path
            if cell0.toolTip() != tip_val:
                cell0.setToolTip(tip_val)

            target_h = expanded_h if expanded else standard_h
            if self.table.rowHeight(r) != target_h:
                self.table.setRowHeight(r, target_h)

            if expanded or self._expanded_panels:
                idx0 = self.table.model().index(r, 0)
                cur_widget = self.table.indexWidget(idx0)
                if expanded:
                    panel = self._expanded_panels.get(dl_id)
                    if panel is None or cur_widget is not panel:
                        panel = TorrentInlinePanel(dl_id, it, is_ar, self.table)
                        panel.selection_applied.connect(self._on_inline_torrent_applied)
                        self._expanded_panels[dl_id] = panel
                        self.table.setIndexWidget(idx0, panel)
                    else:
                        panel.update_from(it)
                elif cur_widget is not None:
                    self.table.removeCellWidget(r, 0)

            if dl_id == sel_id and self.table.currentRow() != r:
                self.table.setCurrentCell(r, 0)

        self._row_states = new_states
        self._completed_count = sum(1 for it in items if it.get("status") == "completed")
        self.btn_start_all.setEnabled(resumable_n > 0)
        self.btn_stop_all.setEnabled(active_n > 0)
        self._sync_toolbar_selection()

        connected = self.engine.active_connected_browsers(12.0) if hasattr(self.engine, "active_connected_browsers") else []
        rpc_ok = getattr(self.engine, "rpc_alive", False)
        if not rpc_ok:
            bridge = "الجسر المحلي متوقف" if is_ar else "Local bridge offline"
            ext_txt = "الجسر المحلي متوقف" if is_ar else "Bridge Offline"
            ext_icon_name, ext_col = "warning", c["danger"]
        elif connected:
            bridge = f"المتصفح متصل ({', '.join(connected)})" if is_ar else f"Browser connected ({', '.join(connected)})"
            ext_txt = "متصل بالإضافـة" if is_ar else "Connected to Extension"
            ext_icon_name, ext_col = "pulse", c["success"]
        else:
            bridge = "بانتظار إضافة المتصفح" if is_ar else "Waiting for browser extension"
            ext_txt = "ربط إضافة المتصفح" if is_ar else "Connect Extension"
            ext_icon_name, ext_col = "browser", c["warn"]

        self.btn_ext_status.setText(ext_txt)
        self.btn_ext_status.setIcon(outline_icon(ext_icon_name, ext_col, 16, 2.0))
        self.btn_ext_status.setStyleSheet(
            f"QPushButton#ExtStatusPill {{ color: {c['text_sec'] if connected else ext_col}; "
            f"text-align: {'right' if is_ar else 'left'}; }}"
        )

        free_b = self._cached_free_space()
        free_str = format_bytes(free_b) if free_b > 0 else "—"
        sep = "   |   "
        if is_ar:
            parts = [
                f"السرعة الكلية: {L(format_speed(total_spd))}",
                f"النشطة: {L(active_n)}",
                f"في الطابور: {L(queued_n)}",
                f"المساحة الحرة: {L(free_str)}",
                bridge,
            ]
        else:
            parts = [
                f"Total Speed: {format_speed(total_spd)}",
                f"Active: {active_n}",
                f"Queued: {queued_n}",
                f"Free Space: {free_str}",
                bridge,
            ]
        self.lbl_status_bar.setText(sep.join(parts))

    def _sync_toolbar_selection(self):
        dl_id = self.get_selected_id()
        item = self.engine.downloads.get(dl_id) if dl_id else None
        st = item.get("status") if item else ""
        has_sel = item is not None
        can_resume = has_sel and st in ("paused", "error", "queued", "scheduled")
        can_pause = has_sel and st == "downloading" and item.get("phase") not in ("merging", "verifying", "saving")
        self.btn_resume.setEnabled(can_resume)
        self.btn_pause.setEnabled(can_pause)
        self.btn_delete.setEnabled(has_sel)
        self.btn_clear_done.setEnabled(bool(getattr(self, "_completed_count", 0)))


def install_crash_guard(log_dir: str = ""):
    """PyQt aborts the whole app on an exception left unhandled in a slot. Log it and keep running instead."""
    log_dir = log_dir or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), "AppData", "Local"),
                                      "ScorpionIDM")

    def _hook(exc_type, exc, tb):
        if issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return sys.__excepthook__(exc_type, exc, tb)
        try:
            import traceback

            os.makedirs(log_dir, exist_ok=True)
            log_p = os.path.join(log_dir, "app_errors.log")
            if os.path.isfile(log_p) and os.path.getsize(log_p) > 512 * 1024:
                os.replace(log_p, log_p + ".old")
            with open(log_p, "a", encoding="utf-8") as f:
                f.write(f"--- {time.strftime('%Y-%m-%d %H:%M:%S')} v{APP_VERSION}\n")
                f.write("".join(traceback.format_exception(exc_type, exc, tb)))
        except Exception:
            pass

    sys.excepthook = _hook
    return _hook


if __name__ == "__main__":
    install_crash_guard()
    # Arguments: "--tray" (started with Windows) and/or a .torrent path / magnet link opened from Explorer or the browser
    cli_args = sys.argv[1:]
    start_in_tray = "--tray" in cli_args
    open_target = next((a for a in cli_args if not a.startswith("--")), "").strip()

    def _target_payload(target: str) -> dict:
        t_low = target.lower()
        is_tor = t_low.startswith("magnet:?") or t_low.split("?")[0].endswith(".torrent")
        return {"url": target, "type": "torrent" if is_tor else "file"}

    # Single-instance guard: if already running, hand over the target (or just focus) and exit
    try:
        r = requests.get("http://127.0.0.1:19615/ping", timeout=0.6)
        if r.status_code == 200:
            cli_headers = {
                BRIDGE_CLIENT_HEADER: "1",
                BRIDGE_TOKEN_HEADER: load_or_create_bridge_token(),
            }
            if open_target:
                requests.post(
                    "http://127.0.0.1:19615/capture",
                    json=_target_payload(open_target),
                    headers=cli_headers,
                    timeout=2,
                )
            elif not start_in_tray:
                requests.get("http://127.0.0.1:19615/focus", headers=cli_headers, timeout=0.6)
            sys.exit(0)
    except Exception:
        pass

    if EMBEDDED_RUNTIME:
        try:
            import ctypes

            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Scorpion.DownloadManager")
        except Exception:
            pass

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    win = ScorpionMainWindow(app)
    if not start_in_tray or getattr(win, "tray_icon", None) is None:
        win.show()
    if open_target:
        QTimer.singleShot(800, lambda: win.on_browser_captured(_target_payload(open_target)))
    sys.exit(app.exec())
