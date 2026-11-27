# -*- coding: utf-8 -*-
"""
Scorpion Download Manager — Visual Design System, Golden-Scorpion Brand Loader,
Vector Outline Icon Set & Rich Card Thumbnail Renderer.
"""
import ctypes
import os
import time

from PyQt6.QtCore import Qt, QByteArray, QRectF
from PyQt6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap
from PyQt6.QtSvg import QSvgRenderer


_MODULE_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_MODULE_DIR)

# Design tokens shared across desktop surfaces
TOKENS = {
    "radius_sm": 6,
    "radius_md": 8,
    "radius_lg": 11,
    "radius_card": 11,
    "sidebar_w_full": 228,
    "sidebar_w_standard": 212,
    "sidebar_w_compact": 188,
    "sidebar_w_tiny": 168,
    "titlebar_h": 38,
    "menubar_h": 28,
    "control_h": 34,
    "card_h": 78,
    "card_gap": 8,
    "card_torrent_expanded_h": 238,
}

PALETTES = {
    "dark": {
        "bg": "#0D0D11",
        "sidebar_bg": "#101016",
        "surface": "#16161D",
        "surface2": "#1E1E28",
        "surface3": "#121218",
        "card_active_bg": "#19171B",
        "border": "#262633",
        "border_subtle": "#1D1D27",
        "border_amber": "#7A4B16",
        "text": "#F2F3F7",
        "text_sec": "#C2C6D2",
        "muted": "#8A8E9E",
        "disabled": "#565A6A",
        "accent": "#FF9500",
        "accent_intense": "#FF5A00",
        "accent_hover": "#FFA726",
        "primary_bg": "#FF9500",
        "primary_hover": "#FFA624",
        "primary_text": "#120C04",
        "accent_soft": "#281D10",
        "danger": "#FF453A",
        "success": "#30D158",
        "warn": "#FF9F0A",
        "track": "#282834",
        "btn_bg": "#1A1A23",
        "btn_hover": "#232330",
        "btn_pressed": "#2A2A38",
        "menu_bg": "#15151C",
        "card_shadow": "#07070A",
    },
    "light": {
        "bg": "#F4F5F8",
        "sidebar_bg": "#ECEEF3",
        "surface": "#FFFFFF",
        "surface2": "#EDEEF4",
        "surface3": "#F8F9FC",
        "card_active_bg": "#FFFDF9",
        "border": "#D7DCE6",
        "border_subtle": "#E5E8F0",
        "border_amber": "#D97706",
        "text": "#151821",
        "text_sec": "#3F4554",
        "muted": "#5E6475",
        "disabled": "#9CA3B2",
        "accent": "#E67E00",
        "accent_intense": "#EA580C",
        "accent_hover": "#CC6D00",
        "primary_bg": "#FF9500",
        "primary_hover": "#E68600",
        "primary_text": "#140D04",
        "accent_soft": "#FFF3DE",
        "danger": "#DC2626",
        "success": "#16A34A",
        "warn": "#D97706",
        "track": "#E0E4EE",
        "btn_bg": "#F7F8FA",
        "btn_hover": "#ECEEF4",
        "btn_pressed": "#E0E4EE",
        "menu_bg": "#FFFFFF",
        "card_shadow": "#CBD0DC",
    },
}


