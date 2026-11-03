# -*- coding: utf-8 -*-
import os
import sys

# Guard against pythonw.exe where sys.stdout / sys.stderr are None
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import json
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
import hashlib
import socket
import base64
import urllib.parse
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

# Verify HTTPS with the Windows certificate store (like browsers do), so antivirus or company HTTPS
# inspection (e.g. Kaspersky) doesn't fail every check while certificates stay verified
try:
    import truststore

    truststore.inject_into_ssl()
except Exception:
    pass

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

try:
    import yt_dlp
    HAS_YTDLP = True
except ImportError:
    HAS_YTDLP = False

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, QObject, QSize, QRectF, QPointF, QTime, QByteArray, QPoint, QPropertyAnimation, QEasingCurve
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
)

# ==============================================================================
# STYLESHEETS (LIGHT MODE & DARK MODE - NATIVE WINDOWS 11 FLUENT STYLE)
# ==============================================================================
PALETTES = {
    "light": {
        "bg": "#f4f5f7", "surface": "#ffffff", "surface2": "#f1f3f6", "border": "#e2e5ea",
        "text": "#1f2430", "muted": "#6b7280", "accent": "#2563eb", "accent_hover": "#1d4ed8",
        "accent_soft": "#e8effd", "danger": "#dc2626", "success": "#16a34a", "warn": "#d97706",
        "track": "#e7eaef",
    },
    "dark": {
        "bg": "#0f1115", "surface": "#171a21", "surface2": "#1e222b", "border": "#2a2f3a",
        "text": "#e6e8ec", "muted": "#8f98a8", "accent": "#3b82f6", "accent_hover": "#60a5fa",
        "accent_soft": "#1b2742", "danger": "#f87171", "success": "#4ade80", "warn": "#fbbf24",
        "track": "#262b35",
    },
}


def _is_dark_theme() -> bool:
    app = QApplication.instance()
    return bool(app and app.property("scorpionTheme") == "dark")


def pal() -> dict:
    return PALETTES["dark" if _is_dark_theme() else "light"]


def L(text) -> str:
    """Keep numbers/units/latin readable inside Arabic (RTL) text."""
    return "\u200e" + str(text) + "\u200e"


def mode_color(mode: str) -> str:
    p = pal()
    return {"done": p["success"], "error": p["danger"], "paused": p["warn"]}.get(mode, p["accent"])


_ICON_FONT = None


def glyph_icon(code: str, color: str = None, size: int = 16) -> QIcon:
    """Monochrome icon drawn from the built-in Windows icon font (Segoe Fluent / MDL2)."""
    global _ICON_FONT
    if _ICON_FONT is None:
        from PyQt6.QtGui import QFontDatabase

        fams = QFontDatabase.families()
        _ICON_FONT = "Segoe Fluent Icons" if "Segoe Fluent Icons" in fams else "Segoe MDL2 Assets"
    from PyQt6.QtGui import QPixmap

    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    f = QFont(_ICON_FONT)
    f.setPixelSize(int(size * 1.6))
    p.setFont(f)
    p.setPen(QColor(color or pal()["text"]))
    p.drawText(pm.rect(), Qt.AlignmentFlag.AlignCenter, code)
    p.end()
    pm.setDevicePixelRatio(2.0)
    return QIcon(pm)


APP_VERSION = "2.1.11"

# External programs shipped with the app: <install>/tools (ffmpeg, ffprobe + DLLs, QuickJS) and <install>/build (aria2c)
TOOLS_DIR = os.path.join(RESOURCE_ROOT, "tools")
TOOLS_PACK_FILES = ("ffmpeg.exe", "ffprobe.exe", "qjs.exe")


def find_tool(name: str) -> str:
    """Path of a bundled program, falling back to one installed on the PC (developer machines)."""
    exe = name if name.lower().endswith(".exe") else name + ".exe"
    for cand in (
        os.path.join(TOOLS_DIR, exe),
        os.path.join(RESOURCE_ROOT, "build", exe),
        shutil.which(name) or "",
        os.path.expandvars(rf"%LOCALAPPDATA%\Microsoft\WinGet\Links\{exe}"),
    ):
        if cand and os.path.isfile(cand):
            return cand
    return ""


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


# Local browser bridge (127.0.0.1:19615): only extension pages and native local processes are trusted.
BRIDGE_CLIENT_HEADER = "X-Scorpion-Client"
BRIDGE_ALLOWED_ORIGIN_PREFIXES = ("chrome-extension://", "moz-extension://", "extension://")

CHANGELOG_HISTORY = [
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
    "add": "\uE710", "video": "\uE714", "torrent": "\uE71B", "play": "\uE768", "pause": "\uE769", "stop": "\uE71A",
    "delete": "\uE74D", "clear": "\uE894", "browser": "\uE774", "moon": "\uE708", "sun": "\uE706",
    "lang": "\uE8C1", "folder": "\uE838", "open": "\uE8A7", "close": "\uE711", "hide": "\uE921",
    "download": "\uE896", "settings": "\uE713", "update": "\uE777",
}


def build_qss(p: dict) -> str:
    return f"""
* {{ font-family: "Segoe UI", Tahoma; font-size: 13px; color: {p['text']}; }}
QMainWindow, QDialog {{ background: {p['bg']}; }}
QFrame#ToolbarFrame {{ background: {p['surface']}; border: none; border-bottom: 1px solid {p['border']}; }}
QFrame#CardFrame {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; }}
QFrame#VSep {{ background: {p['border']}; min-width: 1px; max-width: 1px; border: none; }}
QLabel {{ background: transparent; }}
QLabel#Muted {{ color: {p['muted']}; }}
QLabel#Caption {{ color: {p['muted']}; font-size: 12px; }}
QLabel#Value {{ font-size: 19px; font-weight: 600; }}
QLabel#Title {{ font-size: 16px; font-weight: 600; }}
QLabel#Url {{ color: {p['muted']}; font-size: 12px; }}
QLabel#EmptyState {{ color: {p['muted']}; font-size: 14px; }}
QLabel#StatusBar {{ color: {p['muted']}; background: {p['surface']}; border-top: 1px solid {p['border']}; padding: 7px 16px; font-size: 12px; }}
QPushButton {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 7px; padding: 7px 16px; font-weight: 600; }}
QPushButton:hover {{ background: {p['surface2']}; }}
QPushButton:pressed {{ background: {p['track']}; }}
QPushButton:disabled {{ color: {p['muted']}; background: {p['surface2']}; }}
QPushButton#PrimaryBtn, QPushButton#SuccessBtn {{ background: {p['accent']}; border-color: {p['accent']}; color: #ffffff; }}
QPushButton#PrimaryBtn:hover, QPushButton#SuccessBtn:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
QPushButton#PrimaryBtn:disabled, QPushButton#SuccessBtn:disabled {{ background: {p['surface2']}; border-color: {p['border']}; color: {p['muted']}; }}
QPushButton#DangerBtn {{ color: {p['danger']}; }}
QPushButton#DangerBtn:hover {{ border-color: {p['danger']}; }}
QPushButton#ToolBtn {{ background: transparent; border: 1px solid transparent; padding: 7px 11px; }}
QPushButton#ToolBtn:hover {{ background: {p['surface2']}; border-color: {p['border']}; }}
QPushButton#ToolBtn:disabled {{ background: transparent; color: {p['muted']}; }}
QLineEdit, QComboBox, QSpinBox {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 7px; padding: 6px 10px; selection-background-color: {p['accent']}; selection-color: #ffffff; }}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']}; selection-background-color: {p['accent_soft']}; selection-color: {p['text']}; }}
QTreeWidget, QTableWidget {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; outline: 0; gridline-color: transparent; alternate-background-color: {p['surface']}; }}
QTreeWidget::item {{ padding: 8px 6px; border: none; }}
QTreeWidget::item:hover {{ background: {p['surface2']}; }}
QTreeWidget::item:selected {{ background: {p['accent_soft']}; color: {p['accent']}; }}
QTableWidget::item {{ padding: 0px 8px; border: none; border-bottom: 1px solid {p['surface2']}; }}
QTableWidget::item:hover {{ background: {p['surface2']}; }}
QTableWidget::item:selected {{ background: {p['accent_soft']}; color: {p['text']}; }}
QHeaderView {{ background: transparent; border: none; }}
QHeaderView::section {{ background: {p['surface']}; color: {p['muted']}; font-size: 12px; font-weight: 600; padding: 9px 8px; border: none; border-bottom: 1px solid {p['border']}; }}
QTableCornerButton::section {{ background: {p['surface']}; border: none; }}
QTabWidget::pane {{ border: 1px solid {p['border']}; border-radius: 10px; background: {p['surface']}; top: -1px; }}
QTabBar::tab {{ background: transparent; color: {p['muted']}; padding: 9px 18px; border: none; border-bottom: 2px solid transparent; font-weight: 600; }}
QTabBar::tab:selected {{ color: {p['accent']}; border-bottom: 2px solid {p['accent']}; }}
QTabBar::tab:hover {{ color: {p['text']}; }}
QCheckBox {{ spacing: 8px; }}
QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 7px 22px; border-radius: 6px; }}
QMenu::item:selected {{ background: {p['accent_soft']}; color: {p['accent']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
QToolTip {{ background: {p['surface']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 5px 8px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {p['track']}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {p['muted']}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['track']}; border-radius: 4px; min-width: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{ background: none; height: 0px; width: 0px; }}
QProgressBar {{ background: {p['track']}; border: none; border-radius: 5px; text-align: center; font-weight: 600; }}
QProgressBar::chunk {{ background: {p['accent']}; border-radius: 5px; }}
QSplitter::handle {{ background: transparent; }}
"""


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
    "Music": [".mp3", ".wav", ".flac", ".aac", ".ogg", ".m4a", ".wma", ".opus"],
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


def sanitize_filename(name: str) -> str:
    clean = "".join("_" if c in '<>:"/\\|?*\r\n\t' else c for c in (name or "download_file")).strip()
    return clean or "scorpion_download.bin"


def extract_filename(url: str, headers: dict) -> str:
    cd = headers.get("Content-Disposition") or headers.get("content-disposition") or ""
    if "filename=" in cd:
        part = cd.split("filename=")[-1].strip().strip('"\';')
        if part:
            return sanitize_filename(urllib.parse.unquote(part))
    try:
        parsed = urllib.parse.urlparse(url)
        base = os.path.basename(urllib.parse.unquote(parsed.path))
        if base and len(base) > 1 and base != "/":
            return sanitize_filename(base)
    except Exception:
        pass
    return "scorpion_file.bin"


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

    def set_state(self, pct: float, mode: str):
        self.target = max(0.0, min(100.0, float(pct or 0)))
        self.mode = mode

    def tick(self):
        self.shown += (self.target - self.shown) * 0.15
        if abs(self.target - self.shown) < 0.05:
            self.shown = self.target
        if self.mode in ("active", "connecting"):
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
            span = 100.0 if self.mode == "done" else self.shown
            if span > 0:
                p.drawArc(r, 90 * 16, int(-span * 3.6 * 16))
            if self.mode == "active" and span < 100:
                # small moving glow dot on the track to show activity
                glow = QColor(col)
                glow.setAlpha(90)
                p.setPen(QPen(glow, stroke))
                p.drawArc(r, int((90 - self.angle) * 16), int(-10 * 16))

        if self.mode == "done":
            txt, size = "✓", 26
        elif self.mode == "error":
            txt, size = "!", 26
        else:
            txt, size = f"{self.shown:.0f}%", 18
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

    def set_state(self, pct: float, mode: str):
        self.target = max(0.0, min(100.0, float(pct or 0)))
        self.mode = mode

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
            bw = w * 0.25
            x = -bw + (w + bw) * ((time.time() * 0.6) % 1.0)
            p.fillRect(QRectF(x, 0, bw, h), col)
            return
        fw = w * (100.0 if self.mode == "done" else self.shown) / 100.0
        p.fillRect(QRectF(0, 0, fw, h), col)
        if self.mode == "active" and fw > 20:
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

    def set_data(self, segments, total: int, progress: float, done: bool):
        self.segments = segments or []
        self.total = int(total or 0)
        self.progress = float(progress or 0)
        self.done = done
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
        got = QColor(c["success"] if self.done else c["accent"])
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
                    p.fillRect(QRectF(max(0.0, x0 - 2), 0, 2, h), QColor(c["warn"]))
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
        _mirror_if_rtl(self, p)
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