def build_qss(p: dict) -> str:
    """Coordinated QSS stylesheet; preserves focus selectors required across desktop accessibility tests."""
    chk_path = ""
    for base in (_REPO_ROOT, os.path.dirname(_MODULE_DIR)):
        cand = os.path.join(base, "build", "icons", "check-mark.svg")
        if os.path.exists(cand):
            chk_path = cand.replace(os.sep, "/")
            break
    chk_rule = f'\n    image: url("{chk_path}");' if chk_path else ""
    return f"""
* {{
    font-family: "Segoe UI", "Tahoma", sans-serif;
    font-size: 13px;
    color: {p['text']};
}}
QMainWindow, QDialog {{
    background: {p['bg']};
}}
QWidget#MainShell {{
    background: {p['bg']};
}}
QFrame#TitleBarFrame {{
    background: {p['bg']};
    border: none;
}}
QPushButton#WinCtrlBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0px;
}}
QPushButton#WinCtrlBtn:hover {{
    background: {p['surface2']};
}}
QPushButton#WinCtrlBtn:pressed {{
    background: {p['track']};
}}
QPushButton#WinCloseBtn {{
    background: transparent;
    border: none;
    border-radius: 6px;
    padding: 0px;
}}
QPushButton#WinCloseBtn:hover {{
    background: #E81123;
}}
QPushButton#WinCloseBtn:pressed {{
    background: #C40E1D;
}}
QFrame#MenuRowBar {{
    background: {p['bg']};
    border: none;
    border-bottom: 1px solid {p['border_subtle']};
}}
QMenuBar#TopMenuBar {{
    background: transparent;
    border: none;
    spacing: 2px;
    padding: 1px 6px;
}}
QMenuBar#TopMenuBar::item {{
    background: transparent;
    color: {p['text_sec']};
    padding: 4px 10px;
    border-radius: 5px;
    font-size: 12.5px;
    font-weight: 500;
}}
QMenuBar#TopMenuBar::item:selected,
QMenuBar#TopMenuBar::item:pressed {{
    background: {p['surface2']};
    color: {p['text']};
}}
QFrame#SidebarPanel {{
    background: {p['sidebar_bg']};
    border: none;
    border-right: 1px solid {p['border_subtle']};
}}
QFrame#SidebarPanel[rtl="true"] {{
    border-right: none;
    border-left: 1px solid {p['border_subtle']};
}}
QLabel#CategoriesHdr {{
    color: {p['text']};
    font-size: 13.5px;
    font-weight: 600;
    padding: 2px 4px;
}}
QPushButton#ExtStatusPill {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 6px 8px;
    font-size: 12.5px;
    font-weight: 500;
    text-align: left;
}}
QPushButton#ExtStatusPill:hover {{
    background: {p['surface2']};
    border-color: {p['border']};
}}
QFrame#ToolbarFrame {{
    background: transparent;
    border: none;
}}
QFrame#CardFrame {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 10px;
}}
QFrame#VSep {{
    background: {p['border']};
    min-width: 1px;
    max-width: 1px;
    border: none;
}}
QLabel {{
    background: transparent;
}}
QLabel#Muted {{
    color: {p['muted']};
}}
QLabel#Caption {{
    color: {p['muted']};
    font-size: 12px;
}}
QLabel#Value {{
    font-size: 19px;
    font-weight: 600;
}}
QLabel#Title {{
    font-size: 15.5px;
    font-weight: 600;
}}
QLabel#Url {{
    color: {p['muted']};
    font-size: 12px;
}}
QLabel#EmptyState {{
    color: {p['muted']};
    font-size: 14px;
}}
QFrame#StatusStripFrame {{
    background: {p['sidebar_bg']};
    border: none;
    border-top: 1px solid {p['border_subtle']};
}}
QLabel#StatusBar {{
    color: {p['text_sec']};
    background: transparent;
    border: none;
    padding: 7px 16px;
    font-size: 12px;
    font-weight: 500;
}}
QPushButton {{
    background: {p['btn_bg']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 14px;
    font-weight: 600;
    color: {p['text']};
}}
QPushButton:hover {{
    background: {p['btn_hover']};
    border-color: {p['muted']};
}}
QPushButton:pressed {{
    background: {p['btn_pressed']};
}}
QPushButton:disabled {{
    color: {p['disabled']};
    background: {p['surface3']};
    border-color: {p['border_subtle']};
}}
QPushButton#PrimaryBtn, QPushButton#SuccessBtn {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['primary_bg']}, stop:1 {p['accent_intense']});
    border: 1px solid {p['primary_bg']};
    border-radius: 8px;
    color: {p['primary_text']};
    font-weight: 700;
    padding: 7px 16px;
}}
QPushButton#PrimaryBtn:hover, QPushButton#SuccessBtn:hover {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['primary_hover']}, stop:1 {p['accent']});
    border-color: {p['primary_hover']};
}}
QPushButton#PrimaryBtn:pressed, QPushButton#SuccessBtn:pressed {{
    background: {p['accent_intense']};
    border-color: {p['accent_intense']};
}}
QPushButton#PrimaryBtn:disabled, QPushButton#SuccessBtn:disabled {{
    background: {p['surface2']};
    border-color: {p['border']};
    color: {p['disabled']};
}}
QPushButton#ToolbarSecondaryBtn {{
    background: {p['btn_bg']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 7px 13px;
    font-weight: 600;
    color: {p['text_sec']};
}}
QPushButton#ToolbarSecondaryBtn:hover {{
    background: {p['btn_hover']};
    border-color: {p['muted']};
    color: {p['text']};
}}
QPushButton#ToolbarSecondaryBtn:pressed {{
    background: {p['btn_pressed']};
}}
QPushButton#ToolbarSecondaryBtn:disabled {{
    background: {p['surface3']};
    border-color: {p['border_subtle']};
    color: {p['disabled']};
}}
QPushButton#DangerBtn {{
    color: {p['danger']};
    border-color: {p['border']};
}}
QPushButton#DangerBtn:hover {{
    background: rgba(255, 69, 58, 0.14);
    border-color: {p['danger']};
}}
QPushButton#ToolBtn {{
    background: transparent;
    border: 1px solid transparent;
    border-radius: 7px;
    padding: 6px 10px;
}}
QPushButton#ToolBtn:hover {{
    background: {p['surface2']};
    border-color: {p['border']};
}}
QPushButton#ToolBtn:disabled {{
    background: transparent;
    color: {p['disabled']};
}}
QPushButton:focus {{
    border: 1.5px solid {p['accent']};
}}
QPushButton#ToolBtn:focus, QPushButton#ToolbarSecondaryBtn:focus {{
    border: 1.5px solid {p['accent']};
    background: {p['surface2']};
}}
QLineEdit, QComboBox, QSpinBox, QTimeEdit {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {p['accent']};
    selection-color: {p['primary_text']};
}}
QLineEdit#SidebarSearch {{
    background: {p['surface']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    padding: 6px 10px;
    font-size: 13px;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QTimeEdit:focus, QLineEdit#SidebarSearch:focus {{
    border: 1.5px solid {p['accent']};
}}
QSpinBox::up-button, QSpinBox::down-button, QTimeEdit::up-button, QTimeEdit::down-button {{
    width: 16px;
    border: none;
    background: transparent;
}}
QComboBox QAbstractItemView {{
    background: {p['menu_bg']};
    border: 1px solid {p['border']};
    selection-background-color: {p['accent_soft']};
    selection-color: {p['accent']};
    padding: 4px;
}}
QTreeWidget {{
    background: transparent;
    border: none;
    outline: 0;
}}
QTreeWidget#SidebarTree {{
    background: transparent;
    border: none;
    outline: 0;
}}
QTreeWidget#SidebarTree:focus {{
    outline: none;
}}
QTreeWidget#TorrentSubTree, QTreeWidget#DialogTree {{
    background: {p['surface3']};
    border: 1px solid {p['border']};
    border-radius: 8px;
    outline: 0;
}}
QTreeWidget#TorrentSubTree:focus, QTreeWidget#DialogTree:focus {{
    border: 1.5px solid {p['accent']};
}}
QTreeWidget::item {{
    padding: 5px 6px;
    border: none;
}}
QTableWidget {{
    background: {p['bg']};
    border: 1px solid {p['border']};
    border-radius: 10px;
    outline: 0;
    gridline-color: transparent;
    alternate-background-color: {p['bg']};
}}
QTableWidget#DownloadCardList {{
    background: transparent;
    border: none;
    outline: 0;
    gridline-color: transparent;
}}
QTableWidget:focus {{
    border: 1.5px solid {p['accent']};
}}
QTableWidget#DownloadCardList:focus {{
    border: 1px solid {p['border_subtle']};
    border-radius: 10px;
}}
QTableWidget::item {{
    padding: 0px;
    border: none;
    background: transparent;
}}
QTableWidget::item:selected {{
    background: transparent;
    color: {p['text']};
}}
QHeaderView {{
    background: transparent;
    border: none;
}}
QHeaderView::section {{
    background: transparent;
    color: {p['muted']};
    font-size: 12px;
    font-weight: 600;
    padding: 8px 8px;
    border: none;
    border-bottom: 1px solid {p['border']};
}}
QTableCornerButton::section {{
    background: transparent;
    border: none;
}}
QTabWidget::pane {{
    border: 1px solid {p['border']};
    border-radius: 10px;
    background: {p['surface']};
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    color: {p['muted']};
    padding: 9px 18px;
    border: none;
    border-bottom: 2px solid transparent;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    color: {p['accent']};
    border-bottom: 2px solid {p['accent']};
}}
QTabBar::tab:hover {{
    color: {p['text']};
}}
QCheckBox {{
    spacing: 8px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1.5px solid {p['muted']};
    background: {p['surface3']};
}}
QCheckBox::indicator:hover {{
    border-color: {p['accent']};
}}
QCheckBox::indicator:checked {{
    background: {p['accent']};
    border-color: {p['accent']};{chk_rule}
}}
QMenu {{
    background: {p['menu_bg']};
    border: 1px solid {p['border']};
    border-radius: 9px;
    padding: 6px;
}}
QMenu::item {{
    padding: 7px 22px;
    border-radius: 6px;
    color: {p['text']};
}}
QMenu::item:selected {{
    background: {p['accent_soft']};
    color: {p['accent']};
}}
QMenu::separator {{
    height: 1px;
    background: {p['border']};
    margin: 5px 8px;
}}
QToolTip {{
    background: {p['surface2']};
    color: {p['text']};
    border: 1px solid {p['border']};
    border-radius: 6px;
    padding: 5px 8px;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {p['track']};
    border-radius: 4px;
    min-height: 28px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p['muted']};
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 8px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {p['track']};
    border-radius: 4px;
    min-width: 28px;
}}
QScrollBar::add-line, QScrollBar::sub-line, QScrollBar::add-page, QScrollBar::sub-page {{
    background: none;
    height: 0px;
    width: 0px;
}}
QProgressBar {{
    background: {p['track']};
    border: none;
    border-radius: 4px;
    text-align: center;
    font-weight: 600;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {p['accent']}, stop:1 {p['accent_intense']});
    border-radius: 4px;
}}
QSplitter::handle {{
    background: transparent;
}}
"""