def _set_elided(label: QLabel, text: str):
    label.setToolTip(text)
    fm = label.fontMetrics()
    width = max(80, label.width() - 4)
    label.setText(fm.elidedText(text, Qt.TextElideMode.ElideMiddle, width))


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
        lead = (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute) if self.is_ar else Qt.AlignmentFlag.AlignLeft
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
            self.resize(max(self.width(), 700), min(700, avail.height() - 40))
        else:
            width = max(640, self.width())
            self.adjustSize()
            self.resize(width, self.minimumSizeHint().height())

    def _apply_icons(self):
        c = pal()
        self.btn_open_file.setIcon(glyph_icon(ICONS["open"], "#ffffff"))
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
            mode, st = "connecting", T("جاري دمج الصوت والصورة", "Merging audio & video")
        elif phase == "connecting" or done == 0:
            mode = "connecting"
            if item.get("isTorrent"):
                st = T("جاري البحث عن Peers", "Finding peers")
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

        self.setWindowTitle(f"{pct:.0f}% — {item.get('filename', '')}")
        _set_elided(self.lbl_filename, item.get("filename", ""))
        if status == "error" and item.get("errorMsg"):
            _set_elided(self.lbl_url, str(item.get("errorMsg")))
            self.lbl_url.setStyleSheet(f"color: {pal()['danger']}; font-size: 12px;")
        else:
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
        self.lbl_meta.setText(sep.join([
            T(f"الوقت المنقضي {L(elapsed)}", f"Elapsed {elapsed}"),
            T(f"الاتصالات {L(f'{active}/{len(segs)}')}", f"Connections {active}/{len(segs)}"),
            resume,
        ]))

        self.seg_map.set_data(segs, total, pct, status == "completed")
        hist = item.get("speedHistory", [])
        self.speed_graph.set_history(hist)
        peak = max(hist) if hist else 0
        self.lbl_graph.setText(T(f"السرعة اللحظية  —  الذروة {L(format_speed(peak))}", f"Live speed  —  peak {format_speed(peak)}"))
        self._fill_segment_table(segs)

        finished = status == "completed"
        self.btn_open_file.setVisible(finished)
        self.btn_toggle.setVisible(not finished)
        self.btn_cancel.setVisible(not finished)
        if status == "downloading":
            self.btn_toggle.setText(T("إيقاف مؤقت", "Pause"))
            self.btn_toggle.setIcon(glyph_icon(ICONS["pause"], "#ffffff"))
        else:
            self.btn_toggle.setText(T("استئناف", "Resume") if status != "error" else T("إعادة المحاولة", "Retry"))
            self.btn_toggle.setIcon(glyph_icon(ICONS["play"], "#ffffff"))

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
            label = s.get("label") or f"#{s.get('id')}"
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
                self.seg_table.item(r, 4).setToolTip(tip)

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
        ans = QMessageBox.question(
            self,
            self.T("إلغاء التحميل", "Cancel download"),
            self.T("هل تريد إلغاء هذا التحميل وحذفه من القائمة؟", "Cancel this download and remove it?"),
        )
        if ans == QMessageBox.StandardButton.Yes:
            self.engine.delete_download(self.dl_id)
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

    def __init__(self, engine, initial_url: str = "", is_video: bool = False, lang: str = "ar", parent=None, is_torrent: bool = False):
        super().__init__(parent)
        self.engine = engine
        self.is_video = is_video
        self.is_torrent = is_torrent
        self.is_ar = lang == "ar"
        self.result_opts = None

        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        if is_torrent:
            title_ar = "🧲 تحميل تورنت أو رابط Magnet — Scorpion IDM"
            title_en = "🧲 Add Torrent / Magnet Link — Scorpion IDM"
        elif is_video:
            title_ar = "🎬 سحب فيديو ذكي (32 بورت) — Scorpion IDM"
            title_en = "🎬 Smart Video Grabber (32 Ports) — Scorpion IDM"
        else:
            title_ar = "📥 إضافة رابط تحميل جديد (32 بورت) — Scorpion IDM"
            title_en = "📥 Add New Download (32 Ports) — Scorpion IDM"
        self.setWindowTitle(title_ar if self.is_ar else title_en)
        self.resize(600, 355)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        layout = QVBoxLayout(self)

        # URL Input + Probe + Browse .torrent
        layout.addWidget(
            QLabel(
                "رابط التحميل، أو رابط ماجنت، أو مسار ملف تورنت:"
                if self.is_ar
                else "Download URL, Magnet URI, or .torrent File Path:"
            )
        )
        url_row = QHBoxLayout()
        self.txt_url = QLineEdit(initial_url)
        self.txt_url.setPlaceholderText("https://...  |  magnet:?xt=urn:btih:...  |  C:\\...\\file.torrent")
        self.txt_url.textChanged.connect(self._on_url_text_changed)
        url_row.addWidget(self.txt_url, 1)

        btn_torrent_file = QPushButton("🧲 ملف تورنت" if self.is_ar else "🧲 .torrent File")
        btn_torrent_file.clicked.connect(self.browse_torrent_file)
        url_row.addWidget(btn_torrent_file)

        btn_probe = QPushButton("🔍 فحص الرابط" if self.is_ar else "🔍 Probe")
        btn_probe.clicked.connect(self.probe_now)
        url_row.addWidget(btn_probe)
        layout.addLayout(url_row)

        self.lbl_probe_info = QLabel("")
        self.lbl_probe_info.setStyleSheet("color: #059669; font-weight: bold;")
        layout.addWidget(self.lbl_probe_info)

        # Filename & Category
        form_grid = QGridLayout()
        form_grid.addWidget(QLabel("اسم الملف:" if self.is_ar else "File Name:"), 0, 0)
        self.txt_filename = QLineEdit()
        form_grid.addWidget(self.txt_filename, 0, 1)

        form_grid.addWidget(QLabel("التصنيف:" if self.is_ar else "Category:"), 0, 2)
        self.cmb_cat = QComboBox()
        self.cmb_cat.addItems(["Programs", "Compressed", "Video", "Music", "Documents", "General"])
        if is_video or is_torrent:
            self.cmb_cat.setCurrentText("Video")
        form_grid.addWidget(self.cmb_cat, 0, 3)

        form_grid.addWidget(QLabel("مجلد الحفظ:" if self.is_ar else "Save Folder:"), 1, 0)
        self.txt_savedir = QLineEdit(self.engine.settings["downloadsRoot"])
        form_grid.addWidget(self.txt_savedir, 1, 1)
        btn_browse = QPushButton("📁 تصفح" if self.is_ar else "📁 Browse")
        btn_browse.clicked.connect(self.browse_dir)
        form_grid.addWidget(btn_browse, 1, 2)

        if is_video:
            form_grid.addWidget(QLabel("جودة الفيديو:" if self.is_ar else "Video Quality:"), 2, 0)
            self.cmb_quality = QComboBox()
            self.qualities_ready.connect(self._on_qualities_ready)
            self._fill_qualities([])
            form_grid.addWidget(self.cmb_quality, 2, 1)
        else:
            form_grid.addWidget(QLabel("عدد البورتات (الأجزاء):" if self.is_ar else "Parallel Ports:"), 2, 0)
            self.cmb_conn = QComboBox()
            self.cmb_conn.addItems(["1", "4", "8", "16", "32", "64"])
            self.cmb_conn.setCurrentText("32")
            form_grid.addWidget(self.cmb_conn, 2, 1)

        layout.addLayout(form_grid)
        layout.addStretch()

        # IDM 3 Action Buttons
        btn_row = QHBoxLayout()
        btn_start = QPushButton("🚀 بدء التحميل الآن" if self.is_ar else "🚀 Start Download Now")
        btn_start.setObjectName("PrimaryBtn")
        btn_start.clicked.connect(lambda: self.accept_download(True))
        btn_row.addWidget(btn_start)

        btn_later = QPushButton("🕒 التحميل لاحقاً" if self.is_ar else "🕒 Download Later")
        btn_later.clicked.connect(lambda: self.accept_download(False))
        btn_row.addWidget(btn_later)

        btn_cancel = QPushButton("إلغاء" if self.is_ar else "Cancel")
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)
        layout.addLayout(btn_row)

        if initial_url:
            QTimer.singleShot(150, self.probe_now)
        elif is_torrent:
            QTimer.singleShot(150, self.browse_torrent_file)

    def browse_dir(self):
        d = QFileDialog.getExistingDirectory(self, "Select Save Folder", self.txt_savedir.text())
        if d:
            self.txt_savedir.setText(d)

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
            self.lbl_probe_info.setText(
                f"✅ ملف تورنت جاهز للتحميل بأقصى سرعة (DHT + Trackers + 32 Ports): {base_name}"
                if self.is_ar
                else f"✅ Torrent file ready for full-speed download (DHT + Trackers + 32 Ports): {base_name}"
            )

    def _on_url_text_changed(self, text: str):
        u = (text or "").strip()
        if u.lower().startswith("magnet:?"):
            self.is_torrent = True
            dn = self.engine.extract_magnet_name(u)
            if dn and not self.txt_filename.text().strip():
                self.txt_filename.setText(dn)
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
            return
        if url.lower().startswith("magnet:?") or (os.path.isfile(url) and url.lower().endswith(".torrent")):
            self._on_url_text_changed(url)
            return
        if not url.startswith("http"):
            return
        if self.is_video:
            self.lbl_probe_info.setText("⏳ جاري قراءة الجودات المتاحة..." if self.is_ar else "⏳ Reading available qualities...")

            def worker():
                try:
                    res = self.engine.list_video_qualities(url)
                except Exception:
                    res = {"ok": False, "qualities": []}
                self.qualities_ready.emit(url, res)

            threading.Thread(target=worker, daemon=True).start()
            return
        self.lbl_probe_info.setText("⏳ جاري فحص الرابط..." if self.is_ar else "⏳ Probing URL...")
        QApplication.processEvents()
        try:
            res = self.engine.probe_url(url)
            self.txt_filename.setText(res["filename"])
            self.cmb_cat.setCurrentText(res["category"])
            self.txt_savedir.setText(res["saveDir"])
            sz = format_bytes(res["totalSize"]) if res["totalSize"] > 0 else "Stream"
            rng = "Yes (يدعم التقسيم إلى 32 بورت والاستكمال)" if res["supportsRange"] else "Direct Stream"
            self.lbl_probe_info.setText(f"✅ الحجم: {sz} | الاستكمال: {rng}")
        except Exception as e:
            self.lbl_probe_info.setText(f"ℹ جاهز للتحميل ({str(e)[:40]})")

    def _fill_qualities(self, qualities: list):
        """Best (plays everywhere) first, then every quality the video offers, then audio only."""
        keep = self.cmb_quality.currentData()
        self.cmb_quality.clear()
        self.cmb_quality.addItem("أفضل جودة تشتغل على أي جهاز (MP4)" if self.is_ar else "Best quality that plays everywhere (MP4)", "best")
        for q in qualities:
            size = q.get("size") or 0
            size_txt = f"  ~{L(format_bytes(size))}" if size else ""
            self.cmb_quality.addItem(f"{q['label']}{size_txt}", q["quality"])
        self.cmb_quality.addItem("الصوت فقط (MP3)" if self.is_ar else "Audio only (MP3)", "audio")
        idx = self.cmb_quality.findData(keep) if keep else -1
        self.cmb_quality.setCurrentIndex(max(0, idx))

    def _on_qualities_ready(self, url: str, res: dict):
        if url != self.txt_url.text().strip():
            return  # the link changed while reading
        qualities = res.get("qualities") or []
        self._fill_qualities(qualities)
        if res.get("title") and not self.txt_filename.text().strip():
            self.txt_filename.setText(sanitize_filename(res["title"]))
        if qualities:
            self.lbl_probe_info.setText(
                # Leading RLM: the line starts with a number, which would otherwise make it left-to-right
                f"‏✅ {L(len(qualities))} جودة متاحة — أعلاها {L(qualities[0]['label'])}" if self.is_ar
                else f"✅ {len(qualities)} qualities available — up to {qualities[0]['label']}"
            )
        else:
            self.lbl_probe_info.setText(
                "ℹ تعذر قراءة الجودات — اختر أفضل جودة" if self.is_ar else "ℹ Couldn't read the qualities — choose Best quality"
            )

    def accept_download(self, start_immediately: bool):
        url = self.txt_url.text().strip()
        if not url:
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
            "category": self.cmb_cat.currentText(),
            "saveDir": self.txt_savedir.text().strip(),
            "connections": 32 if (self.is_video or is_tor) else int(self.cmb_conn.currentText()),
            "startImmediately": start_immediately,
            "isVideo": self.is_video and not is_tor,
            "isTorrent": is_tor,
            "videoQuality": q_val,
        }
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


class ScorpionNativeEngine:
    REQUIRED_EXT_FILES = (
        "manifest.json",
        "background.js",
        "content.js",
        "content.css",
        "popup.html",
        "popup.js",
        "icon.png",
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
        }
        self.total_speed = 0
        self.downloads = {}
        self.controllers = {}
        self.lock = threading.RLock()

        os.makedirs(self.app_data, exist_ok=True)
        os.makedirs(self.temp_root, exist_ok=True)
        os.makedirs(self.default_dl_root, exist_ok=True)
        for cat in list(CATEGORY_MAP.keys()) + ["General"]:
            os.makedirs(os.path.join(self.default_dl_root, cat), exist_ok=True)

        self._load_state()
        if not (self.settings.get("updateUrl") or "").strip():
            self.settings["updateUrl"] = "https://github.com/Mahmoud-847/scorpion-idm.git"
            self.save_state()
        self._apply_install_prefs()
        self.cleanup_old_update_files()
        self.sync_and_repair_browser_extensions()
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
                            dl_url = ""
                            pkg_name = ""
                            assets = rel.get("assets") or []
                            for asset in assets:
                                aname = (asset.get("name") or "").lower()
                                if aname.endswith((".zip", ".exe")):
                                    dl_url = asset.get("browser_download_url") or ""
                                    pkg_name = aname
                                    if aname.endswith(".zip"):
                                        break
                            rel_sha = ""
                            for asset in assets:
                                if pkg_name and (asset.get("name") or "").lower() == pkg_name + ".sha256":
                                    r_sha = requests.get(
                                        asset.get("browser_download_url") or "",
                                        headers={"User-Agent": BROWSER_UA},
                                        timeout=10,
                                    )
                                    if r_sha.status_code == 200:
                                        rel_sha = (r_sha.text.split() or [""])[0]
                                    break
                            manifest = {
                                "version": ver,
                                "publishedAt": (rel.get("published_at") or "")[:10] or latest_entry["date"],
                                "title_ar": rel.get("name") or f"الإصدار {ver}",
                                "title_en": rel.get("name") or f"Version {ver}",
                                "changelog_ar": notes or latest_entry["ar"],
                                "changelog_en": notes or latest_entry["en"],
                                "downloadUrl": dl_url or (manifest.get("downloadUrl") if isinstance(manifest, dict) else ""),
                                "sha256": rel_sha,
                            }
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
        Applies an update package (.zip payload or Setup .exe) in-place without triggering Defender,
        syncs browser extensions, and restarts ScorpionIDM.exe.
        The package must match the SHA-256 published in update.json, otherwise nothing is installed.
        """
        import zipfile

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
            # Launch the installer in silent update mode and close current instance
            subprocess.Popen(
                [pkg_path, "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"], cwd=os.path.dirname(pkg_path)
            )
            self.signals.quit_requested.emit()
            return True, "restarting"

        try:
            with zipfile.ZipFile(pkg_path, "r") as zf:
                members = zf.infolist()
                # Zip Slip guard: refuse the whole package if any entry escapes the install folder
                for member in members:
                    dest = os.path.normcase(os.path.abspath(os.path.join(install_dir, member.filename)))
                    if os.path.commonpath([install_root, dest]) != install_root:
                        return False, f"مسار غير آمن داخل ملف التحديث / Unsafe path in update package: {member.filename}"
                total = max(1, len(members))
                for idx, member in enumerate(members, 1):
                    target_path = os.path.normpath(os.path.join(install_dir, member.filename))
                    if member.is_dir():
                        os.makedirs(target_path, exist_ok=True)
                        continue
                    os.makedirs(os.path.dirname(target_path), exist_ok=True)
                    if os.path.exists(target_path):
                        try:
                            os.remove(target_path)
                        except PermissionError:
                            stale = f"{target_path}.old_{int(time.time() * 1000)}_{idx}"
                            try:
                                os.replace(target_path, stale)
                            except Exception:
                                pass
                    with zf.open(member) as src_f, open(target_path, "wb") as dst_f:
                        shutil.copyfileobj(src_f, dst_f)
                    if progress_cb and (idx % 15 == 0 or idx == total):
                        progress_cb(int(50 + 50 * idx / total))

            self.sync_and_repair_browser_extensions()
            ensure_app_shortcuts(self.settings)
            if os.path.exists(exe_path):
                subprocess.Popen([exe_path], cwd=install_dir)
                self.signals.quit_requested.emit()
            return True, "restarting"
        except Exception as e:
            return False, str(e)

    def _apply_install_prefs(self):
        """One-time choices written by the installer (start with Windows / torrent association / shortcut)."""
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
                # Scheduler: at the chosen time (once per day) move scheduled downloads into the queue
                if self.settings.get("schedEnabled"):
                    now = time.localtime()
                    today = time.strftime("%Y-%m-%d", now)
                    hh, mm = (self.settings.get("schedTime") or "02:00").split(":")[:2]
                    due = (now.tm_hour, now.tm_min) >= (int(hh), int(mm))
                    if due and self.settings.get("schedLastFired") != today:
                        self.settings["schedLastFired"] = today
                        for it in self.downloads.values():
                            if it.get("status") == "scheduled":
                                it["status"] = "queued"
                        self.save_state()
                # Queue: start the oldest queued items while there are free slots
                max_c = max(1, int(self.settings.get("maxConcurrent") or 4))
                queued = sorted(
                    (it for it in self.downloads.values() if it.get("status") == "queued"),
                    key=lambda x: x.get("createdAt", 0),
                )
                for it in queued:
                    if self.active_count() >= max_c:
                        break
                    it["status"] = "paused"
                    self.start_download(it["id"])
            except Exception:
                pass

    def sync_and_repair_browser_extensions(self) -> dict:
        """
        Ensures all 7 browser extension files are present and up to date in:
        1. Primary workspace folder (project_root/browser-extension)
        2. ~/AppData/Local/Programs/ScorpionIDM/browser-extension (so existing Chrome/Edge entries work via Retry without removing/re-adding!)
        3. ~/AppData/Local/ScorpionIDM/browser-extension
        """
        repaired_paths = []
        for target_dir in (self.legacy_prog_ext_dir, self.appdata_ext_dir):
            try:
                if os.path.normcase(os.path.abspath(target_dir)) == os.path.normcase(os.path.abspath(self.ext_source_dir)):
                    continue
                os.makedirs(target_dir, exist_ok=True)
                for fname in self.REQUIRED_EXT_FILES:
                    src = os.path.join(self.ext_source_dir, fname)
                    dst = os.path.join(target_dir, fname)
                    if os.path.exists(src):
                        shutil.copy2(src, dst)
                repaired_paths.append(target_dir)
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

    def _start_browser_rpc_bridge(self):
        engine_ref = self

        class BridgeHandler(BaseHTTPRequestHandler):
            def log_message(self, format, *args):
                return

            def _origin_allowed(self) -> bool:
                """Only our browser extension or a native local process (no Origin) may talk to the bridge."""
                origin = (self.headers.get("Origin") or "").strip().lower()
                if not origin:
                    return True
                return origin.startswith(BRIDGE_ALLOWED_ORIGIN_PREFIXES)

            def _is_trusted_client(self) -> bool:
                # A custom header can't be sent cross-site without a CORS preflight, and the preflight
                # is only granted to extension origins, so web pages can't trigger state-changing calls.
                return self._origin_allowed() and self.headers.get(BRIDGE_CLIENT_HEADER) == "1"

            def _send_cors(self, code=200):
                self.send_response(code)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                origin = (self.headers.get("Origin") or "").strip()
                if origin and self._origin_allowed():
                    self.send_header("Access-Control-Allow-Origin", origin)
                    self.send_header("Vary", "Origin")
                    self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
                    self.send_header("Access-Control-Allow-Headers", f"Content-Type, {BRIDGE_CLIENT_HEADER}")
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
                    if qs.get("ext"):
                        br = (qs.get("browser") or ["chrome"])[0]
                        engine_ref.record_browser_connection(br)
                    if qs.get("set_lang") and self._is_trusted_client():
                        new_lang = (qs.get("set_lang") or [""])[0].strip().lower()
                        if new_lang in ("ar", "en") and engine_ref.settings.get("lang") != new_lang:
                            engine_ref.settings["lang"] = new_lang
                            engine_ref.save_state()
                            engine_ref.signals.lang_changed.emit(new_lang)
                    self._send_cors(200)
                    self.wfile.write(
                        json.dumps(
                            {
                                "ok": True,
                                "app": "Scorpion IDM Native",
                                "lang": engine_ref.settings.get("lang", "ar"),
                            }
                        ).encode("utf-8")
                    )
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
                        res = engine_ref.list_video_qualities(arg("url"), arg("referer"), arg("tab"))
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
                if not self._is_trusted_client():
                    self._reject()
                    return
                if parsed.path == "/capture":
                    length = min(int(self.headers.get("Content-Length") or 0), 1024 * 1024)
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

        try:
            srv = ThreadingHTTPServer(("127.0.0.1", self.rpc_port), BridgeHandler)
            self.rpc_alive = True
            srv.serve_forever()
        except Exception:
            self.rpc_alive = False

    def _load_state(self):
        try:
            if os.path.exists(self.state_file):
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data.get("settings"), dict):
                    self.settings.update(data["settings"])
                    if int(self.settings.get("defaultConnections") or 0) < 32:
                        self.settings["defaultConnections"] = 32
                for item in data.get("downloads", []):
                    if item.get("status") in ("downloading", "connecting"):
                        item["status"] = "paused"
                        item["speed"] = 0
                    dl_id = item.get("id")
                    fn = item.get("filename") or "download.bin"
                    if dl_id:
                        item["tempFilePath"] = os.path.join(self.get_item_temp_dir(dl_id), fn + ".scorpion_part")
                    self.downloads[item["id"]] = item
        except Exception:
            pass
        self._sweep_stray_part_files()

    def _sweep_stray_part_files(self):
        dl_root = self.settings.get("downloadsRoot") or self.default_dl_root
        if not os.path.isdir(dl_root):
            return
        try:
            for dirpath, _, filenames in os.walk(dl_root):
                for fn in filenames:
                    if fn.endswith((".part", ".ytdl", ".scorpion_part", ".aria2")) or "-Frag" in fn:
                        try:
                            os.remove(os.path.join(dirpath, fn))
                        except Exception:
                            pass
        except Exception:
            pass

    def save_state(self):
        with self.lock:
            try:
                with open(self.state_file, "w", encoding="utf-8") as f:
                    json.dump(
                        {"settings": self.settings, "downloads": list(self.downloads.values())},
                        f,
                        ensure_ascii=False,
                        indent=2,
                    )
            except Exception:
                pass

    def probe_url(self, url: str) -> dict:
        hdrs = {"User-Agent": self.settings["userAgent"], "Range": "bytes=0-0"}
        r = requests.get(url, headers=hdrs, stream=True, timeout=12, allow_redirects=True, verify=False)
        final_url = r.url
        status = r.status_code
        resp_headers = dict(r.headers)
        r.close()

        total_size = 0
        supports_range = False
        if status == 206:
            supports_range = True
            cr = resp_headers.get("Content-Range") or resp_headers.get("content-range") or ""
            if "/" in cr:
                try:
                    total_size = int(cr.split("/")[-1])
                except Exception:
                    pass
        elif 200 <= status < 300:
            if "bytes" in (resp_headers.get("Accept-Ranges") or "").lower():
                supports_range = True
            try:
                total_size = int(resp_headers.get("Content-Length") or 0)
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

    def add_download(self, opts: dict) -> dict:
        url = opts["url"].strip()
        total_size = int(opts.get("totalSize") or 0)
        supports_range = bool(opts.get("supportsRange", True))
        filename = opts.get("filename") or ""
        category = opts.get("category") or ""
        save_dir = opts.get("saveDir") or ""
        is_torrent = self._is_torrent_source(url, opts)
        is_video = bool(opts.get("isVideo", False)) and not is_torrent

        if total_size <= 0 and not is_video and not is_torrent:
            try:
                p = self.probe_url(url)
                url = p["url"]
                total_size = p["totalSize"]
                supports_range = p["supportsRange"]
                if not filename:
                    filename = p["filename"]
                if not category:
                    category = p["category"]
                if not save_dir:
                    save_dir = p["saveDir"]
                if p["filename"].lower().endswith(".torrent"):
                    is_torrent = True
            except Exception:
                pass

        if not filename:
            if is_torrent:
                if url.lower().startswith("magnet:?"):
                    filename = self.extract_magnet_name(url)
                else:
                    raw_fn = os.path.basename(url.split("?")[0]) or "Torrent_Download"
                    filename = raw_fn[:-8] if raw_fn.lower().endswith(".torrent") else raw_fn
            elif is_video:
                filename = "Scorpion_Video.mp4"
            else:
                filename = extract_filename(url, {})
        if is_torrent and filename.lower().endswith(".torrent"):
            filename = filename[:-8] or "Torrent_Download"
        filename = sanitize_filename(filename)
        if not category:
            category = "Video" if (is_video or is_torrent) else detect_category(filename)
        if not save_dir:
            save_dir = os.path.join(self.settings["downloadsRoot"], category)
        os.makedirs(save_dir, exist_ok=True)

        base, ext = os.path.splitext(filename)
        final_name = filename
        idx = 1
        while os.path.exists(os.path.join(save_dir, final_name)):
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
        item = {
            "id": dl_id,
            "url": url,
            "filename": final_name,
            "category": category,
            "saveDir": save_dir,
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
            "isTorrent": is_torrent,
            "videoQuality": opts.get("videoQuality", "best"),
            "referer": (opts.get("referer") or "").strip(),
            # Page the user was on when the download came from an embedded player (iframe)
            "tabUrl": (opts.get("tabUrl") or "").strip(),
            "checksumSha256": None,
            "checksumMd5": None,
        }
        with self.lock:
            self.downloads[dl_id] = item
        if opts.get("startImmediately", True):
            self.save_state()
            self.start_download(dl_id)
        else:
            # "Download later": waits for the scheduler (or a manual Resume)
            item["status"] = "scheduled"
            self.save_state()
        return item

    def start_download(self, dl_id: str):
        item = self.downloads.get(dl_id)
        if not item or item["status"] == "completed" or dl_id in self.controllers:
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
        self.save_state()

        if item.get("isTorrent") or self._is_torrent_source(item.get("url", ""), item):
            item["isTorrent"] = True
            ctrl = {"aborted": False, "last_bytes": item["downloadedBytes"], "last_time": time.time(), "file_lock": threading.Lock()}
            self.controllers[dl_id] = ctrl
            threading.Thread(target=self._run_torrent_worker, args=(item, ctrl), daemon=True).start()
            return

        u_plus_ref = ((item.get("url") or "") + " " + (item.get("referer") or "")).lower()
        if any(
            d in u_plus_ref
            for d in ("spotify.com", "soundcloud.com", "anghami.com", "deezer.com", "music.apple.com", "widevine-license")
        ):
            item["isVideo"] = True
            item["videoQuality"] = "audio"
            item["category"] = "Music"
            if any(x in (item.get("url") or "").lower() for x in ("widevine-license", "spclient.spotify.com", "/license")):
                if item.get("referer"):
                    item["url"] = item["referer"]
            self.save_state()

        if item.get("isVideo"):
            ctrl = {"aborted": False, "last_bytes": item["downloadedBytes"], "last_time": time.time(), "file_lock": threading.Lock()}
            self.controllers[dl_id] = ctrl
            threading.Thread(target=self._run_video_worker, args=(item, ctrl), daemon=True).start()
            return

        os.makedirs(item["saveDir"], exist_ok=True)
        mode = "r+b" if os.path.exists(item["tempFilePath"]) else "w+b"
        f_obj = open(item["tempFilePath"], mode)
        ctrl = {"aborted": False, "file": f_obj, "file_lock": threading.Lock(), "last_bytes": item["downloadedBytes"], "last_time": time.time(),
                "act_lock": threading.Lock(), "active": 0, "conn_limit": max(1, len(item["segments"]))}
        self.controllers[dl_id] = ctrl

        for seg in item["segments"]:
            if seg["endByte"] == -1 or seg["currentByte"] <= seg["endByte"]:
                threading.Thread(target=self._run_segment_worker, args=(item, seg, ctrl), daemon=True).start()
            else:
                seg["status"] = "completed"
                seg["info"] = "Complete"

    def _throttle(self, item: dict):
        """Per-download and global speed limits."""
        limit_kbps = item.get("speedLimitKbps") or 0
        if limit_kbps > 0 and item["speed"] > limit_kbps * 1024:
            time.sleep(0.06)
        g_limit = int(self.settings.get("globalSpeedLimitKbps") or 0)
        if g_limit > 0 and getattr(self, "total_speed", 0) > g_limit * 1024:
            time.sleep(0.06)

    def _restart_single_connection(self, item: dict, ctrl: dict):
        """Server ignores Range requests: restart the download over one plain connection."""
        with ctrl["act_lock"]:
            if ctrl.get("restarting"):
                return
            ctrl["restarting"] = True
        ctrl["aborted"] = True
        self.controllers.pop(item["id"], None)
        try:
            ctrl["file"].close()
        except Exception:
            pass
        try:
            if os.path.exists(item["tempFilePath"]):
                os.remove(item["tempFilePath"])
        except Exception:
            pass
        item["supportsRange"] = False
        item["downloadedBytes"] = 0
        item["segments"] = self._create_segments(item.get("totalSize") or 0, 1)
        item["status"] = "paused"
        self.save_state()
        self.start_download(item["id"])

    def _run_segment_worker(self, item: dict, seg: dict, ctrl: dict):
        """
        Downloads one byte range. Retries with back-off; if the server rejects many parallel
        connections (429/503/reset), the shared connection limit is lowered so the remaining
        parts continue with fewer connections instead of the whole download failing.
        """
        seg["status"] = "downloading"
        seg["info"] = "Receiving data..."
        max_attempts = 12
        attempt = 0
        try:
            while not ctrl["aborted"] and item["status"] == "downloading":
                # Wait for a free connection slot under the adaptive limit
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
                    hdrs = {"User-Agent": self.settings["userAgent"]}
                    if item.get("referer"):
                        hdrs["Referer"] = item["referer"]
                    ranged = item["supportsRange"] and seg["endByte"] >= seg["currentByte"]
                    if ranged:
                        hdrs["Range"] = f"bytes={seg['currentByte']}-{seg['endByte']}"

                    with requests.get(item["url"], headers=hdrs, stream=True, timeout=20, allow_redirects=True, verify=False) as r:
                        if r.status_code in (429, 503, 509, 403, 500, 502, 504):
                            retry_reason = f"HTTP {r.status_code}"
                        elif r.status_code not in (200, 206):
                            seg["status"] = "error"
                            seg["info"] = f"HTTP {r.status_code}"
                            return
                        elif r.status_code == 200 and ranged and seg["currentByte"] > 0:
                            # Range ignored by the server -> fall back to a single connection
                            threading.Thread(target=self._restart_single_connection, args=(item, ctrl), daemon=True).start()
                            return
                        else:
                            seg["info"] = "Receiving data..."
                            for chunk in r.iter_content(chunk_size=65536):
                                if ctrl["aborted"] or item["status"] != "downloading":
                                    return
                                if not chunk:
                                    continue
                                to_write = len(chunk)
                                if seg["endByte"] != -1:
                                    rem = seg["endByte"] - seg["currentByte"] + 1
                                    if rem <= 0:
                                        break
                                    to_write = min(to_write, rem)
                                with ctrl["file_lock"]:
                                    if ctrl["aborted"]:
                                        return
                                    ctrl["file"].seek(seg["currentByte"])
                                    ctrl["file"].write(chunk[:to_write])
                                    seg["currentByte"] += to_write
                                    seg["downloaded"] += to_write
                                    item["downloadedBytes"] += to_write
                                attempt = 0
                                self._throttle(item)
                                if seg["endByte"] != -1 and seg["currentByte"] > seg["endByte"]:
                                    break
                            finished = seg["endByte"] == -1 or seg["currentByte"] > seg["endByte"]
                            if finished:
                                if not ctrl["aborted"]:
                                    with ctrl["act_lock"]:
                                        ctrl["active"] = max(0, ctrl["active"] - 1)
                                    released = True
                                    self._on_segment_done(item, seg, ctrl)
                                return
                            retry_reason = "Connection dropped"
                except Exception as e:
                    retry_reason = str(e)[:35]
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

        hdrs = {"User-Agent": BROWSER_UA}
        if referer:
            hdrs["Referer"] = referer
        try:
            html = requests.get(page_url, headers=hdrs, timeout=15, verify=False).text
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
        found = re.findall(r"""https?://[^\s"'<>\\]+?\.(?:m3u8|mpd|mp4)(?:\?[^\s"'<>\\]*)?""", html, re.I)
        # relative manifest paths like file:"/hls/xyz/master.m3u8"
        for rel in re.findall(r"""["'](/[^"'\s]+?\.m3u8(?:\?[^"'\s]*)?)["']""", html, re.I):
            found.append(urllib.parse.urljoin(page_url, rel))
        uniq = []
        for u in found:
            if u not in uniq and not re.search(r"\.(jpg|png|gif)\b", u, re.I):
                uniq.append(u)
        uniq.sort(key=lambda u: (0 if ".m3u8" in u.lower() else 1, 0 if "master" in u.lower() else 1))
        return uniq[:6]

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
            "web player",
            "you",
            "search",
        }
        if raw.lower() not in generic_names and len(raw) >= 3:
            return raw

        for page_url in (item.get("url") or "", item.get("referer") or ""):
            if not page_url.startswith(("http://", "https://")):
                continue
            if any(x in page_url.lower() for x in ("widevine", "spclient.spotify.com", "/license")):
                continue
            try:
                resp = requests.get(page_url, headers={"User-Agent": BROWSER_UA}, timeout=10, verify=False)
                html_txt = resp.text
                m_og = re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)["\']', html_txt, re.I)
                m_desc = re.search(
                    r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\']([^"\']+)["\']', html_txt, re.I
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

        return raw

    def _extract_with_fallback(self, ydl, item: dict):
        """Try yt-dlp on the URL; for DRM/music sites or unsupported pages, fall back to audio search or stream scraping."""
        u_low = (item.get("url") or "").lower().strip()
        u_clean = u_low.split("?")[0].rstrip("/")
        is_audio = item.get("videoQuality") == "audio" or item.get("category") == "Music"

        def _unwrap_info(info_obj):
            if isinstance(info_obj, dict) and info_obj.get("entries"):
                entries = [e for e in info_obj["entries"] if e]
                if entries:
                    return entries[0]
            return info_obj

        def _extract_via_audio_search():
            query = self._build_audio_search_query(item)
            if not query:
                return None
            saved_hdrs = dict(ydl.params.get("http_headers") or {})
            try:
                clean_hdrs = {k: v for k, v in saved_hdrs.items() if k.lower() not in ("referer", "origin")}
                ydl.params["http_headers"] = clean_hdrs
                res = _unwrap_info(ydl.extract_info(f"ytsearch1:{query}", download=False))
                if res:
                    return res
            except Exception:
                pass
            finally:
                ydl.params["http_headers"] = saved_hdrs
            return None

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
        if is_audio and (any(d in u_low for d in drm_music_domains) or u_clean in sc_generic_paths):
            found_info = _extract_via_audio_search()
            if found_info:
                return found_info

        try:
            return _unwrap_info(ydl.extract_info(item["url"], download=False))
        except Exception as first_err:
            if is_audio:
                found_info = _extract_via_audio_search()
                if found_info:
                    return found_info
            # An embedded player's address may not identify the video; the page around it usually does
            tab_url = (item.get("tabUrl") or "").strip()
            if tab_url.lower().startswith(("http://", "https://")) and tab_url != item["url"]:
                try:
                    info = _unwrap_info(ydl.extract_info(tab_url, download=False))
                    item["url"] = tab_url
                    return info
                except Exception:
                    pass
            if not item["url"].lower().split("?")[0].endswith((".html", ".htm", "/")) and "unsupported url" not in str(first_err).lower():
                raise
            for cand in self._scrape_media_urls(item["url"], item.get("referer") or item["url"]):
                try:
                    info = _unwrap_info(ydl.extract_info(cand, download=False))
                    item["url"] = cand
                    return info
                except Exception:
                    continue
            raise RuntimeError(
                "الموقع ده بيخفي رابط الفيديو. شغّل الفيديو الأول لثواني ثم اضغط زر التحميل تاني "
                "علشان الإضافة تلتقط الرابط المباشر من المشغل."
            ) from first_err

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

    def list_video_qualities(self, url: str, referer: str = "", tab_url: str = "") -> dict:
        """
        Every video quality a page offers (as yt-dlp sees it), for the quality pickers in the browser
        button and the Add Download dialog. Cached for a few minutes per address.
        """
        url = (url or "").strip()
        if not url.lower().startswith(("http://", "https://")) or not HAS_YTDLP:
            return {"ok": False, "qualities": []}
        cache = self.__dict__.setdefault("_quality_cache", {})
        hit = cache.get(url)
        if hit and time.time() - hit[0] < 600:
            return hit[1]

        class _Quiet:
            def debug(self, msg):
                pass

            info = warning = error = debug

        opts = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True,
                "nocheckcertificate": True, "logger": _Quiet()}
        opts.update(self._js_runtime_opts())
        if referer:
            pr = urllib.parse.urlparse(referer)
            opts["http_headers"] = {"Referer": referer, "Origin": f"{pr.scheme}://{pr.netloc}", "User-Agent": BROWSER_UA}
        item = {"url": url, "referer": referer, "tabUrl": tab_url, "videoQuality": "best", "category": ""}
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = self._extract_with_fallback(ydl, item)
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
        cache[url] = (time.time(), res)
        return res

    def get_item_temp_dir(self, dl_id: str) -> str:
        d = os.path.join(self.temp_root, str(dl_id))
        os.makedirs(d, exist_ok=True)
        return d

    def _cleanup_item_temp(self, item: dict):
        if not item:
            return
        dl_id = item.get("id")
        if dl_id:
            shutil.rmtree(os.path.join(self.temp_root, str(dl_id)), ignore_errors=True)
        tp = item.get("tempFilePath")
        if tp and os.path.exists(tp):
            try:
                os.remove(tp)
            except Exception:
                pass
        save_dir = item.get("saveDir")
        file_path = item.get("filePath")
        if save_dir and file_path and os.path.isdir(save_dir):
            base_prefix = os.path.splitext(os.path.basename(file_path))[0]
            try:
                for fn in os.listdir(save_dir):
                    if fn.startswith(base_prefix) and (
                        fn.endswith((".part", ".ytdl", ".scorpion_part")) or "-Frag" in fn
                    ):
                        try:
                            os.remove(os.path.join(save_dir, fn))
                        except Exception:
                            pass
            except Exception:
                pass

    def _probe_video_stream_range(self, url: str, headers: dict, fallback_size: int = 0) -> tuple:
        """Verify HTTP 206 Range support and return (exact_size, supports_range) for a video stream."""
        try:
            h = dict(headers or {})
            h["Range"] = "bytes=0-0"
            r = requests.get(url, headers=h, stream=True, timeout=10, allow_redirects=True, verify=False)
            status = r.status_code
            cr = r.headers.get("Content-Range", "")
            cl = r.headers.get("Content-Length", "")
            r.close()
            if status == 206 and "/" in cr:
                tot_str = cr.split("/")[-1].strip()
                if tot_str.isdigit() and int(tot_str) > 0:
                    return int(tot_str), True
            if status == 206 and fallback_size > 0:
                return fallback_size, True
            if status == 200 and cl.isdigit() and int(cl) > 0:
                return int(cl), False
        except Exception:
            pass
        return fallback_size, False

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
                        "label": f"{s_spec['kind']} #{seg_id}",
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

            hdrs = {"User-Agent": BROWSER_UA}
            if item.get("referer") and "googlevideo.com" not in s_url.lower():
                hdrs["Referer"] = item["referer"]
            if isinstance(f.get("http_headers"), dict):
                hdrs.update(f["http_headers"])

            approx = int(f.get("filesize") or f.get("filesize_approx") or 0)
            exact_sz, ok_range = self._probe_video_stream_range(s_url, hdrs, approx)
            if not ok_range or exact_sz <= 0:
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

        # Resume support: reuse the previous layout if the same streams (same sizes) and part files are still there
        layout_sig = [[sp["idx"], sp["size"], n] for sp, n in zip(stream_specs, port_alloc)]
        prev_segs = item.get("segments") or []
        can_resume = (
            item.get("videoLayout") == layout_sig
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
            item["totalSize"] = sum(sp["size"] for sp in stream_specs)
            item["downloadedBytes"] = 0
            item["supportsRange"] = True
            item["useRangeVideoEngine"] = True
            item["phase"] = "downloading"
            ctrl["last_bytes"] = 0
            ctrl["last_time"] = time.time()
            ctrl["video_stream_files"] = [sp["fh"] for sp in stream_specs]
            self.save_state()

        def port_worker(seg: dict, sp: dict):
            is_yt_cdn = "googlevideo.com" in sp["url"].lower()
            block_size = 4 * 1024 * 1024  # 4 MB range blocks bypass YouTube single-stream throttling
            retries = 0
            while seg["localCur"] <= seg["localEnd"] and not ctrl["aborted"]:
                req_start = seg["localCur"]
                req_end = min(seg["localEnd"], req_start + block_size - 1) if is_yt_cdn else seg["localEnd"]
                hdrs = dict(sp["headers"])
                hdrs["Range"] = f"bytes={req_start}-{req_end}"
                try:
                    with requests.get(
                        sp["url"], headers=hdrs, stream=True, timeout=20, allow_redirects=True, verify=False
                    ) as resp:
                        if resp.status_code not in (200, 206):
                            raise RuntimeError(f"HTTP {resp.status_code}")
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
                            limit_kbps = item.get("speedLimitKbps") or 0
                            if limit_kbps > 0 and item["speed"] > limit_kbps * 1024:
                                time.sleep(0.05)
                            if seg["localCur"] > req_end:
                                break
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

        if any(s["status"] != "completed" for s in new_segs):
            # Clean up partial files and fall back to yt-dlp if any range worker failed permanently
            for sp in stream_specs:
                try:
                    if os.path.exists(sp["partPath"]):
                        os.remove(sp["partPath"])
                except Exception:
                    pass
            item["useRangeVideoEngine"] = False
            return False

        # Merge / finalize output
        item["phase"] = "merging"
        item["speed"] = 0
        no_win = 0x08000000 if os.name == "nt" else 0
        if len(stream_specs) == 2 and has_ffmpeg:
            final_out = base_no_ext + ".mp4"
            subprocess.run(
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
            for sp in stream_specs:
                try:
                    os.remove(sp["partPath"])
                except Exception:
                    pass
            if os.path.exists(final_out):
                item["filePath"] = final_out
                item["filename"] = os.path.basename(final_out)
                item["totalSize"] = os.path.getsize(final_out)
                item["downloadedBytes"] = item["totalSize"]
        else:
            sp0 = stream_specs[0]
            if q == "audio" and has_ffmpeg:
                final_out = base_no_ext + ".mp3"
                subprocess.run(
                    [ffmpeg_bin, "-y", "-i", sp0["partPath"], "-vn", "-ab", "192k", final_out],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    creationflags=no_win,
                    check=False,
                )
                try:
                    os.remove(sp0["partPath"])
                except Exception:
                    pass
            else:
                out_ext = ".mp3" if q == "audio" else (".mp4" if sp0["ext"] in ("mp4", "m4a", "webm") else f".{sp0['ext']}")
                final_out = base_no_ext + out_ext
                if os.path.exists(final_out):
                    try:
                        os.remove(final_out)
                    except Exception:
                        pass
                shutil.move(sp0["partPath"], final_out)
            if os.path.exists(final_out):
                item["filePath"] = final_out
                item["filename"] = os.path.basename(final_out)
                item["totalSize"] = os.path.getsize(final_out)
                item["downloadedBytes"] = item["totalSize"]

        self._cleanup_item_temp(item)
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

        def hook(d):
            if ctrl["aborted"]:
                raise RuntimeError("Paused")
            segs = item.get("segments") or []
            if not segs:
                return
            if d["status"] == "downloading":
                item["phase"] = "downloading"
                dl_b = int(d.get("downloaded_bytes") or 0)
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
            "progress_hooks": [hook],
            "quiet": True,
            "no_warnings": True,
            "nocheckcertificate": True,
            "concurrent_fragment_downloads": n_ports,
            "logger": QuietYtdlpLogger(),
        }
        if item.get("referer"):
            ref = item["referer"]
            pr = urllib.parse.urlparse(ref)
            ydl_opts["http_headers"] = {
                "Referer": ref,
                "Origin": f"{pr.scheme}://{pr.netloc}",
                "User-Agent": BROWSER_UA,
            }
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
                if ctrl["aborted"]:
                    return
                reqs = info.get("requested_formats") or [info]

                # 2) Try Scorpion's 16-port HTTP Range Video Engine first (for YouTube / MP4 streams)
                handled_by_16_ports = self._download_video_streams_16ports(
                    item, ctrl, reqs, base_no_ext, ffmpeg_bin, has_ffmpeg, q
                )
                if ctrl["aborted"]:
                    return

                # 3) If HLS (.m3u8) / DASH (.mpd), run yt-dlp with 16 parallel fragment ports
                if not handled_by_16_ports:
                    is_ar = self.settings.get("lang", "ar") == "ar"
                    kind_lbl = "بورت فيديو" if is_ar else "Video Port"
                    tot_est = sum(int(f.get("filesize") or f.get("filesize_approx") or 0) for f in reqs)
                    per_p = max(1, tot_est // n_ports) if tot_est > 0 else 0
                    item["segments"] = [
                        {
                            "id": i,
                            "formatId": "",
                            "label": f"{kind_lbl} #{i}",
                            "size": per_p,
                            "downloaded": 0,
                            "startByte": (i - 1) * per_p,
                            "endByte": (i * per_p - 1) if per_p else -1,
                            "currentByte": (i - 1) * per_p,
                            "status": "downloading",
                            "info": f"Port #{i}",
                        }
                        for i in range(1, n_ports + 1)
                    ]
                    item["totalSize"] = tot_est
                    item["supportsRange"] = True
                    item["phase"] = "downloading"

                    info = ydl.process_ie_result(info, download=True)
                    actual_temp = ydl.prepare_filename(info)
                    chosen_ext = os.path.splitext(actual_temp)[1] or ".mp4"
                    for cand_ext in (".mp3", ".mp4", ".m4a", ".mkv", ".webm"):
                        cand_temp = temp_base + cand_ext
                        if os.path.exists(cand_temp):
                            actual_temp = cand_temp
                            chosen_ext = cand_ext
                            break
                    if os.path.exists(actual_temp):
                        final_dest = base_no_ext + chosen_ext
                        os.makedirs(os.path.dirname(final_dest), exist_ok=True)
                        if os.path.exists(final_dest):
                            try:
                                os.remove(final_dest)
                            except Exception:
                                pass
                        shutil.move(actual_temp, final_dest)
                        item["filePath"] = final_dest
                        item["filename"] = os.path.basename(final_dest)
                        item["totalSize"] = os.path.getsize(final_dest)
                        item["downloadedBytes"] = item["totalSize"]

            # A "video" with no picture means the page handed over the wrong file (e.g. an interface sound)
            fp = item.get("filePath") or ""
            if q != "audio" and os.path.isfile(fp) and self._has_video_stream(fp) is False:
                try:
                    os.remove(fp)
                except OSError:
                    pass
                raise RuntimeError(
                    "الملف اللي وصل من الصفحة مفيهوش فيديو (غالبًا صوت من واجهة الموقع). "
                    "شغّل الفيديو واضغط زر التحميل اللي فوقه، أو انسخ رابط المنشور نفسه."
                )

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
            item["useRangeVideoEngine"] = False
            self.controllers.pop(item["id"], None)
            if not ctrl["aborted"]:
                msg = str(err).replace("ERROR:", "").strip()
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
                "label": f"{port_lbl} #{i}",
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
                resp = requests.get(src, headers=hdrs, timeout=15, allow_redirects=True, verify=False)
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
            def effective_limit() -> int:
                lims = [int(item.get("speedLimitKbps") or 0), int(self.settings.get("globalSpeedLimitKbps") or 0)]
                lims = [x for x in lims if x > 0]
                return min(lims) if lims else 0

            last_limit = -1
            while not ctrl["aborted"]:
                time.sleep(0.35)
                if ctrl["aborted"]:
                    break

                cur_limit = effective_limit()
                if cur_limit != last_limit:
                    last_limit = cur_limit
                    try:
                        rpc_call(
                            "aria2.changeGlobalOption",
                            [{"max-overall-download-limit": f"{cur_limit}K" if cur_limit > 0 else "0"}],
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
                    continue

                st = st_obj.get("status", "active")
                tot_b = int(st_obj.get("totalLength") or 0)
                dl_b = int(st_obj.get("completedLength") or 0)
                spd = int(st_obj.get("downloadSpeed") or 0)
                peers = int(st_obj.get("connections") or 0)
                seeders = int(st_obj.get("numSeeders") or 0)
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
                    files = st_obj.get("files") or []
                    # Stop the engine so no file handles stay open, then move finished data out of temp
                    if proc and proc.poll() is None:
                        try:
                            proc.terminate()
                            proc.wait(timeout=5)
                        except Exception:
                            pass
                    final_path = self._move_torrent_output(bt_dir, item["saveDir"], files)
                    if final_path:
                        item["filePath"] = final_path
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
        """Delete unselected leftovers, move finished torrent data into save_dir. Returns the main output path."""
        for f_ in files or []:
            if str(f_.get("selected", "true")).lower() == "false" and f_.get("path"):
                try:
                    if os.path.isfile(f_["path"]):
                        os.remove(f_["path"])
                except Exception:
                    pass
        moved = []
        try:
            entries = [e for e in os.listdir(bt_dir) if not e.lower().endswith(".aria2")]
        except Exception:
            entries = []
        for name in entries:
            src_p = os.path.join(bt_dir, name)
            base, ext = os.path.splitext(name) if os.path.isfile(src_p) else (name, "")
            dest = os.path.join(save_dir, name)
            n = 1
            while os.path.exists(dest):
                dest = os.path.join(save_dir, f"{base} ({n}){ext}")
                n += 1
            try:
                shutil.move(src_p, dest)
                moved.append(dest)
            except Exception:
                pass
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
        return save_dir if moved else ""

    def _finalize(self, item: dict, ctrl: dict):
        self.controllers.pop(item["id"], None)
        try:
            ctrl["file"].close()
            if os.path.exists(item["tempFilePath"]):
                if os.path.exists(item["filePath"]):
                    os.remove(item["filePath"])
                shutil.move(item["tempFilePath"], item["filePath"])
        except Exception:
            pass
        self._cleanup_item_temp(item)
        item["downloadedBytes"] = item["totalSize"] or item["downloadedBytes"]
        item["totalSize"] = item["downloadedBytes"]
        item["progress"] = 100.0
        item["speed"] = 0
        item["timeLeft"] = 0
        item["finishedAt"] = time.time()
        item["status"] = "completed"
        self.save_state()
        self.signals.completed.emit(item["id"])

    def pause_download(self, dl_id: str):
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
        item = self.downloads.pop(dl_id, None)
        if item:
            self._cleanup_item_temp(item)
        self.save_state()

    def delete_completed(self):
        for k in [k for k, v in self.downloads.items() if v["status"] == "completed"]:
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
            now = time.time()
            # Total speed of all running downloads (used by the global speed limit)
            self.total_speed = sum(
                int(it.get("speed") or 0) for it in list(self.downloads.values()) if it.get("status") == "downloading"
            )
            for dl_id, ctrl in list(self.controllers.items()):
                item = self.downloads.get(dl_id)
                if not item or item["status"] != "downloading":
                    continue
                if item.get("isTorrent") or (item.get("isVideo") and not item.get("useRangeVideoEngine")):
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


# ==============================================================================
# INTERACTIVE 3-SCREEN BROWSER SETUP WIZARD (CHROME / EDGE / BRAVE)
# ==============================================================================
BROWSER_SPECS = [
    ("chrome", "Google Chrome", "chrome://extensions", "#2563eb"),
    ("msedge", "Microsoft Edge", "edge://extensions", "#0284c7"),
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
    """Paints a visual 3-step illustration showing Developer Mode, Load Unpacked, and Ctrl+V."""

    def __init__(self, is_ar: bool = True, parent=None):
        super().__init__(parent)
        self.is_ar = is_ar
        self.setMinimumHeight(195)

    def paintEvent(self, _e):
        p = pal()
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()

        # Three visual step cards side by side (in RTL: Step 1 on Right, Step 2 in Center, Step 3 on Left)
        gap = 12
        card_w = (w - gap * 2) / 3.0
        card_h = h - 4

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

            if kind == "toggle":
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
                QRectF(x + 8, 124, card_w - 16, 24),
                Qt.AlignmentFlag.AlignCenter,
                title,
            )

            painter.setPen(QColor(p["success"] if kind == "keys" else p["muted"]))
            f_s = painter.font()
            f_s.setBold(kind == "keys")
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
            "معالج ربط المتصفحات الذكي — Scorpion IDM"
            if self.is_ar
            else "Smart Browser Setup Wizard — Scorpion IDM"
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
                    f"background: {p['accent']}; color: #ffffff; font-weight: 700; font-size: 12px; "
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
            "اختر المتصفح الذي تريد ربطه ببرنامج Scorpion IDM:"
            if self.is_ar
            else "Select the browser you want to integrate with Scorpion IDM:"
        )
        h_lbl.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {p['text']};")
        ic_lay.addWidget(h_lbl)

        s_lbl = QLabel(
            "سيقوم المعالج بتجهيز ملفات الإضافة في مسار النظام الدائم، ونسخ المسار، وفتح صفحة التفعيل، والانتقال تلقائياً بمجرد تفعيلها."
            if self.is_ar
            else "The wizard prepares the extension files in a permanent path, copies the path, opens the extensions page, and detects activation automatically."
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

        for br_key, br_name, _ext_url, _accent in BROWSER_SPECS:
            w = self.br_cards_widgets[br_key]
            exe_path = self._find_browser_exe(br_key)
            installed = os.path.exists(exe_path)
            is_conn = br_key in connected_list

            if is_conn:
                w["conn_pill"].setText("✓ متصل ومفعّل" if self.is_ar else "✓ Connected")
                w["conn_pill"].setStyleSheet(
                    f"background: {p['accent_soft']}; color: {p['success']}; font-weight: 700; "
                    f"font-size: 12px; padding: 4px 12px; border-radius: 11px;"
                )
                w["conn_pill"].show()
                w["status_lbl"].setText(
                    "الإضافة مفعّلة في المتصفح وتلتقط التحميلات والفيديوهات تلقائياً"
                    if self.is_ar
                    else "Extension is active and capturing downloads & videos automatically"
                )
                w["btn"].setText("إعادة الفتح / فحص" if self.is_ar else "Re-open / Check")
                w["btn"].setObjectName("")
            elif installed:
                w["conn_pill"].hide()
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

        btn_recopy = QPushButton("نسخ المسار ✓" if self.is_ar else "Copy Path ✓")
        btn_recopy.clicked.connect(self.copy_ext_path)
        path_row.addWidget(btn_recopy)

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
            "تم الاتصال بنجاح بين إضافة المتصفح وبرنامج Scorpion IDM!"
            if self.is_ar
            else "Browser extension is now actively linked to Scorpion IDM!"
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
                "✓  ظهور زر «تحميل الفيديو بواسطة Scorpion IDM» تلقائياً أعلى أي فيديو مع اختيار الجودة",
                "✓  Floating 'Download Video with Scorpion IDM' button appears on video players",
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

    def copy_ext_path(self) -> str:
        perm_dir = self.engine.get_permanent_ext_dir()
        if self.parent_win:
            self.parent_win.last_clip = perm_dir
        QApplication.clipboard().setText(perm_dir)
        return perm_dir

    def start_browser_wizard(self, br_key: str, br_name: str, ext_url: str):
        self.selected_browser_key = br_key
        self.selected_browser_name = br_name
        self.selected_ext_url = ext_url
        self.wait_started_at = time.time()

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
        self.copy_ext_path()
        exe = self._find_browser_exe(self.selected_browser_key)
        try:
            subprocess.Popen([exe, self.selected_ext_url])
        except Exception:
            pass

    def _on_extension_ping_received(self, br_key: str):
        if self.stack.currentIndex() == 1:
            if br_key == self.selected_browser_key or (time.time() - self.wait_started_at) >= 0:
                self._transition_to_success(br_key)
        elif self.stack.currentIndex() == 0:
            self._refresh_screen_1_cards()

    def _poll_connection_state(self):
        if self.stack.currentIndex() == 1 and self.wait_started_at > 0:
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
            fill = QRectF(bar.right() - fw, bar.top(), fw, bar_h) if rtl else QRectF(bar.left(), bar.top(), fw, bar_h)
            fp = QPainterPath()
            fp.addRoundedRect(fill, bar_h / 2, bar_h / 2)
            painter.fillPath(fp, QColor(mode_color(mode)))

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
        self.setWindowTitle(T("الإعدادات — Scorpion IDM", "Settings — Scorpion IDM"))
        self.resize(620, 560)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        def card(title: str):
            fr = QFrame()
            fr.setObjectName("CardFrame")
            lay = QGridLayout(fr)
            lay.setContentsMargins(16, 12, 16, 14)
            lay.setHorizontalSpacing(12)
            lay.setVerticalSpacing(10)
            hdr = QLabel(title)
            hdr.setStyleSheet("font-size: 14px; font-weight: 700;")
            lay.addWidget(hdr, 0, 0, 1, 3)
            root.addWidget(fr)
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
        self.cmb_conn = QComboBox()
        self.cmb_conn.addItems(["1", "4", "8", "16", "32", "64"])
        self.cmb_conn.setCurrentText(str(s.get("defaultConnections", 32)))
        g.addWidget(self.cmb_conn, 2, 1)

        g.addWidget(QLabel(T("أقصى عدد تحميلات في نفس الوقت:", "Max simultaneous downloads:")), 3, 0)
        self.spin_max = QSpinBox()
        self.spin_max.setRange(1, 20)
        self.spin_max.setValue(int(s.get("maxConcurrent", 4)))
        g.addWidget(self.spin_max, 3, 1)

        g.addWidget(QLabel(T("حد السرعة الكلي (KB/s) — 0 بدون حد:", "Global speed limit (KB/s) — 0 = none:")), 4, 0)
        self.spin_glimit = QSpinBox()
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
        self.chk_assoc = QCheckBox(T("فتح ملفات التورنت وروابط ماجنت بالبرنامج","Open .torrent files and Magnet links with Scorpion"))
        self.chk_assoc.setChecked(bool(s.get("associateTorrents", True)))
        g2.addWidget(self.chk_assoc, 4, 0, 1, 3)
        g2.addWidget(QLabel(T("عند بدء أي تحميل يظهر:", "When a download starts, show:")), 5, 0)
        self.cmb_on_start = QComboBox()
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
        hh, mm = (s.get("schedTime") or "02:00").split(":")[:2]
        self.time_sched.setTime(QTime(int(hh), int(mm)))
        self.time_sched.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        g3.addWidget(self.time_sched, 1, 2)

        root.addStretch()
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

    def _save(self):
        s = self.engine.settings
        new_root = self.txt_root.text().strip() or self.engine.default_dl_root
        try:
            os.makedirs(new_root, exist_ok=True)
            for cat in list(CATEGORY_MAP.keys()) + ["General"]:
                os.makedirs(os.path.join(new_root, cat), exist_ok=True)
        except Exception as e:
            QMessageBox.warning(self, "Scorpion IDM", str(e))
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
        apply_shell_integration(s)
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
        self.info = update_info or self.engine.check_for_updates()
        self._updating = False

        self.setWindowTitle(
            self.T("تحديثات البرنامج وسجل الإضافات — Scorpion IDM", "Software Updates & What's New — Scorpion IDM")
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

        self.lbl_headline = QLabel()
        self.lbl_headline.setStyleSheet("font-size: 16px; font-weight: 700;")
        bl.addWidget(self.lbl_headline)

        self.lbl_sub = QLabel()
        self.lbl_sub.setObjectName("Muted")
        self.lbl_sub.setWordWrap(True)
        bl.addWidget(self.lbl_sub)
        root.addWidget(banner)

        # 2) Release Notes ("What's New") Card
        notes_card = QFrame()
        notes_card.setObjectName("CardFrame")
        nl = QVBoxLayout(notes_card)
        nl.setContentsMargins(16, 14, 16, 14)
        nl.setSpacing(8)

        self.lbl_notes_title = QLabel()
        self.lbl_notes_title.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {c['accent']};")
        nl.addWidget(self.lbl_notes_title)

        self.lbl_notes_body = QLabel()
        self.lbl_notes_body.setWordWrap(True)
        self.lbl_notes_body.setAlignment(
            (Qt.AlignmentFlag.AlignRight if self.is_ar else Qt.AlignmentFlag.AlignLeft) | Qt.AlignmentFlag.AlignTop
        )
        self.lbl_notes_body.setStyleSheet("line-height: 1.5; font-size: 13px; background: transparent;")
        notes_scroll = QScrollArea()
        notes_scroll.setWidgetResizable(True)
        notes_scroll.setFrameShape(QFrame.Shape.NoFrame)
        notes_scroll.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        notes_scroll.setWidget(self.lbl_notes_body)
        nl.addWidget(notes_scroll, 1)
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
        self.btn_update_now.setIcon(glyph_icon(ICONS["download"], "#ffffff"))
        self.btn_update_now.setMinimumWidth(165)
        self.btn_update_now.clicked.connect(self._start_update_now)

        btns.addWidget(self.btn_close)
        btns.addWidget(self.btn_update_now)
        root.addLayout(btns)

        self._refresh_view()

    def _save_prefs(self):
        self.engine.settings["autoCheckUpdates"] = True
        self.engine.save_state()

    def _save_and_close(self):
        self._save_prefs()
        self.accept()

    def _refresh_view(self):
        c = pal()
        has_upd = bool(self.info.get("hasUpdate"))
        error = (self.info.get("error") or "").strip()
        if " / " in error:  # friendly errors are stored as "Arabic / English"
            error = error.split(" / ", 1)[0 if self.is_ar else 1]
        lat_ver = self.info.get("latestVersion") or APP_VERSION
        pub_date = self.info.get("publishedAt") or CHANGELOG_HISTORY[0]["date"]
        checked = self.info.get("checkedAt") or ""
        checked_txt = self.T(f"آخر فحص: {L(checked)}", f"Last checked: {checked}") if checked else ""
        # "Update Now" only exists when there is something to install
        self.btn_update_now.setVisible(has_upd)
        if not self._updating:
            self.btn_update_now.setEnabled(has_upd)

        if has_upd:
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
                f"🎉 تم تحديث البرنامج بنجاح إلى الإصدار {L('v' + APP_VERSION)}!",
                f"🎉 Successfully Updated to Version v{APP_VERSION}!",
            ), c["success"]
            sub = self.T("إليك ما الجديد في هذا الإصدار:", "Here is what's new in this version:")
        else:
            headline, color = self.T(
                f"✅ برنامجك محدث إلى آخر إصدار ({L('v' + APP_VERSION)})",
                f"✅ Scorpion IDM is up to date (v{APP_VERSION})",
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
        lines = [f"•  {line}" for line in notes_list]
        for prev in history:
            lines.append("")
            lines.append(f"── {prev['title_ar' if self.is_ar else 'title_en']} ({L(prev['date'])}) ──")
            for pline in prev["ar" if self.is_ar else "en"]:
                lines.append(f"•  {pline}")
        self.lbl_notes_body.setText("\n".join(lines))

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
                        "Applying update files and restarting Scorpion IDM...",
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
        self.setWindowTitle(T("اختيار ملفات التورنت", "Select torrent files") + f" — {item.get('filename', '')}")
        self.resize(680, 480)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 14, 16, 14)
        self.lbl_total = QLabel()
        self.lbl_total.setStyleSheet("font-weight: 700;")
        lay.addWidget(self.lbl_total)

        self.tree = QTreeWidget()
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
    if os.name != "nt" or not INSTALLED:
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
    if os.name != "nt" or not INSTALLED:
        return
    import winreg
    cmd = f'{app_launch_command()} "%1"'
    # The runtime exe carries Python's icon (changing it would break its signature), so point at ours
    scorpion_ico = os.path.join(RESOURCE_ROOT, "build", "icon.ico")
    icon = scorpion_ico if EMBEDDED_RUNTIME and os.path.isfile(scorpion_ico) else f"{sys.executable},0"
    try:
        if enabled:
            base = rf"Software\Classes\{TORRENT_PROGID}"
            _reg_set(base, "", "Torrent File (Scorpion IDM)")
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
    if os.name != "nt":
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

    start_lnk = os.path.join(
        os.environ.get("APPDATA", ""),
        "Microsoft",
        "Windows",
        "Start Menu",
        "Programs",
        "Scorpion Download Manager.lnk",
    )
    if not os.path.exists(start_lnk):
        create_shortcut_native(start_lnk, target_exe, work_dir, icon_path)

    desktop_lnk = os.path.join(os.path.expanduser("~"), "Desktop", "Scorpion Download Manager.lnk")
    if settings.get("desktopShortcut", True) and not os.path.exists(desktop_lnk):
        create_shortcut_native(desktop_lnk, target_exe, work_dir, icon_path)


def apply_shell_integration(settings: dict):
    set_start_with_windows(bool(settings.get("startWithWindows", True)))
    set_torrent_association(bool(settings.get("associateTorrents", True)))
    ensure_app_shortcuts(settings)


def item_mode(it: dict) -> str:
    st = it.get("status")
    if st == "completed":
        return "done"
    if st == "error":
        return "error"
    if st in ("paused", "queued", "scheduled"):
        return "paused"
    if st == "downloading" and (it.get("phase") in ("connecting", "merging", "selecting") or not it.get("downloadedBytes")):
        return "connecting"
    return "active"


def item_status_text(it: dict, is_ar: bool) -> str:
    m = item_mode(it)
    st = it.get("status")
    if st == "queued":
        return "في الانتظار" if is_ar else "Queued"
    if st == "scheduled":
        return "مجدول" if is_ar else "Scheduled"
    if it.get("phase") == "merging" and m == "connecting":
        return "جاري الدمج" if is_ar else "Merging"
    if it.get("phase") == "selecting":
        return "اختيار الملفات" if is_ar else "Select files"
    return {
        "done": ("مكتمل", "Completed"),
        "error": ("فشل", "Failed"),
        "paused": ("متوقف", "Paused"),
        "connecting": ("جاري الاتصال", "Connecting"),
        "active": ("جاري التحميل", "Downloading"),
    }[m][0 if is_ar else 1]

class DownloadCard(QWidget):
    """Small card in the screen corner for one download: live progress, then Open / Show in folder."""

    action = pyqtSignal(str, str)  # download id, action

    W, H = 384, 132

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
        self.setFixedSize(self.W, self.H)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight)
        c = pal()

        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 8, 8, 8)
        self.body = QFrame()
        self.body.setObjectName("ToastCard")
        self.body.setStyleSheet(
            f"#ToastCard {{ background: {c['surface']}; border: 1px solid {c['border']}; border-radius: 12px; }}"
            f"#ToastCard QLabel {{ background: transparent; }}"
        )
        shadow = QGraphicsDropShadowEffect(self.body)
        shadow.setBlurRadius(18)
        shadow.setOffset(0, 3)
        shadow.setColor(QColor(0, 0, 0, 70))
        self.body.setGraphicsEffect(shadow)
        outer.addWidget(self.body)

        lay = QVBoxLayout(self.body)
        lay.setContentsMargins(12, 9, 10, 9)
        lay.setSpacing(5)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.icon = QLabel()
        self.icon.setFixedSize(22, 22)
        top.addWidget(self.icon)
        self.name = QLabel()
        self.name.setStyleSheet("font-weight: 600;")
        top.addWidget(self.name, 1)
        self.btn_close = QPushButton()
        self.btn_close.setObjectName("ToolBtn")
        self.btn_close.setFixedSize(24, 24)
        self.btn_close.setIcon(glyph_icon(ICONS["close"], c["muted"], 12))
        self.btn_close.setToolTip(self.T("إغلاق", "Close"))
        self.btn_close.clicked.connect(lambda: self.action.emit(self.dl_id, "close"))
        top.addWidget(self.btn_close)
        lay.addLayout(top)

        self.status = QLabel()
        self.status.setObjectName("Muted")
        lay.addWidget(self.status)
        self.bar = SlimProgressBar()
        self.bar.setFixedHeight(6)
        lay.addWidget(self.bar)

        btns = QHBoxLayout()
        btns.setSpacing(6)
        btns.addStretch()
        self.btn_b = QPushButton()
        self.btn_a = QPushButton()
        for b in (self.btn_b, self.btn_a):
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedHeight(30)
            b.setStyleSheet("padding: 2px 14px;")
            btns.addWidget(b)
        self.btn_a.clicked.connect(lambda: self.action.emit(self.dl_id, self.btn_a.property("act")))
        self.btn_b.clicked.connect(lambda: self.action.emit(self.dl_id, self.btn_b.property("act")))
        lay.addLayout(btns)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def _set_buttons(self, a: tuple, b: tuple, primary_a: bool = False):
        for btn, (text, act) in ((self.btn_a, a), (self.btn_b, b)):
            btn.setText(text)
            btn.setProperty("act", act)
        self.btn_a.setObjectName("PrimaryBtn" if primary_a else "")
        self.btn_a.style().unpolish(self.btn_a)
        self.btn_a.style().polish(self.btn_a)

    def update_from(self, item: dict):
        T = self.T
        c = pal()
        mode = item_mode(item)
        pct = 100.0 if item.get("status") == "completed" else float(item.get("progress") or 0)
        name = item.get("filename") or ""
        if getattr(self, "_full_name", None) != name:
            self._full_name = name
            self._elide_name()
            self.icon.setPixmap(file_type_icon(name).pixmap(22, 22))
        if mode == "done":
            size = item.get("totalSize") or item.get("downloadedBytes") or 0
            text = T("✓ اكتمل التحميل", "✓ Download complete") + (f"  •  {L(format_bytes(size))}" if size else "")
        elif mode == "error":
            reason = item.get("errorMsg") or T("سبب غير معروف", "Unknown reason")
            # An English reason inside an Arabic line keeps its own direction
            if self.is_ar and not re.search(r"[؀-ۿ]", reason):
                reason = "⁦" + reason + "⁩"  # LRI ... PDI: isolated left-to-right run
            text = T("فشل: ", "Failed: ") + reason
        elif mode == "active":
            parts = [L(f"{pct:.0f}%"), L(format_speed(item.get("speed", 0)))]
            if item.get("timeLeft"):
                parts.append(T("متبقي ", "") + L(format_eta(item.get("timeLeft"))) + T("", " left"))
            text = "  •  ".join(parts)
        else:
            text = item_status_text(item, self.is_ar)
        _set_elided(self.status, text)
        color = {"done": c["success"], "error": c["danger"]}.get(mode, c["muted"])
        self.status.setStyleSheet(f"color: {color};")
        self.bar.set_state(pct, mode)
        self.bar.tick()

        if mode != self.state:
            self.state = mode
            if mode == "done":
                self._set_buttons((T("تشغيل", "Open"), "open"), (T("فتح المجلد", "Show in folder"), "folder"), True)
                self.dismiss_at = time.time() + 6
            elif mode == "error":
                self._set_buttons((T("إعادة المحاولة", "Retry"), "retry"), (T("التفاصيل", "Details"), "details"), True)
                self.dismiss_at = time.time() + 15
            elif mode == "paused":
                self._set_buttons((T("استئناف", "Resume"), "resume"), (T("التفاصيل", "Details"), "details"))
                self.dismiss_at = None
            else:
                self._set_buttons((T("إيقاف مؤقت", "Pause"), "pause"), (T("التفاصيل", "Details"), "details"))
                self.dismiss_at = None

    def _elide_name(self):
        # Shortened to the label's width, which is only known once the card is laid out
        if self.name.width() > 20:
            _set_elided(self.name, self._full_name)
        else:
            self.name.setText(self._full_name)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._elide_name)

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


class DownloadCardManager(QObject):
    """Stacks download cards above the tray (newest at the bottom, at most 3) with slide and fade."""

    MAX = 3

    def __init__(self, window):
        super().__init__(window)
        self.win = window
        self.cards = {}  # download id -> card, in creation order
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
        anim = QPropertyAnimation(card, b"windowOpacity", self)
        anim.setDuration(180)
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
        for i, card in enumerate(reversed(visible)):
            target = QPoint(avail.right() - card.W - 6, avail.bottom() - (i + 1) * (card.H - 6) - 2)
            if card is new:
                card.setWindowOpacity(0.0)
                card.move(target + QPoint(0, 18))
                card.show()
                fade = QPropertyAnimation(card, b"windowOpacity", self)
                fade.setDuration(200)
                fade.setStartValue(0.0)
                fade.setEndValue(1.0)
                self._keep(fade)
            elif not card.isVisible():
                card.setWindowOpacity(1.0)
                card.move(target)
                card.show()
            slide = QPropertyAnimation(card, b"pos", self)
            slide.setDuration(240)
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
        self.theme = self.engine.settings.get("theme", "light")
        self.lang = self.engine.settings.get("lang", "ar")
        self.filter_state = "all"
        self.filter_cat = "ALL"
        self.open_progress_dialogs = {}
        self.cards = DownloadCardManager(self)
        self.taskbar = TaskbarProgress()
        self._seen_status = {}
        self._tray_badge_count = None

        icon_path = os.path.join(RESOURCE_ROOT, "build", "icon.ico")
        self.app_icon = QIcon(icon_path) if os.path.exists(icon_path) else QIcon()
        if not self.app_icon.isNull():
            self.setWindowIcon(self.app_icon)

        avail = QApplication.primaryScreen().availableGeometry()
        self.resize(min(1180, avail.width() - 40), min(720, avail.height() - 40))
        self.setup_ui()
        self.setup_tray()
        self.apply_theme_and_lang()
        self._restore_window_geometry()

        # Clipboard monitoring for direct links
        self.clipboard = QApplication.clipboard()
        self.last_clip = self.clipboard.text().strip()
        self.clipboard.dataChanged.connect(self.on_clipboard_changed)

        # UI refresh timer (250ms)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh_all)
        self.timer.start(250)

        self.engine.signals.completed.connect(self.on_download_completed)
        self.engine.signals.browser_captured.connect(self.on_browser_captured)
        self.engine.signals.focus_requested.connect(self.bring_to_front)
        self.engine.signals.torrent_files_ready.connect(self.on_torrent_files_ready)
        self.engine.signals.lang_changed.connect(self._on_remote_lang_changed)
        self.engine.signals.quit_requested.connect(self.quit_app)
        self.engine.signals.update_available.connect(self._on_update_available)
        apply_shell_integration(self.engine.settings)

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

    def setup_tray(self):
        if not QSystemTrayIcon.isSystemTrayAvailable():
            self.tray_icon = None
            return
        is_ar = self.lang == "ar"
        self.tray_icon = QSystemTrayIcon(self.app_icon, self)
        self.tray_icon.setToolTip(f"Scorpion Download Manager v{APP_VERSION}")
        tray_menu = QMenu(self)
        for text, slot in [
            ("إظهار البرنامج" if is_ar else "Show Scorpion", self.bring_to_front),
            ("إضافة رابط" if is_ar else "Add URL", lambda: self.open_add_dialog("", False)),
            ("ربط المتصفحات" if is_ar else "Browsers", self.open_browser_setup_dialog),
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
        self.tray_icon.activated.connect(
            lambda reason: self.bring_to_front()
            if reason in (QSystemTrayIcon.ActivationReason.Trigger, QSystemTrayIcon.ActivationReason.DoubleClick)
            else None
        )
        self.tray_icon.show()

    def bring_to_front(self):
        self.setWindowFlags(self.windowFlags() | Qt.WindowType.WindowStaysOnTopHint)
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowStaysOnTopHint)
        self.show()

    def setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # 1. Toolbar: one primary action, the rest are calm flat tool buttons
        toolbar = QFrame()
        toolbar.setObjectName("ToolbarFrame")
        # The toolbar never sets the window's minimum width: _apply_layout_mode fits it to the width instead
        toolbar.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)
        toolbar.setMinimumWidth(0)
        self._toolbar_frame = toolbar
        tb = QHBoxLayout(toolbar)
        tb.setContentsMargins(14, 10, 14, 10)
        tb.setSpacing(4)

        self._toolbar_buttons = []

        def tool(name, slot, primary=False):
            b = QPushButton()
            self._toolbar_buttons.append(b)
            b.setObjectName("PrimaryBtn" if primary else "ToolBtn")
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setIconSize(QSize(16, 16))
            b.clicked.connect(slot)
            setattr(self, name, b)
            tb.addWidget(b)
            return b

        tool("btn_add", lambda: self.open_add_dialog("", False), primary=True)
        tb.addSpacing(6)
        tool("btn_video", lambda: self.open_add_dialog("", True))
        tool("btn_torrent", lambda: self.open_add_dialog("", False, True))
        sep = _vsep()
        sep.setFixedHeight(22)
        tb.addWidget(sep)
        tool("btn_resume", self.resume_selected)
        tool("btn_pause", self.pause_selected)
        tool("btn_stop_all", self.engine.pause_all)
        sep2 = _vsep()
        sep2.setFixedHeight(22)
        tb.addWidget(sep2)
        tool("btn_delete", self.delete_selected)
        tool("btn_clear_done", self.engine.delete_completed)
        tb.addSpacing(10)
        self.txt_search = QLineEdit()
        self.txt_search.setClearButtonEnabled(True)
        # Shrinks on small screens instead of forcing a wider window
        self.txt_search.setMinimumWidth(130)
        self.txt_search.setMaximumWidth(240)
        self.txt_search.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.txt_search.textChanged.connect(lambda _t: self.refresh_all())
        tb.addWidget(self.txt_search)
        tb.addStretch()
        tool("btn_browser_setup", self.open_browser_setup_dialog)
        tool("btn_updates", self.open_update_dialog)
        tool("btn_settings", self.open_settings_dialog)
        tool("btn_theme", self.toggle_theme)
        tool("btn_lang", self.toggle_lang)
        root_layout.addWidget(toolbar)

        # 2. Body: sidebar + downloads table
        body = QWidget()
        bl = QHBoxLayout(body)
        bl.setContentsMargins(14, 14, 14, 14)
        bl.setSpacing(14)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(2)
        self.tree.setHeaderHidden(True)
        self.tree.setFixedWidth(230)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(16)
        self.tree.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tree.header().setStretchLastSection(False)
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.tree.header().resizeSection(1, 44)
        self.tree.itemClicked.connect(self.on_tree_clicked)
        bl.addWidget(self.tree)

        self.stack = QStackedWidget()
        self.table = QTableWidget(0, 6)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setShowGrid(False)
        self.table.setWordWrap(False)
        self.table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.table.setIconSize(QSize(20, 20))
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(44)
        hh = self.table.horizontalHeader()
        hh.setHighlightSections(False)
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col, width in ((1, 110), (2, 190), (3, 110), (4, 110), (5, 120)):
            hh.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
            hh.resizeSection(col, width)
        self.table.setItemDelegateForColumn(2, ProgressDelegate(self.table))
        self.table.cellDoubleClicked.connect(self.on_row_double_clicked)
        # The table takes no focus, so leave the search box on click; otherwise Delete/Enter keep going to it
        self.table.cellPressed.connect(lambda _r, _c: self.txt_search.clearFocus())
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.on_table_context_menu)
        self.stack.addWidget(self.table)

        self.empty_label = QLabel()
        self.empty_label.setObjectName("EmptyState")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setWordWrap(True)
        empty_card = QFrame()
        empty_card.setObjectName("CardFrame")
        el = QVBoxLayout(empty_card)
        el.addWidget(self.empty_label)
        self.stack.addWidget(empty_card)
        bl.addWidget(self.stack, 1)
        root_layout.addWidget(body, 1)

        # 3. Status bar
        self.lbl_status_bar = QLabel()
        self.lbl_status_bar.setObjectName("StatusBar")
        root_layout.addWidget(self.lbl_status_bar)
        self.nav_items = {}
        self._setup_shortcuts()

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
        self.app.setStyleSheet(LIGHT_QSS if self.theme == "light" else DARK_QSS)
        c = pal()
        self.setWindowTitle(f"Scorpion Download Manager v{APP_VERSION}")

        labels = [
            (self.btn_add, T("إضافة رابط", "Add URL"), "add", "#ffffff"),
            (self.btn_video, T("تحميل فيديو", "Grab video"), "video", None),
            (self.btn_torrent, T("تحميل تورنت", "Torrent"), "torrent", None),
            (self.btn_resume, T("استئناف", "Resume"), "play", None),
            (self.btn_pause, T("إيقاف مؤقت", "Pause"), "pause", None),
            (self.btn_stop_all, T("إيقاف الكل", "Stop all"), "stop", None),
            (self.btn_delete, T("حذف", "Delete"), "delete", None),
            (self.btn_clear_done, T("حذف المكتمل", "Clear completed"), "clear", None),
            (self.btn_browser_setup, T("ربط المتصفحات", "Browsers"), "browser", None),
            (self.btn_updates, T("التحديثات", "Updates"), "update", None),
            (self.btn_settings, T("الإعدادات", "Settings"), "settings", None),
            (self.btn_theme, T("الوضع الداكن", "Dark") if self.theme == "light" else T("الوضع الفاتح", "Light"),
             "moon" if self.theme == "light" else "sun", None),
            (self.btn_lang, "English" if is_ar else "العربية", "lang", None),
        ]
        for btn, text, icon, color in labels:
            btn.setProperty("fullText", text)
            btn.setText(text)
            btn.setIcon(glyph_icon(ICONS[icon], color or c["text"]))
        self._apply_layout_mode(force=True)
        self.txt_search.setPlaceholderText(T("🔍 بحث في التحميلات (Ctrl+F)", "🔍 Search downloads (Ctrl+F)"))

        self.tree.clear()
        self.nav_items = {}

        def nav(parent, key, text, data):
            it = QTreeWidgetItem(parent, [text, ""])
            it.setData(0, Qt.ItemDataRole.UserRole, data)
            it.setTextAlignment(1, Qt.AlignmentFlag.AlignCenter)
            it.setForeground(1, QColor(c["muted"]))
            self.nav_items[key] = it
            return it

        root_all = nav(self.tree, "all", T("كل التحميلات", "All downloads"), ("all", "ALL"))
        for cat_id, ar, en in [
            ("Video", "فيديو", "Video"),
            ("Music", "صوتيات", "Music"),
            ("Programs", "برامج", "Programs"),
            ("Compressed", "ملفات مضغوطة", "Compressed"),
            ("Documents", "مستندات", "Documents"),
            ("General", "أخرى", "Other"),
        ]:
            nav(root_all, cat_id, T(ar, en), ("all", cat_id))
        root_all.setExpanded(True)
        nav(self.tree, "unfinished", T("غير مكتمل", "Unfinished"), ("unfinished", "ALL"))
        nav(self.tree, "completed", T("مكتمل", "Completed"), ("completed", "ALL"))
        for key, it in self.nav_items.items():
            if it.data(0, Qt.ItemDataRole.UserRole) == (self.filter_state, self.filter_cat):
                self.tree.setCurrentItem(it)

        self.table.setHorizontalHeaderLabels(
            [T("اسم الملف", "File name"), T("الحجم", "Size"), T("التقدم", "Progress"),
             T("السرعة", "Speed"), T("الوقت المتبقي", "Time left"), T("الحالة", "Status")]
        )
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignCenter)
        name_hdr = self.table.horizontalHeaderItem(0)
        if name_hdr:
            name_hdr.setTextAlignment(
                ((Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute) if is_ar else Qt.AlignmentFlag.AlignLeft)
                | Qt.AlignmentFlag.AlignVCenter
            )
        self.empty_label.setText(
            T("لا توجد تحميلات هنا بعد\n\nاضغط «إضافة رابط» أو استخدم زر التحميل في المتصفح",
              "No downloads here yet\n\nClick “Add URL” or use the download button in your browser")
        )
        self._row_ids = []
        self.refresh_all()

    def _restyle_cards(self):
        # Cards are drawn with the current theme and language; reopen them in the new style
        for dl_id in list(self.cards.cards):
            self.cards.cards.pop(dl_id).close()
            self.cards.show_for(dl_id)

    def toggle_theme(self):
        self.theme = "dark" if self.theme == "light" else "light"
        self.engine.settings["theme"] = self.theme
        self.engine.save_state()
        self.apply_theme_and_lang()
        self._restyle_cards()

    def toggle_lang(self):
        self.lang = "en" if self.lang == "ar" else "ar"
        self.engine.settings["lang"] = self.lang
        self.engine.save_state()
        self.apply_theme_and_lang()
        self._restyle_cards()

    def _on_remote_lang_changed(self, new_lang: str):
        if new_lang in ("ar", "en") and self.lang != new_lang:
            self.lang = new_lang
            self.apply_theme_and_lang()

    def on_table_context_menu(self, pos):
        row = self.table.rowAt(pos.y())
        if row < 0:
            return
        self.table.selectRow(row)
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
            add(T("تشغيل الملف", "Open file"), "open", lambda: os.startfile(item["filePath"]))
        add(T("فتح المجلد", "Open folder"), "folder", lambda: self._open_item_folder(item))
        add(T("تفاصيل التحميل", "Download details"), "download", lambda: self.open_progress_window(dl_id))
        if item["status"] != "completed":
            if item["status"] == "downloading":
                add(T("إيقاف مؤقت", "Pause"), "pause", lambda: self.engine.pause_download(dl_id))
            else:
                add(T("استئناف", "Resume"), "play",
                    lambda: (self.engine.start_download(dl_id), self.open_progress_window(dl_id)))
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
        data = item.data(0, Qt.ItemDataRole.UserRole)
        if data:
            self.filter_state, self.filter_cat = data
            self.refresh_all()

    def open_browser_setup_dialog(self):
        dlg = BrowserSetupDialog(self.engine, self.lang, self)
        dlg.exec()

    def open_settings_dialog(self):
        dlg = SettingsDialog(self.engine, self.lang, self)
        dlg.exec()

    def open_update_dialog(self, update_info: dict = None, just_updated: bool = False):
        if not isinstance(update_info, dict):
            update_info = None
        dlg = UpdateDialog(self.engine, self.lang, self, update_info=update_info, just_updated=just_updated)
        dlg.exec()

    def _background_check_updates(self):
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
        dlg = TorrentFilesDialog(item, self.lang, self if self.isVisible() else None)
        dlg.exec()
        # Closing the window without choosing = download everything
        item["torrentSelection"] = dlg.selected_indices()

    def on_browser_captured(self, payload: dict):
        url = (payload.get("url") or "").strip()
        if not url:
            return
        # Like IDM: only the download window pops up, the main window stays where it is

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
                "category": cat,
                "totalSize": int(payload.get("totalSize") or 0),
                "connections": 32,
                "startImmediately": True,
                "isVideo": is_video and quality != "direct",
                "isTorrent": is_torrent,
                "videoQuality": "audio" if is_audio else (
                    quality if quality in ("best", "audio") or re.fullmatch(r"\d{3,4}p", quality or "") else "best"
                ),
            }
            item = self.engine.add_download(opts)
            self.show_download_started(item["id"])
        else:
            self.open_add_dialog(url, is_video and quality != "direct", is_torrent)

    def open_add_dialog(self, initial_url: str = "", is_video: bool = False, is_torrent: bool = False):
        dlg = AddDownloadDialog(self.engine, initial_url, is_video, self.lang, self, is_torrent=is_torrent)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.result_opts:
            item = self.engine.add_download(dlg.result_opts)
            if dlg.result_opts.get("startImmediately"):
                self.show_download_started(item["id"])

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
            ans = QMessageBox.question(
                self,
                "حذف التحميل" if is_ar else "Delete download",
                (f"حذف «{item.get('filename', '')}»؟\nسيتم حذف الأجزاء التي تم تحميلها." if is_ar
                 else f"Delete “{item.get('filename', '')}”?\nThe downloaded parts will be discarded."),
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
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
        exts = (".torrent", ".zip", ".rar", ".7z", ".exe", ".msi", ".iso", ".mp4", ".mkv", ".mp3", ".pdf", ".apk")
        if text.startswith(("http://", "https://")) and text.split("?")[0].lower().endswith(exts):
            is_tor = text.split("?")[0].lower().endswith(".torrent")
            self.open_add_dialog(text, False, is_tor)

    def on_download_completed(self, dl_id: str):
        if not self.engine.downloads.get(dl_id):
            return
        dlg = self.open_progress_dialogs.get(dl_id)
        if dlg is not None and dlg.isVisible():
            # The progress window itself switches to the "complete" state
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
        p.setPen(QColor("#ffffff"))
        f = QFont()
        f.setPixelSize(22)
        f.setBold(True)
        p.setFont(f)
        p.drawText(QRectF(30, 30, 34, 34), Qt.AlignmentFlag.AlignCenter, str(n) if n < 10 else "9+")
        p.end()
        return QIcon(pm)

    def _apply_layout_mode(self, force: bool = False):
        """
        Fits any screen, down to half of a laptop screen: toolbar buttons become icons (their text moves
        to the tooltip), the sidebar narrows and less important columns shrink or hide.
        """
        def set_texts(m):
            # Narrowest layout: tighter gaps and a smaller search box so every button still fits
            self._toolbar_frame.layout().setSpacing(1 if m == "tiny" else 4)
            self.txt_search.setMinimumWidth(80 if m == "tiny" else 130)
            self.txt_search.setMaximumWidth(150 if m == "tiny" else 240)
            for btn in self._toolbar_buttons:
                full = btn.property("fullText") or ""
                keep_text = m == "full" or (btn is self.btn_add and m == "compact")
                btn.setText(full if keep_text else "")
                btn.setToolTip("" if keep_text else full)

        # Width each layout needs, measured for the current language (Arabic labels are longer)
        key = (self.lang, tuple(b.property("fullText") or "" for b in self._toolbar_buttons))
        if force or getattr(self, "_mode_widths_key", None) != key:
            self._mode_widths = {}
            for m in ("full", "compact", "tiny"):
                set_texts(m)
                self._mode_widths[m] = self._toolbar_frame.layout().sizeHint().width()
            self._mode_widths_key = key
            self._layout_mode = None
        w = self.width()
        mode = "full" if self._mode_widths["full"] <= w else ("compact" if self._mode_widths["compact"] <= w else "tiny")
        if mode == getattr(self, "_layout_mode", None):
            return
        self._layout_mode = mode
        set_texts(mode)
        self.tree.setFixedWidth({"full": 230, "compact": 190, "tiny": 150}[mode])
        widths = {
            "full": (110, 190, 110, 110, 120),
            "compact": (95, 150, 95, 90, 105),
            "tiny": (85, 120, 85, 0, 95),
        }[mode]
        hh = self.table.horizontalHeader()
        for col, width in zip((1, 2, 3, 4, 5), widths):
            self.table.setColumnHidden(col, width == 0)
            if width:
                hh.resizeSection(col, width)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "tree"):
            self._apply_layout_mode()

    def _restore_window_geometry(self):
        raw = self.engine.settings.get("windowGeometry") or ""
        if raw:
            try:
                self.restoreGeometry(QByteArray.fromBase64(raw.encode("ascii")))
            except Exception:
                pass
        # Never larger than the screen or off it (e.g. saved on a bigger monitor that is now gone)
        avail = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        w, h = min(self.width(), avail.width()), min(self.height(), avail.height())
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
        self._save_window_geometry()
        # Like IDM: closing the main window keeps Scorpion running in the tray to catch browser downloads
        if getattr(self, "tray_icon", None) is not None and not getattr(self, "_really_quit", False):
            event.ignore()
            self.hide()
            if not getattr(self, "_tray_hint_shown", False):
                self._tray_hint_shown = True
                self.tray_icon.showMessage(
                    "Scorpion IDM",
                    "البرنامج شغال في الخلفية بجوار الساعة ويستقبل التحميلات من المتصفح"
                    if self.lang == "ar"
                    else "Scorpion keeps running in the tray to catch browser downloads",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
            return
        super().closeEvent(event)
        self.app.quit()

    def quit_app(self):
        if self.isVisible():
            self._save_window_geometry()
        self._really_quit = True
        self.engine.pause_all()
        self.app.quit()

    def refresh_all(self):
        is_ar = self.lang == "ar"
        c = pal()
        items = sorted(self.engine.downloads.values(), key=lambda x: x.get("createdAt", 0), reverse=True)
        self._update_status_surfaces(items)

        # sidebar counts
        counts = {k: 0 for k in self.nav_items}
        total_spd = 0
        active_n = 0
        for it in items:
            if it["status"] == "downloading":
                total_spd += it.get("speed", 0) or 0
                active_n += 1
            counts["all"] = counts.get("all", 0) + 1
            cat = it.get("category") or "General"
            if cat in counts:
                counts[cat] += 1
            counts["completed" if it["status"] == "completed" else "unfinished"] = counts.get(
                "completed" if it["status"] == "completed" else "unfinished", 0) + 1
        for key, nav_it in self.nav_items.items():
            n = counts.get(key, 0)
            nav_it.setText(1, str(n) if n else "")

        query = self.txt_search.text().strip().lower()
        filtered = []
        for it in items:
            if self.filter_state == "unfinished" and it["status"] == "completed":
                continue
            if self.filter_state == "completed" and it["status"] != "completed":
                continue
            if self.filter_cat != "ALL" and (it.get("category") or "General") != self.filter_cat:
                continue
            if query and query not in (it.get("filename") or "").lower() and query not in (it.get("url") or "").lower():
                continue
            filtered.append(it)

        self.stack.setCurrentIndex(0 if filtered else 1)
        if not filtered:
            self.empty_label.setText(
                (f"لا توجد نتائج لـ «{query}»" if is_ar else f"No results for “{query}”") if query
                else ("لا توجد تحميلات هنا بعد\n\nاضغط «إضافة رابط» أو استخدم زر التحميل في المتصفح" if is_ar
                      else "No downloads here yet\n\nClick “Add URL” or use the download button in your browser")
            )
        sel_id = self.get_selected_id()
        ids = [it["id"] for it in filtered]
        if ids != getattr(self, "_row_ids", []):
            self.table.setRowCount(len(filtered))
            self._row_ids = ids

        center = Qt.AlignmentFlag.AlignCenter
        for r, it in enumerate(filtered):
            mode = item_mode(it)
            total = it.get("totalSize") or 0
            done = it.get("downloadedBytes") or 0
            downloading = it["status"] == "downloading" and mode == "active"
            cells = [
                it.get("filename", ""),
                L(format_bytes(total)) if total else (L(format_bytes(done)) if done else "—"),
                "",
                L(format_speed(it.get("speed", 0))) if downloading else "—",
                L(format_eta(it.get("timeLeft"))) if downloading else "—",
                item_status_text(it, is_ar),
            ]
            for col, text in enumerate(cells):
                cell = self.table.item(r, col)
                if cell is None:
                    cell = QTableWidgetItem()
                    if col:
                        cell.setTextAlignment(center)
                    else:
                        cell.setTextAlignment(Qt.AlignmentFlag.AlignLeading | Qt.AlignmentFlag.AlignVCenter)
                    self.table.setItem(r, col, cell)
                if cell.text() != text:
                    cell.setText(text)
                if col == 0:
                    if cell.data(ROLE_ID) != it["id"]:
                        cell.setData(ROLE_ID, it["id"])
                        cell.setIcon(file_type_icon(it.get("filename", "")))
                    cell.setToolTip(it.get("filePath", ""))
                elif col == 2:
                    cell.setData(ROLE_PCT, float(it.get("progress") or 0))
                    cell.setData(ROLE_MODE, mode)
                elif col == 5:
                    cell.setForeground(QColor(mode_color(mode) if mode != "connecting" else c["muted"]))
                    tip = ""
                    if it["status"] == "error":
                        reason = (it.get("errorMsg") or "").strip() or ("سبب غير معروف" if is_ar else "Unknown reason")
                        tip = f"{'سبب الفشل' if is_ar else 'Failure reason'}: {reason}"
                    if cell.toolTip() != tip:
                        cell.setToolTip(tip)
            if it["id"] == sel_id and self.table.currentRow() != r:
                self.table.selectRow(r)

        bridge = (("المتصفح متصل" if is_ar else "Browser connected") if self.engine.rpc_alive
                  else ("المتصفح غير متصل" if is_ar else "Browser not connected"))
        sep = "      •      "
        if is_ar:
            parts = [f"السرعة الكلية {L(format_speed(total_spd))}", f"تحميلات نشطة {L(active_n)}",
                     f"الإجمالي {L(len(items))}", bridge]
        else:
            parts = [f"Total speed {format_speed(total_spd)}", f"Active {active_n}", f"Total {len(items)}", bridge]
        self.lbl_status_bar.setText(sep.join(parts))


if __name__ == "__main__":
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
            if open_target:
                requests.post(
                    "http://127.0.0.1:19615/capture",
                    json=_target_payload(open_target),
                    headers={BRIDGE_CLIENT_HEADER: "1"},
                    timeout=2,
                )
            elif not start_in_tray:
                requests.get("http://127.0.0.1:19615/focus", headers={BRIDGE_CLIENT_HEADER: "1"}, timeout=0.6)
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