_REDUCED_MOTION_CACHE = (0.0, False)


def prefers_reduced_motion() -> bool:
    """Respects Windows 'Animation effects' accessibility preference."""
    global _REDUCED_MOTION_CACHE
    now = time.monotonic()
    if now - _REDUCED_MOTION_CACHE[0] < 5.0:
        return _REDUCED_MOTION_CACHE[1]
    val = False
    if os.name == "nt":
        try:
            enabled = ctypes.c_int(1)
            if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(enabled), 0):
                val = not bool(enabled.value)
        except Exception:
            val = False
    _REDUCED_MOTION_CACHE = (now, val)
    return val


def resolve_build_file(rel: str) -> str:
    for base in (_REPO_ROOT, os.path.dirname(_MODULE_DIR)):
        cand = os.path.join(base, "build", rel)
        if os.path.exists(cand):
            return cand
    return ""


_FALLBACK_SCORPION_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" fill="none">
<g stroke="#3D1800" stroke-width="4" stroke-linejoin="round" stroke-linecap="round" fill="#FF9500">
<path d="M142 146 L166 161 L169 196 L157 187 L156 167 L136 152 Z"/>
<path d="M154 135 L183 148 L194 184 L182 177 L173 155 L147 142 Z"/>
<path d="M164 122 L198 132 L214 164 L201 159 L187 140 L158 129 Z"/>
<path d="M170 107 L206 113 L224 142 L210 139 L195 122 L166 115 Z"/>
<path d="M100 128 C78 115 56 118 40 135 C27 151 27 177 36 198 C42 182 44 170 50 162 C51 175 54 187 60 196 C64 180 64 164 69 154 C74 142 86 138 100 138 Z"/>
<path d="M124 154 C138 170 134 191 116 207 C99 221 70 227 46 221 C64 214 78 205 86 196 C70 202 54 204 42 200 C61 191 80 179 94 168 C104 160 116 154 124 154 Z"/>
<path d="M84 152 C77 141 85 125 104 116 C126 102 150 85 166 67 C174 56 173 42 164 35 C156 30 148 33 144 41 C141 50 144 62 132 76 C131 64 123 51 124 36 C126 19 144 13 166 19 C189 26 202 47 197 71 C192 94 173 114 152 132 C137 146 119 164 97 160 Z"/>
</g></svg>"""

_EMBLEM_CACHE: dict[tuple[int, bool], QPixmap] = {}


def scorpion_emblem_pixmap(size: int = 24, small: bool = False) -> QPixmap:
    """Returns transparent HiDPI Golden-Scorpion pixmap rendered cleanly from vector SVG."""
    key = (int(size), bool(small))
    if key in _EMBLEM_CACHE:
        return _EMBLEM_CACHE[key]
    svg_name = "scorpion_tray.svg" if (small or size <= 24) else "scorpion_logo.svg"
    svg_path = resolve_build_file(svg_name) or resolve_build_file("scorpion_logo.svg")
    renderer = QSvgRenderer(svg_path) if svg_path else QSvgRenderer(QByteArray(_FALLBACK_SCORPION_SVG.encode("utf-8")))
    if not renderer.isValid():
        renderer = QSvgRenderer(QByteArray(_FALLBACK_SCORPION_SVG.encode("utf-8")))
    dpr = 2
    px = size * dpr
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    renderer.render(p, QRectF(0, 0, px, px))
    p.end()
    pm.setDevicePixelRatio(float(dpr))
    _EMBLEM_CACHE[key] = pm
    return pm


def scorpion_emblem_icon() -> QIcon:
    """Multi-size QIcon populated from the Golden Scorpion vector."""
    ico = QIcon()
    for sz in (16, 20, 24, 32, 48, 64, 128, 256):
        ico.addPixmap(scorpion_emblem_pixmap(sz, small=(sz <= 24)))
    return ico


# Consistent 24x24 outline stroke SVG icon paths (unified 1.8px stroke, round joins/caps)
_OUTLINE_PATHS = {
    "search": (
        '<circle cx="11" cy="11" r="6.5"/>'
        '<path d="M16 16 L20.5 20.5"/>'
    ),
    "all_downloads": (
        '<rect x="3.5" y="4" width="17" height="16" rx="2.5"/>'
        '<path d="M12 8 V15.5 M9 12.8 L12 15.8 L15 12.8"/>'
    ),
    "video": (
        '<rect x="3" y="4.5" width="18" height="15" rx="2.2"/>'
        '<path d="M7.5 4.5 V19.5 M16.5 4.5 V19.5 M3 9.5 H7.5 M3 14.5 H7.5 M16.5 9.5 H21 M16.5 14.5 H21"/>'
        '<polygon points="10.5,9.5 15,12 10.5,14.5" stroke-linejoin="round"/>'
    ),
    "music": (
        '<path d="M9 17.5 V6.5 L19 5 V16"/>'
        '<circle cx="6.8" cy="17.5" r="2.3"/>'
        '<circle cx="16.8" cy="16" r="2.3"/>'
    ),
    "programs": (
        '<rect x="3.8" y="3.8" width="7" height="7" rx="1.6"/>'
        '<rect x="13.2" y="3.8" width="7" height="7" rx="1.6"/>'
        '<rect x="3.8" y="13.2" width="7" height="7" rx="1.6"/>'
        '<rect x="13.2" y="13.2" width="7" height="7" rx="1.6" transform="rotate(15 16.7 16.7)"/>'
    ),
    "compressed": (
        '<path d="M3.5 7 C3.5 5.8 4.4 5 5.6 5 H10 L12 7 H18.4 C19.6 7 20.5 7.8 20.5 9 V17.5 C20.5 18.7 19.6 19.5 18.4 19.5 H5.6 C4.4 19.5 3.5 18.7 3.5 17.5 Z"/>'
        '<path d="M11 10.5 V16 M9.5 12 H12.5 M9.5 14.5 H12.5"/>'
    ),
    "documents": (
        '<path d="M6.5 3.5 H14 L18.5 8 V20.5 H6.5 Z"/>'
        '<path d="M14 3.5 V8 H18.5 M9.5 12 H15.5 M9.5 15.5 H15.5 M9.5 18.2 H13"/>'
    ),
    "torrents": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<ellipse cx="12" cy="12" rx="3.6" ry="8.5"/>'
        '<path d="M4 9.5 H20 M4 14.5 H20"/>'
    ),
    "queues": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 7.5 V12.5 L15.5 14.5"/>'
    ),
    "pulse": (
        '<path d="M3 12 H6.8 L9.2 6.5 L13 17.5 L15.8 10 L17.6 12 H21"/>'
    ),
    "add": (
        '<path d="M12 5 V19 M5 12 H19"/>'
    ),
    "play": (
        '<polygon points="7.5,5.5 18.5,12 7.5,18.5" stroke-linejoin="round"/>'
    ),
    "pause": (
        '<rect x="7" y="5.5" width="3.3" height="13" rx="0.9"/>'
        '<rect x="13.7" y="5.5" width="3.3" height="13" rx="0.9"/>'
    ),
    "stop": (
        '<rect x="6" y="6" width="12" height="12" rx="2"/>'
    ),
    "calendar": (
        '<rect x="4" y="5.5" width="16" height="14.5" rx="2.2"/>'
        '<path d="M8 3.5 V7 M16 3.5 V7 M4 10 H20 M9 14 H10.5 M13.5 14 H15"/>'
    ),
    "settings": (
        '<circle cx="12" cy="12" r="3.2"/>'
        '<path d="M12 3.5 V5.5 M12 18.5 V20.5 M3.5 12 H5.5 M18.5 12 H20.5 M6 6 L7.5 7.5 M16.5 16.5 L18 18 M18 6 L16.5 7.5 M7.5 16.5 L6 18"/>'
    ),
    "resume_cw": (
        '<path d="M18.5 9.5 A7 7 0 1 0 19 14"/>'
        '<polyline points="19,5 19,9.5 14.5,9.5"/>'
    ),
    "open_file": (
        '<path d="M14 4 H19.5 V9.5 M19.5 4 L11 12.5"/>'
        '<path d="M18 13.5 V18.5 C18 19.3 17.3 20 16.5 20 H5.5 C4.7 20 4 19.3 4 18.5 V7.5 C4 6.7 4.7 6 5.5 6 H10.5"/>'
    ),
    "folder": (
        '<path d="M3.5 7 C3.5 5.9 4.4 5 5.5 5 H9.8 L11.8 7 H18.5 C19.6 7 20.5 7.9 20.5 9 V17.5 C20.5 18.6 19.6 19.5 18.5 19.5 H5.5 C4.4 19.5 3.5 18.6 3.5 17.5 Z"/>'
    ),
    "delete": (
        '<path d="M4.5 7 H19.5 M9 7 V4.5 H15 V7 M6.8 7 L7.6 19.5 H16.4 L17.2 7 M10 10.5 V16.5 M14 10.5 V16.5"/>'
    ),
    "clear": (
        '<path d="M4 7 H18 M4 12 H15 M4 17 H12 M16 14 L20.5 18.5 M20.5 14 L16 18.5"/>'
    ),
    "browser": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M3.5 12 H20.5 M12 3.5 C14.8 6.5 14.8 17.5 12 20.5 C9.2 17.5 9.2 6.5 12 3.5 Z"/>'
    ),
    "update": (
        '<path d="M19 10 A7.2 7.2 0 0 0 6.2 7.4 M5 14 A7.2 7.2 0 0 0 17.8 16.6"/>'
        '<polyline points="19,5.5 19,10 14.5,10"/>'
        '<polyline points="5,18.5 5,14 9.5,14"/>'
    ),
    "moon": (
        '<path d="M19.5 14.5 A7.5 7.5 0 0 1 9.5 4.5 A7.5 7.5 0 1 0 19.5 14.5 Z"/>'
    ),
    "sun": (
        '<circle cx="12" cy="12" r="4"/>'
        '<path d="M12 3 V5 M12 19 V21 M3 12 H5 M19 12 H21 M5.6 5.6 L7 7 M17 17 L18.4 18.4 M18.4 5.6 L17 7 M7 17 L5.6 18.4"/>'
    ),
    "lang": (
        '<path d="M4 7 H13 M8.5 4.5 V7 C8.5 11.5 6.5 14 4 16 M6 10.5 C7.3 12.8 9 14.5 11.5 16"/>'
        '<path d="M13 19 L16.5 10.5 L20 19 M14.2 16.5 H18.8"/>'
    ),
    "probe": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 8 V12.5 M12 15.8 V16.2"/>'
    ),
    "clock": (
        '<circle cx="12" cy="12" r="8.5"/>'
        '<path d="M12 7.5 V12.5 L15.2 14.2"/>'
    ),
    "peers": (
        '<circle cx="9" cy="8" r="2.8"/>'
        '<path d="M4 18 C4 14.8 6.2 13 9 13 C11.8 13 14 14.8 14 18"/>'
        '<circle cx="16.2" cy="8.8" r="2.2"/>'
        '<path d="M15.5 13.5 C17.8 13.7 19.5 15.2 19.5 18"/>'
    ),
    "chevron_down": '<polyline points="6.5,9.5 12,15 17.5,9.5"/>',
    "chevron_up": '<polyline points="6.5,14.5 12,9 17.5,14.5"/>',
    "minimize": '<path d="M6 12 H18"/>',
    "maximize": '<rect x="6" y="6" width="12" height="12" rx="1.4"/>',
    "restore": '<rect x="7.5" y="5" width="11" height="11" rx="1.2"/><path d="M5 8.5 V18.5 H15"/>',
    "close": '<path d="M6.5 6.5 L17.5 17.5 M17.5 6.5 L6.5 17.5"/>',
    "download": '<path d="M12 4.5 V15 M8 11.5 L12 15.5 L16 11.5 M4.5 18.5 H19.5"/>',
    "check": '<polyline points="5.5,12.5 10,17 18.8,7.5"/>',
    "warning": '<path d="M12 4 L20.5 19 H3.5 Z M12 10 V13.5 M12 16.5 V16.8"/>',
}

_ICON_CACHE: dict[tuple[str, str, int, int], QPixmap] = {}


def outline_pixmap(name: str, color: str = "#F2F3F7", size: int = 16, stroke_w: float = 1.9) -> QPixmap:
    """Renders a crisp stroke-based SVG outline icon cached at HiDPI 2x."""
    qc = QColor(color)
    col = qc.name(QColor.NameFormat.HexRgb)
    alpha = max(0.0, min(1.0, float(qc.alphaF())))
    sw_key = int(round(stroke_w * 10))
    key = (name, f"{col}@{alpha:.2f}", int(size), sw_key)
    if key in _ICON_CACHE:
        return _ICON_CACHE[key]
    body = _OUTLINE_PATHS.get(name) or _OUTLINE_PATHS["all_downloads"]
    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" '
        f'stroke="{col}" stroke-opacity="{alpha:.3f}" stroke-width="{stroke_w:.2f}" '
        f'stroke-linecap="round" stroke-linejoin="round">'
        f"{body}</svg>"
    )
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    dpr = 2
    px = max(16, int(size) * dpr)
    pm = QPixmap(px, px)
    pm.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pm)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    renderer.render(painter, QRectF(0, 0, px, px))
    painter.end()
    pm.setDevicePixelRatio(float(dpr))
    _ICON_CACHE[key] = pm
    return pm


def outline_icon(name: str, color: str = "#F2F3F7", size: int = 16, stroke_w: float = 1.9) -> QIcon:
    return QIcon(outline_pixmap(name, color, size, stroke_w))


def draw_card_file_badge(
    painter: QPainter,
    rect: QRectF,
    filename: str,
    category: str = "General",
    is_torrent: bool = False,
    p: dict | None = None,
) -> None:
    """Draws refined file-type thumbnails for stacked download cards without distorted labels."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    ext = os.path.splitext(filename or "")[1].lstrip(".").upper()
    ext_tag = (ext[:4] if ext else ("TOR" if is_torrent else "FILE"))
    x, y, w, h = rect.x(), rect.y(), rect.width(), rect.height()

    is_video = category == "Video" or ext in ("MP4", "MKV", "WEBM", "MOV", "AVI", "FLV", "TS", "M4V")
    is_music = category == "Music" or ext in ("MP3", "M4A", "FLAC", "WAV", "OGG", "OPUS", "AAC")
    is_iso = ext in ("ISO", "IMG", "DMG", "TORRENT") or (is_torrent and not is_video and not is_music)
    is_zip = category == "Compressed" or ext in ("ZIP", "RAR", "7Z", "TAR", "GZ", "TGZ", "XZ")
    is_doc = category == "Documents" or ext in ("PDF", "DOC", "DOCX", "XLS", "XLSX", "PPT", "PPTX", "TXT", "EPUB")

    if is_video:
        # Film slate thumbnail with amber play glyph and crisp format badge
        bg_rect = QRectF(x + 2, y + 4, w - 4, h - 8)
        bp = QPainterPath()
        bp.addRoundedRect(bg_rect, 6, 6)
        painter.fillPath(bp, QColor("#20222C"))
        painter.setPen(QPen(QColor("#3E4252"), 1.0))
        painter.drawPath(bp)
        # Side filmstrip sprockets
        painter.fillRect(QRectF(x + 5, y + 8, 3.2, 4), QColor("#4A4F62"))
        painter.fillRect(QRectF(x + 5, y + 16, 3.2, 4), QColor("#4A4F62"))
        painter.fillRect(QRectF(x + 5, y + 24, 3.2, 4), QColor("#4A4F62"))
        painter.fillRect(QRectF(x + w - 8.2, y + 8, 3.2, 4), QColor("#4A4F62"))
        painter.fillRect(QRectF(x + w - 8.2, y + 16, 3.2, 4), QColor("#4A4F62"))
        painter.fillRect(QRectF(x + w - 8.2, y + 24, 3.2, 4), QColor("#4A4F62"))
        # Play triangle
        cx, cy = bg_rect.center().x(), bg_rect.center().y() - 3
        tri = QPainterPath()
        tri.moveTo(cx - 5, cy - 6.5)
        tri.lineTo(cx + 7.5, cy)
        tri.lineTo(cx - 5, cy + 6.5)
        tri.closeSubpath()
        painter.fillPath(tri, QColor("#F2F3F7"))
        # Corner real format pill (e.g. MP4 / MKV)
        tag_r = QRectF(x + w - 23, y + h - 15, 22, 13)
        tp = QPainterPath()
        tp.addRoundedRect(tag_r, 3.5, 3.5)
        painter.fillPath(tp, QColor("#FF9500"))
        f = QFont("Segoe UI", 1, QFont.Weight.Bold)
        f.setPixelSize(8)
        painter.setFont(f)
        painter.setPen(QColor("#140D04"))
        painter.drawText(tag_r, Qt.AlignmentFlag.AlignCenter, ext_tag if ext else "MP4")

    elif is_iso:
        # Clean light document sheet with optical disc emblem (matches Ubuntu ISO card)
        sheet = QPainterPath()
        r0 = QRectF(x + 6, y + 2, w - 12, h - 4)
        sheet.moveTo(r0.left(), r0.top() + 4)
        sheet.quadTo(r0.left(), r0.top(), r0.left() + 4, r0.top())
        sheet.lineTo(r0.right() - 9, r0.top())
        sheet.lineTo(r0.right(), r0.top() + 9)
        sheet.lineTo(r0.right(), r0.bottom() - 4)
        sheet.quadTo(r0.right(), r0.bottom(), r0.right() - 4, r0.bottom())
        sheet.lineTo(r0.left() + 4, r0.bottom())
        sheet.quadTo(r0.left(), r0.bottom(), r0.left(), r0.bottom() - 4)
        sheet.closeSubpath()
        painter.fillPath(sheet, QColor("#ECEEF3"))
        painter.setPen(QPen(QColor("#BFC5D2"), 1.0))
        painter.drawPath(sheet)
        # Folded corner
        fold = QPainterPath()
        fold.moveTo(r0.right() - 9, r0.top())
        fold.lineTo(r0.right() - 9, r0.top() + 9)
        fold.lineTo(r0.right(), r0.top() + 9)
        fold.closeSubpath()
        painter.fillPath(fold, QColor("#CBD0DC"))
        # Disc / Ubuntu-inspired ring glyph
        c_pt = QRectF(r0.left() + 5, r0.center().y() - 7, w - 22, w - 22)
        painter.setPen(QPen(QColor("#3E4352"), 3.0))
        painter.drawEllipse(c_pt)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FF9500"))
        for dx, dy in ((-8, 0), (6, -6), (6, 6)):
            painter.drawEllipse(QRectF(c_pt.center().x() + dx - 1.5, c_pt.center().y() + dy - 1.5, 3.2, 3.2))

    elif is_zip:
        # Warm golden-amber layered archive folder (matches Game_Update_Patch.zip card)
        back = QPainterPath()
        back.addRoundedRect(QRectF(x + 4, y + 6, w - 8, h - 11), 5, 5)
        painter.fillPath(back, QColor("#CC7000"))
        tab = QPainterPath()
        tab.addRoundedRect(QRectF(x + 4, y + 4, 18, 9), 3, 3)
        painter.fillPath(tab, QColor("#E08205"))
        front = QPainterPath()
        front.addRoundedRect(QRectF(x + 4, y + 11, w - 8, h - 16), 5, 5)
        grad = QLinearGradient(x, y + 11, x, y + h - 5)
        grad.setColorAt(0.0, QColor("#FFB93E"))
        grad.setColorAt(1.0, QColor("#EB8408"))
        painter.fillPath(front, grad)
        # Paper slip inside
        painter.fillRect(QRectF(x + 12, y + 7, w - 24, 5), QColor("#F5F6FA"))

    elif is_doc:
        # Crisp white page with folded corner + red PDF/color badge + text lines
        r0 = QRectF(x + 6, y + 2, w - 12, h - 4)
        sheet = QPainterPath()
        sheet.moveTo(r0.left(), r0.top() + 3.5)
        sheet.quadTo(r0.left(), r0.top(), r0.left() + 3.5, r0.top())
        sheet.lineTo(r0.right() - 8, r0.top())
        sheet.lineTo(r0.right(), r0.top() + 8)
        sheet.lineTo(r0.right(), r0.bottom() - 3.5)
        sheet.quadTo(r0.right(), r0.bottom(), r0.right() - 3.5, r0.bottom())
        sheet.lineTo(r0.left() + 3.5, r0.bottom())
        sheet.quadTo(r0.left(), r0.bottom(), r0.left(), r0.bottom() - 3.5)
        sheet.closeSubpath()
        painter.fillPath(sheet, QColor("#F6F7FA"))
        painter.setPen(QPen(QColor("#C6CCD8"), 1.0))
        painter.drawPath(sheet)
        badge_col = "#DC2626" if ext in ("PDF", "") else ("#2563EB" if "DOC" in ext else ("#16A34A" if "XLS" in ext else "#D97706"))
        banner = QRectF(r0.left() + 2, r0.top() + 11, r0.width() - 4, 13)
        bp = QPainterPath()
        bp.addRoundedRect(banner, 2.5, 2.5)
        painter.fillPath(bp, QColor(badge_col))
        f = QFont("Segoe UI", 1, QFont.Weight.Bold)
        f.setPixelSize(8)
        painter.setFont(f)
        painter.setPen(QColor("#FFFFFF"))
        painter.drawText(banner, Qt.AlignmentFlag.AlignCenter, ext_tag if ext else "PDF")
        # Document miniature ruled lines
        painter.setPen(QPen(QColor("#8E95A5"), 1.4))
        painter.drawLine(QRectF(r0.left() + 6, r0.bottom() - 10, r0.width() - 12, 0).topLeft(),
                         QRectF(r0.left() + 6, r0.bottom() - 10, r0.width() - 12, 0).topRight())
        painter.drawLine(QRectF(r0.left() + 6, r0.bottom() - 6, r0.width() - 17, 0).topLeft(),
                         QRectF(r0.left() + 6, r0.bottom() - 6, r0.width() - 17, 0).topRight())

    elif is_music:
        bg_rect = QRectF(x + 4, y + 3, w - 8, h - 6)
        bp = QPainterPath()
        bp.addRoundedRect(bg_rect, 7, 7)
        painter.fillPath(bp, QColor("#211C28"))
        painter.setPen(QPen(QColor("#FF9500"), 1.2))
        painter.drawPath(bp)
        note = outline_pixmap("music", "#FF9500", 22, 2.0)
        painter.drawPixmap(int(bg_rect.center().x() - 11), int(bg_rect.center().y() - 11), note)

    else:
        # Programs / Generic package
        bg_rect = QRectF(x + 4, y + 3, w - 8, h - 6)
        bp = QPainterPath()
        bp.addRoundedRect(bg_rect, 7, 7)
        painter.fillPath(bp, QColor("#1F2330"))
        painter.setPen(QPen(QColor("#3E455B"), 1.0))
        painter.drawPath(bp)
        f = QFont("Segoe UI", 1, QFont.Weight.Bold)
        f.setPixelSize(9)
        painter.setFont(f)
        painter.setPen(QColor("#FF9500"))
        painter.drawText(bg_rect, Qt.AlignmentFlag.AlignCenter, ext_tag)

    painter.restore()
