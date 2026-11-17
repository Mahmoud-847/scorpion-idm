# -*- coding: utf-8 -*-
"""
Scorpion IDM — Custom Title Bar, Sidebar Delegate, Stacked Download Card Delegate,
Inline Torrent File-Selection Panel, and Queue & Scheduler Dialog.
"""
import os
import re
from pathlib import Path

from PyQt6.QtCore import Qt, QEvent, QPointF, QRectF, QSize, pyqtSignal
from PyQt6.QtGui import (
    QColor,
    QFont,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
)
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyledItemDelegate,
    QStyle,
    QTableWidget,
    QTimeEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from scorpion_brand import (
    PALETTES,
    draw_card_file_badge,
    outline_icon,
    outline_pixmap,
    prefers_reduced_motion,
    scorpion_emblem_pixmap,
)


def _pal() -> dict:
    app = QApplication.instance()
    dark = True if app is None else (app.property("scorpionTheme") != "light")
    return PALETTES["dark" if dark else "light"]


def _bidi_run(text: str) -> str:
    return "\u200e" + str(text) + "\u200e"


def _bidi_filename(name: str) -> str:
    s = str(name or "")
    if not s:
        return ""
    if not re.search(r"[\u0600-\u06FF]", s):
        return "\u2066" + s + "\u2069"
    m = re.search(r"([0-9A-Za-z.-]*\.[A-Za-z0-9]{1,8})$", s)
    if m:
        return f"{s[:m.start()]}\u2066\u200e{m.group(1)}\u2069"
    return s


def _fmt_bytes(b: int) -> str:
    if not b or b <= 0:
        return "0 B"
    units = ("B", "KB", "MB", "GB", "TB")
    val = float(b)
    i = 0
    while val >= 1024.0 and i < len(units) - 1:
        val /= 1024.0
        i += 1
    if units[i] in ("GB", "TB") or val < 10:
        return f"{val:.1f} {units[i]}"
    return f"{val:.0f} {units[i]}"


def _fmt_speed(bps: int) -> str:
    if not bps or bps <= 0:
        return "0 KB/s"
    return f"{_fmt_bytes(bps)}/s"


def _fmt_eta(sec) -> str:
    if sec is None or sec < 0:
        return "—"
    if sec == 0:
        return "0s"
    m, s = divmod(int(sec), 60)
    h, m = divmod(m, 60)
    if h > 0:
        return f"{h}h {m}m"
    if m > 0:
        return f"{m}m {s}s"
    return f"{s}s"


def apply_win32_window_effects(win: QWidget, is_dark: bool) -> None:
    """Applies Windows 11 DWM dark frame and rounded corners with explicit 64-bit argtypes and safe fallback."""
    if os.name != "nt" or QApplication.platformName() != "windows":
        return
    if not win.isVisible() or win.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen):
        return
    try:
        import ctypes
        from ctypes import wintypes

        hwnd = int(win.winId())
        if not hwnd:
            return
        dwm_fn = ctypes.windll.dwmapi.DwmSetWindowAttribute
        dwm_fn.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm_fn.restype = ctypes.c_long
        # DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        dark_val = ctypes.c_int(1 if is_dark else 0)
        dwm_fn(wintypes.HWND(hwnd), 20, ctypes.byref(dark_val), ctypes.sizeof(dark_val))
        # DWMWA_WINDOW_CORNER_PREFERENCE = 33 -> DWMWCP_ROUND = 2
        corner_val = ctypes.c_int(2)
        dwm_fn(wintypes.HWND(hwnd), 33, ctypes.byref(corner_val), ctypes.sizeof(corner_val))
    except Exception:
        pass


class ScorpionTitleBar(QFrame):
    """Custom Windows 11-style title bar matching the Golden-Scorpion header reference."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setObjectName("TitleBarFrame")
        self.setFixedHeight(38)
        self._drag_pos = None

        lay = QHBoxLayout(self)
        lay.setContentsMargins(14, 0, 8, 0)
        lay.setSpacing(9)

        self.lbl_icon = QLabel()
        self.lbl_icon.setFixedSize(22, 22)
        self.lbl_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.lbl_icon)

        self.lbl_title = QLabel("Scorpion IDM")
        self.lbl_title.setStyleSheet("font-size: 13.5px; font-weight: 600;")
        lay.addWidget(self.lbl_title)
        lay.addStretch(1)

        self.btn_min = QPushButton()
        self.btn_min.setObjectName("WinCtrlBtn")
        self.btn_min.setFixedSize(40, 30)
        self.btn_min.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_min.clicked.connect(parent.showMinimized)

        self.btn_max = QPushButton()
        self.btn_max.setObjectName("WinCtrlBtn")
        self.btn_max.setFixedSize(40, 30)
        self.btn_max.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_max.clicked.connect(self._toggle_maximize)

        self.btn_close = QPushButton()
        self.btn_close.setObjectName("WinCloseBtn")
        self.btn_close.setFixedSize(42, 30)
        self.btn_close.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_close.clicked.connect(parent.close)

        for b in (self.btn_min, self.btn_max, self.btn_close):
            b.setIconSize(QSize(13, 13))
            b.setFocusPolicy(Qt.FocusPolicy.NoFocus)
            lay.addWidget(b)

        self.refresh_theme(is_ar=False)

    def _toggle_maximize(self):
        w = self.window()
        if w.isMaximized():
            w.showNormal()
        else:
            w.showMaximized()
        self.refresh_max_icon()

    def refresh_max_icon(self):
        p = _pal()
        is_max = self.window().isMaximized()
        self.btn_max.setIcon(outline_icon("restore" if is_max else "maximize", p["text_sec"], 13, 1.7))

    def refresh_theme(self, is_ar: bool = False):
        p = _pal()
        self.lbl_icon.setPixmap(scorpion_emblem_pixmap(22, small=True))
        self.lbl_title.setStyleSheet(f"font-size: 13.5px; font-weight: 600; color: {p['text']};")
        self.btn_min.setIcon(outline_icon("minimize", p["text_sec"], 13, 1.7))
        self.btn_max.setIcon(outline_icon("restore" if self.window().isMaximized() else "maximize", p["text_sec"], 13, 1.7))
        self.btn_close.setIcon(outline_icon("close", p["text_sec"], 13, 1.7))
        self.btn_min.setAccessibleName("تصغير" if is_ar else "Minimize")
        self.btn_max.setAccessibleName("استعادة" if (is_ar and self.window().isMaximized()) else ("تكبير" if is_ar else ("Restore" if self.window().isMaximized() else "Maximize")))
        self.btn_close.setAccessibleName("إغلاق" if is_ar else "Close")
        self.btn_min.setToolTip(self.btn_min.accessibleName())
        self.btn_max.setToolTip(self.btn_max.accessibleName())
        self.btn_close.setToolTip(self.btn_close.accessibleName())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child not in (self.btn_min, self.btn_max, self.btn_close):
                wh = self.window().windowHandle()
                if wh is not None and wh.startSystemMove():
                    return
                self._drag_pos = event.globalPosition().toPoint() - self.window().frameGeometry().topLeft()
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None and (event.buttons() & Qt.MouseButton.LeftButton):
            if not self.window().isMaximized():
                self.window().move(event.globalPosition().toPoint() - self._drag_pos)
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            child = self.childAt(event.position().toPoint())
            if child not in (self.btn_min, self.btn_max, self.btn_close):
                self._toggle_maximize()
                return
        super().mouseDoubleClickEvent(event)


SIDEBAR_ROLE_ICON = Qt.ItemDataRole.UserRole + 10


class SidebarDelegate(QStyledItemDelegate):
    """Paints sidebar category items with raised card pill, amber outline icon, and leading accent marker."""

    def sizeHint(self, option, index):
        sh = super().sizeHint(option, index)
        return QSize(sh.width(), 38)

    def paint(self, painter, option, index):
        p = _pal()
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        focused = bool(option.state & QStyle.StateFlag.State_HasFocus)

        rect = QRectF(option.rect).adjusted(2, 2, -2, -2)
        if selected:
            pill = QPainterPath()
            pill.addRoundedRect(rect, 8, 8)
            painter.fillPath(pill, QColor(p["surface2"]))
            # Narrow leading amber selection marker
            bar_w = 3.0
            bar_r = QRectF(rect.right() - bar_w - 1, rect.top() + 7, bar_w, rect.height() - 14) if rtl else QRectF(rect.left() + 1, rect.top() + 7, bar_w, rect.height() - 14)
            bp = QPainterPath()
            bp.addRoundedRect(bar_r, 1.5, 1.5)
            painter.fillPath(bp, QColor(p["accent"]))
        elif hovered:
            pill = QPainterPath()
            pill.addRoundedRect(rect, 8, 8)
            painter.fillPath(pill, QColor(p["surface"]))

        if focused and not selected:
            pen = QPen(QColor(p["accent"]), 1.2)
            painter.setPen(pen)
            painter.drawRoundedRect(rect, 8, 8)

        # Resolve icon key and count from col 0 and col 1 of the tree row
        model = index.model()
        c0_idx = model.index(index.row(), 0, index.parent())
        c1_idx = model.index(index.row(), 1, index.parent())
        icon_name = c0_idx.data(SIDEBAR_ROLE_ICON) or "all_downloads"
        label_txt = str(c0_idx.data(Qt.ItemDataRole.DisplayRole) or "")
        count_txt = str(c1_idx.data(Qt.ItemDataRole.DisplayRole) or "").strip()

        if index.column() == 0:
            ico_col = p["accent"] if selected else p["muted"]
            pm = outline_pixmap(icon_name, ico_col, 16, 1.9)
            ico_size = 16
            if rtl:
                ix = rect.right() - 12 - ico_size
                count_reserve = 28 if count_txt else 8
                tx_rect = QRectF(rect.left() + 6, rect.top(), max(20.0, ix - rect.left() - 16), rect.height())
                align = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter
            else:
                ix = rect.left() + 12
                tx_rect = QRectF(ix + ico_size + 11, rect.top(), max(20.0, rect.right() - (ix + ico_size + 14)), rect.height())
                align = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute | Qt.AlignmentFlag.AlignVCenter

            painter.drawPixmap(int(round(ix)), int(round(rect.center().y() - ico_size / 2.0)), pm)
            f = QFont(option.font)
            f.setPixelSize(13)
            f.setWeight(QFont.Weight.DemiBold if selected else QFont.Weight.Medium)
            painter.setFont(f)
            painter.setPen(QColor(p["text"] if selected else p["text_sec"]))
            elided = painter.fontMetrics().elidedText(label_txt, Qt.TextElideMode.ElideRight, int(tx_rect.width()))
            painter.drawText(tx_rect, align, elided)
        elif count_txt:
            f = QFont(option.font)
            f.setPixelSize(11)
            f.setWeight(QFont.Weight.DemiBold)
            painter.setFont(f)
            painter.setPen(QColor(p["accent"] if selected else p["muted"]))
            painter.drawText(rect.adjusted(2, 0, -6, 0), Qt.AlignmentFlag.AlignCenter, count_txt)

        painter.restore()


# Data roles used on column 0 of the stacked download card list
ROLE_CARD_META = Qt.ItemDataRole.UserRole + 20


_FINALIZING_MODES = ("merging", "verifying", "saving")
_RUNNING_MODES = ("active", "connecting", *_FINALIZING_MODES)


def _draw_progress_bar(
    painter: QPainter,
    bar_rect: QRectF,
    pct: float,
    mode: str,
    p: dict,
    rtl: bool = False,
) -> None:
    """Draws slim rounded progress bar with warm amber-orange gradient and gentle glow."""
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    h = bar_rect.height()
    r = h / 2.0
    track = QPainterPath()
    track.addRoundedRect(bar_rect, r, r)
    painter.fillPath(track, QColor(p["track"]))

    fill_pct = 100.0 if mode == "done" else max(0.0, min(100.0, float(pct or 0.0)))
    if mode == "connecting" and fill_pct < 1.0:
        fill_pct = 18.0
    fw = bar_rect.width() * (fill_pct / 100.0)
    if fw > 0.5:
        if fw < h:
            fw = min(bar_rect.width(), h)
        fill_rect = (
            QRectF(bar_rect.right() - fw, bar_rect.top(), fw, h)
            if rtl
            else QRectF(bar_rect.left(), bar_rect.top(), fw, h)
        )
        # Subtle warm glow halo on active/done progress bars
        if mode in _RUNNING_MODES or mode == "done":
            glow = QPainterPath()
            glow.addRoundedRect(fill_rect.adjusted(-1.5, -2.5, 1.5, 2.5), r + 2, r + 2)
            glow_col = QColor(p["accent"])
            glow_col.setAlpha(42 if mode in _RUNNING_MODES else 24)
            painter.fillPath(glow, glow_col)

        painter.setClipPath(track)
        fill_path = QPainterPath()
        fill_path.addRoundedRect(fill_rect, r, r)
        if mode == "error":
            painter.fillPath(fill_path, QColor(p["danger"]))
        elif mode == "paused":
            paused_col = QColor(p["accent"])
            paused_col.setAlpha(155)
            painter.fillPath(fill_path, paused_col)
        else:
            grad = QLinearGradient(fill_rect.left(), 0, fill_rect.right(), 0)
            if rtl:
                grad.setColorAt(0.0, QColor(p["accent_intense"]))
                grad.setColorAt(1.0, QColor(p["accent"]))
            else:
                grad.setColorAt(0.0, QColor(p["accent"]))
                grad.setColorAt(1.0, QColor(p["accent_intense"]))
            painter.fillPath(fill_path, grad)
    painter.restore()


def _compute_card_layout(row_rect: QRectF, meta: dict, rtl: bool, expanded: bool) -> dict:
    """Single source of truth for painting AND mouse hit-testing card elements."""
    card_top_h = 78.0
    card = QRectF(row_rect.left() + 2, row_rect.top() + 3, max(200.0, row_rect.width() - 6), max(card_top_h, row_rect.height() - 8))
    header = QRectF(card.left(), card.top(), card.width(), card_top_h)

    badge_sz = 44.0
    pad_x = 16.0
    # Right controls area depends on state
    mode = meta.get("mode", "paused")
    is_torrent = bool(meta.get("isTorrent"))
    ctrl_w = 88.0
    if mode == "done":
        ctrl_w = 196.0
    elif mode in _RUNNING_MODES:
        ctrl_w = 132.0 if is_torrent else 86.0
    elif mode == "paused":
        ctrl_w = 48.0
    elif mode == "error":
        ctrl_w = 104.0 if not meta.get("restartOnly") else 46.0
    elif mode in ("queued", "scheduled"):
        ctrl_w = 84.0
    if is_torrent:
        ctrl_w = max(ctrl_w, 120.0 if mode != "done" else 196.0)

    if rtl:
        badge_r = QRectF(header.right() - pad_x - badge_sz, header.top() + (card_top_h - badge_sz) / 2.0, badge_sz, badge_sz)
        ctrl_area = QRectF(header.left() + pad_x, header.top(), ctrl_w, card_top_h)
        info_left = ctrl_area.right() + 14.0
        info_right = badge_r.left() - 14.0
    else:
        badge_r = QRectF(header.left() + pad_x, header.top() + (card_top_h - badge_sz) / 2.0, badge_sz, badge_sz)
        ctrl_area = QRectF(header.right() - pad_x - ctrl_w, header.top(), ctrl_w, card_top_h)
        info_left = badge_r.right() + 14.0
        info_right = ctrl_area.left() - 14.0

    info_r = QRectF(info_left, header.top() + 10.0, max(90.0, info_right - info_left), card_top_h - 18.0)

    # Progress bar spans along the lower part of info_r
    show_bar = mode in (*_RUNNING_MODES, "done", "error") or (mode == "paused" and float(meta.get("progress") or 0) > 0)
    if mode == "done":
        bar_w = max(80.0, info_r.width() - 50.0)
    elif mode == "paused":
        bar_w = min(info_r.width() * 0.45, max(100.0, info_r.width() - 180.0))
    else:
        bar_w = min(info_r.width(), max(115.0, info_r.width() * 0.46))
    bar_h = 6.0
    if show_bar:
        if rtl:
            bar_r = QRectF(info_r.right() - bar_w, info_r.bottom() - bar_h - 3.0, bar_w, bar_h)
            stats_r = QRectF(info_r.left(), info_r.bottom() - 20.0, max(10.0, bar_r.left() - info_r.left() - 10.0), 20.0)
        else:
            bar_r = QRectF(info_r.left(), info_r.bottom() - bar_h - 3.0, bar_w, bar_h)
            stats_r = QRectF(bar_r.right() + 12.0, info_r.bottom() - 20.0, max(10.0, info_r.right() - bar_r.right() - 12.0), 20.0)
    else:
        bar_r = QRectF()
        stat_w = min(info_r.width() * 0.65, max(120.0, info_r.width() - 95.0))
        stats_r = (
            QRectF(info_r.left(), info_r.top() + 21.0, stat_w, 20.0)
            if rtl
            else QRectF(info_r.right() - stat_w, info_r.top() + 21.0, stat_w, 20.0)
        )

    buttons: dict[str, tuple[QRectF, dict]] = {}
    mid_y = header.top() + card_top_h / 2.0
    if is_torrent and mode != "done":
        cx = ctrl_area.left() if rtl else ctrl_area.right() - 118.0
        buttons["toggle_torrent"] = (QRectF(cx, header.top() + 8.0, 118.0, 24.0), {})
        if mode in ("active", "connecting"):
            bsz = 26.0
            gap = 6.0
            btn_y = header.top() + 43.0
            bx0 = ctrl_area.left() if rtl else ctrl_area.right() - (2 * bsz + gap)
            buttons["pause"] = (QRectF(bx0, btn_y, bsz, bsz), {})
            buttons["cancel"] = (QRectF(bx0 + bsz + gap, btn_y, bsz, bsz), {})
        elif mode in _FINALIZING_MODES:
            bsz = 26.0
            bx = ctrl_area.left() if rtl else ctrl_area.right() - bsz
            buttons["cancel"] = (QRectF(bx, header.top() + 43.0, bsz, bsz), {})
        elif mode == "paused":
            bsz = 28.0
            bx = ctrl_area.left() if rtl else ctrl_area.right() - bsz
            buttons["resume"] = (QRectF(bx, header.top() + 42.0, bsz, bsz), {"circle": True})
    elif mode in _RUNNING_MODES:
        bsz = 30.0
        gap = 8.0
        btn_y = header.top() + (card_top_h - bsz) / 2.0 + 6.0
        bx0 = ctrl_area.left() if rtl else ctrl_area.right() - (2 * bsz + gap)
        if mode not in _FINALIZING_MODES:
            buttons["pause"] = (QRectF(bx0, btn_y, bsz, bsz), {})
        buttons["cancel"] = (QRectF(bx0 + bsz + gap, btn_y, bsz, bsz), {})
    elif mode == "paused":
        bsz = 34.0
        bx = ctrl_area.left() if rtl else ctrl_area.right() - bsz
        buttons["resume"] = (QRectF(bx, mid_y - bsz / 2.0, bsz, bsz), {"circle": True})
    elif mode in ("queued", "scheduled"):
        bsz = 30.0
        gap = 8.0
        bx0 = ctrl_area.left() if rtl else ctrl_area.right() - (2 * bsz + gap)
        buttons["resume"] = (QRectF(bx0, mid_y - bsz / 2.0, bsz, bsz), {})
        buttons["cancel"] = (QRectF(bx0 + bsz + gap, mid_y - bsz / 2.0, bsz, bsz), {})
    elif mode == "error":
        bh = 30.0
        if meta.get("restartOnly"):
            bx = ctrl_area.left() if rtl else ctrl_area.right() - 34.0
            buttons["cancel"] = (QRectF(bx, mid_y - bh / 2.0, 32.0, bh), {})
        else:
            bw = 64.0
            gap = 6.0
            bx0 = ctrl_area.left() if rtl else ctrl_area.right() - (bw + 32.0 + gap)
            buttons["retry"] = (QRectF(bx0, mid_y - bh / 2.0, bw, bh), {"pill": True})
            buttons["cancel"] = (QRectF(bx0 + bw + gap, mid_y - bh / 2.0, 30.0, bh), {})
    elif mode == "done":
        bh = 30.0
        w_open, w_folder, gap = 80.0, 106.0, 8.0
        bx0 = ctrl_area.left() if rtl else ctrl_area.right() - (w_open + w_folder + gap)
        buttons["open"] = (QRectF(bx0, mid_y - bh / 2.0, w_open, bh), {"pill": True})
        buttons["folder"] = (QRectF(bx0 + w_open + gap, mid_y - bh / 2.0, w_folder, bh), {"pill": True})

    body_panel_r = QRectF(card.left() + 14.0, card.top() + card_top_h, card.width() - 28.0, max(0.0, card.height() - card_top_h - 10.0)) if expanded else QRectF()

    return {
        "card": card,
        "header": header,
        "badge": badge_r,
        "info": info_r,
        "ctrl": ctrl_area,
        "bar": bar_r,
        "stats": stats_r,
        "show_bar": show_bar,
        "buttons": buttons,
        "panel": body_panel_r,
    }


class DownloadCardRowDelegate(QStyledItemDelegate):
    """Paints each stacked download card with crisp typography, glowing progress, and live controls."""

    def __init__(self, parent_table, window):
        super().__init__(parent_table)
        self.table = parent_table
        self.win = window

    def paint(self, painter, option, index):
        if index.column() != 0:
            return
        meta = index.data(ROLE_CARD_META)
        if not isinstance(meta, dict):
            return
        p = _pal()
        rtl = option.direction == Qt.LayoutDirection.RightToLeft
        is_ar = meta.get("isAr", False)
        mode = meta.get("mode", "paused")
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        row = index.row()
        hover_key = getattr(self.table, "_hover_btn", None)
        if not hover_key or hover_key[0] != row:
            hovered_id = None
        else:
            hovered_id = hover_key[1]

        expanded = bool(meta.get("expanded"))
        geo = _compute_card_layout(QRectF(option.rect), meta, rtl, expanded)
        if hasattr(self.table, "_row_btn_map"):
            self.table._row_btn_map[row] = {k: v[0] for k, v in geo["buttons"].items()}

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        card = geo["card"]

        # Subtle outer amber glow for active download
        if mode in _RUNNING_MODES:
            glow = QPainterPath()
            glow.addRoundedRect(card.adjusted(-2, -2, 2, 2), 13, 13)
            gc = QColor(p["accent"])
            gc.setAlpha(28)
            painter.fillPath(glow, gc)

        card_path = QPainterPath()
        card_path.addRoundedRect(card, 11, 11)
        bg_col = QColor(p["card_active_bg"] if mode in _RUNNING_MODES else p["surface"])
        painter.fillPath(card_path, bg_col)

        if selected:
            bcol = QColor(p["accent"])
            bw = 1.5
        elif mode in _RUNNING_MODES:
            bcol = QColor(p["border_amber"])
            bw = 1.25
        elif mode == "error":
            bcol = QColor(p["danger"])
            bcol.setAlpha(150)
            bw = 1.2
        else:
            bcol = QColor(p["border"])
            bw = 1.0
        painter.setPen(QPen(bcol, bw))
        painter.drawPath(card_path)

        # File-type badge
        draw_card_file_badge(
            painter,
            geo["badge"],
            meta.get("rawName", ""),
            meta.get("category", "General"),
            is_torrent=bool(meta.get("isTorrent")),
            p=p,
        )

        # Filename & size / error line
        info = geo["info"]
        f_title = QFont(option.font)
        f_title.setPixelSize(14)
        f_title.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f_title)
        painter.setPen(QColor(p["text"]))

        name_w = int(max(40, info.width()))
        raw_name = meta.get("rawName", "")
        elided_name = painter.fontMetrics().elidedText(raw_name, Qt.TextElideMode.ElideMiddle, name_w)
        display_name = _bidi_filename(elided_name)
        title_align = (
            (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
            if rtl
            else (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
        ) | Qt.AlignmentFlag.AlignVCenter
        painter.drawText(QRectF(info.left(), info.top(), info.width(), 20), title_align, display_name)

        sub_txt = meta.get("sizeLine", "")
        sub_col = p["danger"] if (mode == "error" and meta.get("errorShort")) else p["muted"]
        if mode == "error" and meta.get("errorShort"):
            sub_txt = meta["errorShort"]
        f_sub = QFont(option.font)
        f_sub.setPixelSize(12)
        f_sub.setWeight(QFont.Weight.Normal)
        painter.setFont(f_sub)
        painter.setPen(QColor(sub_col))
        sub_avail = max(40.0, info.width() - geo["stats"].width() - 10.0) if (not geo["show_bar"] and meta.get("statsLine")) else info.width()
        sub_rect = QRectF(info.right() - sub_avail, info.top() + 21, sub_avail, 18) if rtl else QRectF(info.left(), info.top() + 21, sub_avail, 18)
        elided_sub = painter.fontMetrics().elidedText(sub_txt, Qt.TextElideMode.ElideRight, int(sub_avail))
        painter.drawText(sub_rect, title_align, elided_sub)

        # Progress bar + metrics row
        if geo["show_bar"] and not geo["bar"].isNull():
            _draw_progress_bar(painter, geo["bar"], float(meta.get("progress") or 0), mode, p, rtl=rtl)

        stats_txt = meta.get("statsLine", "")
        if stats_txt:
            f_st = QFont(option.font)
            f_st.setPixelSize(12)
            f_st.setWeight(QFont.Weight.Medium)
            painter.setFont(f_st)
            painter.setPen(QColor(p["text_sec"] if mode == "done" else p["muted"]))
            st_align = (
                (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
                if rtl
                else (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
            ) | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(geo["stats"], st_align, painter.fontMetrics().elidedText(stats_txt, Qt.TextElideMode.ElideRight, int(max(20, geo["stats"].width()))))

        # Top connection badge or "Torrent selection" caption inside ctrl_area
        ctrl = geo["ctrl"]
        if meta.get("connCount", 0) > 1 and not meta.get("isTorrent") and not meta.get("browserTransfer"):
            conn_str = str(meta["connCount"])
            pm_peers = outline_pixmap("peers", p["accent"], 13, 1.9)
            f_c = QFont(option.font)
            f_c.setPixelSize(12)
            f_c.setWeight(QFont.Weight.DemiBold)
            painter.setFont(f_c)
            painter.setPen(QColor(p["accent"]))
            if rtl:
                painter.drawPixmap(int(ctrl.left()), int(ctrl.top() + 10), pm_peers)
                painter.drawText(QRectF(ctrl.left() + 17, ctrl.top() + 8, 30, 18), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, _bidi_run(conn_str))
            else:
                tw = painter.fontMetrics().horizontalAdvance(conn_str)
                x_ico = ctrl.right() - tw - 18
                painter.drawPixmap(int(x_ico), int(ctrl.top() + 10), pm_peers)
                painter.drawText(QRectF(ctrl.right() - tw - 2, ctrl.top() + 8, tw + 2, 18), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, conn_str)
        elif meta.get("isTorrent") and mode != "done":
            tag_txt = "تحديد التورنت" if is_ar else "Torrent selection"
            f_t = QFont(option.font)
            f_t.setPixelSize(12)
            f_t.setWeight(QFont.Weight.Medium)
            painter.setFont(f_t)
            painter.setPen(QColor(p["text_sec"]))
            t_r = (
                QRectF(ctrl.left() + 26, ctrl.top() + 11, ctrl.width() - 26, 18)
                if rtl
                else QRectF(ctrl.left(), ctrl.top() + 11, ctrl.width() - 26, 18)
            )
            t_align = (
                (Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignAbsolute)
                if rtl
                else (Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignAbsolute)
            ) | Qt.AlignmentFlag.AlignVCenter
            painter.drawText(t_r, t_align, tag_txt)

        # Interactive Buttons inside ctrl_area
        f_btn = QFont(option.font)
        f_btn.setPixelSize(12)
        f_btn.setWeight(QFont.Weight.DemiBold)
        painter.setFont(f_btn)

        for bid, (brect, bopts) in geo["buttons"].items():
            is_hov = hovered_id == bid
            if bid == "toggle_torrent":
                ico = "chevron_up" if expanded else "chevron_down"
                chevron_r = QRectF(brect.left(), brect.top(), 24.0, brect.height()) if rtl else QRectF(brect.right() - 24.0, brect.top(), 24.0, brect.height())
                if is_hov:
                    hp = QPainterPath()
                    hp.addRoundedRect(brect, 6, 6)
                    hc = QColor(p["accent"])
                    hc.setAlpha(28)
                    painter.fillPath(hp, hc)
                pm = outline_pixmap(ico, p["text_sec"], 14, 2.0)
                painter.drawPixmap(int(chevron_r.center().x() - 7), int(chevron_r.center().y() - 7), pm)
            elif bopts.get("circle"):
                bg_b = p["btn_hover"] if is_hov else p["surface2"]
                bd_b = p["accent"] if is_hov else p["border"]
                painter.setPen(QPen(QColor(bd_b), 1.2))
                painter.setBrush(QColor(bg_b))
                painter.drawEllipse(brect)
                ico_col = p["accent"] if bid == "resume" else p["text"]
                pm = outline_pixmap("resume_cw" if bid == "resume" else "play", ico_col, 15, 2.0)
                painter.drawPixmap(int(brect.center().x() - 7.5), int(brect.center().y() - 7.5), pm)
            elif bopts.get("pill"):
                bp = QPainterPath()
                bp.addRoundedRect(brect, 7, 7)
                painter.fillPath(bp, QColor(p["btn_hover"] if is_hov else p["btn_bg"]))
                painter.setPen(QPen(QColor(p["accent"] if (is_hov and bid == "retry") else p["border"]), 1.0))
                painter.drawPath(bp)
                lbl_map = {
                    "open": ("تشغيل" if is_ar else "Open File"),
                    "folder": ("فتح المجلد" if is_ar else "Show in Folder"),
                    "retry": ("إعادة" if is_ar else "Retry"),
                }
                painter.setPen(QColor(p["accent"] if bid == "retry" else p["text"]))
                painter.drawText(brect, Qt.AlignmentFlag.AlignCenter, lbl_map.get(bid, bid))
            else:
                # Square icon button (pause / cancel / resume)
                bp = QPainterPath()
                bp.addRoundedRect(brect, 7, 7)
                if bid == "cancel":
                    fill_c = QColor("#D9531E" if is_hov else "#2C1B12")
                    bd_c = QColor("#FF6B2B")
                    ico_name, ico_col = "stop", "#FF7828" if not is_hov else "#FFFFFF"
                elif bid == "pause":
                    fill_c = QColor(p["btn_hover"] if is_hov else p["surface2"])
                    bd_c = QColor(p["muted"] if is_hov else p["border"])
                    ico_name, ico_col = "pause", p["text_sec"]
                else:
                    fill_c = QColor(p["btn_hover"] if is_hov else p["surface2"])
                    bd_c = QColor(p["accent"] if is_hov else p["border"])
                    ico_name, ico_col = "play", p["accent"]
                painter.fillPath(bp, fill_c)
                painter.setPen(QPen(bd_c, 1.0))
                painter.drawPath(bp)
                pm = outline_pixmap(ico_name, ico_col, 13, 2.0)
                painter.drawPixmap(int(brect.center().x() - 6.5), int(brect.center().y() - 6.5), pm)

        painter.restore()


class DownloadCardTableWidget(QTableWidget):
    """QTableWidget rendering stacked interactive cards with row-button hit testing."""

    card_action = pyqtSignal(str, str)  # dl_id, action

    def __init__(self, parent=None):
        super().__init__(0, 6, parent)
        self.setObjectName("DownloadCardList")
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        self._row_btn_map: dict[int, dict[str, QRectF]] = {}
        self._hover_btn: tuple[int, str] | None = None
        self._pressed_btn: tuple[int, str] | None = None

    def _hit_button(self, pos: QPointF) -> tuple[int, str] | None:
        idx = self.indexAt(pos.toPoint())
        if not idx.isValid():
            return None
        row = idx.row()
        btns = self._row_btn_map.get(row) or {}
        for bid, brect in btns.items():
            if brect.adjusted(-3, -3, 3, 3).contains(pos):
                return (row, bid)
        return None

    def mouseMoveEvent(self, event):
        hit = self._hit_button(event.position())
        if hit != self._hover_btn:
            old_row = self._hover_btn[0] if self._hover_btn else -1
            self._hover_btn = hit
            self.viewport().setCursor(Qt.CursorShape.PointingHandCursor if hit else Qt.CursorShape.ArrowCursor)
            for r in {old_row, hit[0] if hit else -1}:
                if r >= 0:
                    self.viewport().update(self.visualRect(self.model().index(r, 0)))
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            hit = self._hit_button(event.position())
            if hit is not None:
                self._pressed_btn = hit
                self.setCurrentCell(hit[0], 0)
                event.accept()
                return
        self._pressed_btn = None
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._pressed_btn is not None:
            pressed = self._pressed_btn
            self._pressed_btn = None
            hit = self._hit_button(event.position())
            if hit == pressed:
                cell = self.item(hit[0], 0)
                dl_id = cell.data(Qt.ItemDataRole.UserRole) if cell else None
                if dl_id:
                    self.card_action.emit(dl_id, hit[1])
                event.accept()
                return
        super().mouseReleaseEvent(event)

    def leaveEvent(self, event):
        if self._hover_btn is not None:
            r = self._hover_btn[0]
            self._hover_btn = None
            self.viewport().setCursor(Qt.CursorShape.ArrowCursor)
            if 0 <= r < self.rowCount():
                self.viewport().update(self.visualRect(self.model().index(r, 0)))
        super().leaveEvent(event)


class TorrentInlinePanel(QFrame):
    """Inline expandable torrent file-selection panel matching the reference Ubuntu ISO card."""

    selection_applied = pyqtSignal(str, list)  # dl_id, selected_indices

    def __init__(self, dl_id: str, item: dict, is_ar: bool, parent=None):
        super().__init__(parent)
        self.dl_id = dl_id
        self.is_ar = is_ar
        self.T = (lambda ar, en: ar) if is_ar else (lambda ar, en: en)
        self._syncing = False
        self._file_by_idx: dict[int, dict] = {}
        self._preview_checks: dict[int, QCheckBox] = {}
        self._tree_items: dict[int, QTreeWidgetItem] = {}
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_ar else Qt.LayoutDirection.LeftToRight)

        p = _pal()
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 78, 16, 10)
        outer.setSpacing(6)

        box = QFrame()
        box.setObjectName("TorrentExpandBox")
        box.setStyleSheet(
            f"#TorrentExpandBox {{ background: {p['surface3']}; border: 1px solid {p['border']}; border-radius: 9px; }}"
        )
        grid = QHBoxLayout(box)
        grid.setContentsMargins(12, 10, 12, 10)
        grid.setSpacing(12)

        # Left Pane: File selection preview with checkboxes
        left = QVBoxLayout()
        left.setSpacing(6)
        self.chk_master = QCheckBox(self.T("معاينة اختيار الملفات", "File selection preview"))
        self.chk_master.setChecked(True)
        self.chk_master.setStyleSheet(f"font-weight: 600; color: {p['text']};")
        self.chk_master.toggled.connect(self._on_master_toggled)
        left.addWidget(self.chk_master)

        self.scroll_preview = QScrollArea()
        self.scroll_preview.setWidgetResizable(True)
        self.scroll_preview.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_preview.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; border: none; }")
        self._preview_container = QWidget()
        self._preview_lay = QVBoxLayout(self._preview_container)
        self._preview_lay.setContentsMargins(6, 2, 4, 2)
        self._preview_lay.setSpacing(4)
        self._preview_lay.addStretch(1)
        self.scroll_preview.setWidget(self._preview_container)
        left.addWidget(self.scroll_preview, 1)

        # Right Pane: Hierarchical Files Tree + Apply selection
        right = QFrame()
        right.setStyleSheet(f"QFrame {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 7px; }}")
        rlay = QVBoxLayout(right)
        rlay.setContentsMargins(10, 8, 10, 8)
        rlay.setSpacing(6)

        rhdr = QHBoxLayout()
        rhdr.setSpacing(6)
        lbl_files = QLabel(self.T("الملفات", "Files"))
        lbl_files.setStyleSheet(f"font-size: 12.5px; font-weight: 600; color: {p['text']}; border: none;")
        rhdr.addWidget(lbl_files)
        self.lbl_summary = QLabel()
        self.lbl_summary.setStyleSheet(f"font-size: 11.5px; color: {p['muted']}; border: none;")
        rhdr.addWidget(self.lbl_summary)
        rhdr.addStretch(1)
        self.btn_apply = QPushButton(self.T("تطبيق الاختيار", "Apply"))
        self.btn_apply.setObjectName("PrimaryBtn")
        self.btn_apply.setFixedHeight(24)
        self.btn_apply.setStyleSheet("padding: 2px 12px; font-size: 11.5px;")
        self.btn_apply.clicked.connect(self._emit_apply)
        rhdr.addWidget(self.btn_apply)
        rlay.addLayout(rhdr)

        self.tree_files = QTreeWidget()
        self.tree_files.setObjectName("TorrentSubTree")
        self.tree_files.setColumnCount(2)
        self.tree_files.setHeaderHidden(True)
        self.tree_files.setIndentation(14)
        self.tree_files.header().setStretchLastSection(False)
        self.tree_files.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree_files.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.tree_files.itemChanged.connect(self._on_tree_item_changed)
        rlay.addWidget(self.tree_files, 1)

        grid.addLayout(left, 11)
        grid.addWidget(right, 10)
        outer.addWidget(box, 1)

        self._files_sig = None
        self.update_from(item)

    def update_from(self, item: dict):
        files = list(item.get("torrentFiles") or [])
        if not files:
            # Show real single-file item or metadata-pending notice cleanly (no fake file data)
            st = item.get("status") or ""
            fname = item.get("filename") or ""
            tot = int(item.get("totalSize") or 0)
            if fname and tot > 0 and item.get("phase") not in ("connecting", "selecting"):
                files = [{"index": 1, "path": fname, "length": tot}]
            else:
                files = []
        sel = set(int(i) for i in (item.get("torrentSelection") or []))
        sig = (
            tuple((int(f.get("index") or 0), str(f.get("path") or ""), int(f.get("length") or 0)) for f in files),
            tuple(sorted(sel)),
        )
        if sig == self._files_sig:
            return
        self._files_sig = sig
        self._rebuild(files, sel)

    def _rebuild(self, files: list, sel_indices: set[int]):
        self._syncing = True
        try:
            self._file_by_idx.clear()
            self._preview_checks.clear()
            self._tree_items.clear()
            while self._preview_lay.count() > 1:
                child = self._preview_lay.takeAt(0)
                if child.widget():
                    child.widget().deleteLater()
            self.tree_files.clear()
            p = _pal()

            if not files:
                wait_lbl = QLabel(self.T("في انتظار قراءة قائمة ملفات التورنت...", "Waiting for torrent metadata..."))
                wait_lbl.setStyleSheet(f"color: {p['muted']}; font-size: 12px;")
                self._preview_lay.insertWidget(0, wait_lbl)
                self.chk_master.setEnabled(False)
                self.btn_apply.setEnabled(False)
                self.lbl_summary.setText("")
                return

            self.chk_master.setEnabled(True)
            self.btn_apply.setEnabled(True)
            folder_nodes: dict[tuple[str, ...], QTreeWidgetItem] = {}

            for i, f in enumerate(files):
                idx = int(f.get("index") or (i + 1))
                rel_path = str(f.get("path") or f"file_{idx}").replace("\\", "/").strip("/")
                length = int(f.get("length") or 0)
                checked = (not sel_indices) or (idx in sel_indices)
                self._file_by_idx[idx] = {"index": idx, "path": rel_path, "length": length}

                base_name = rel_path.rsplit("/", 1)[-1]
                cb = QCheckBox(_bidi_filename(base_name) + (f"  ({_bidi_run(_fmt_bytes(length))})" if length else ""))
                cb.setChecked(checked)
                cb.setStyleSheet(f"font-size: 12px; color: {p['text_sec']};")
                cb.toggled.connect(lambda state, k=idx: self._on_preview_toggled(k, state))
                self._preview_lay.insertWidget(self._preview_lay.count() - 1, cb)
                self._preview_checks[idx] = cb

                parts = [seg for seg in rel_path.split("/") if seg]
                parent_node = self.tree_files
                if len(parts) > 1:
                    for depth in range(len(parts) - 1):
                        key = tuple(parts[: depth + 1])
                        if key not in folder_nodes:
                            fn_item = QTreeWidgetItem(parent_node, [parts[depth], ""])
                            fn_item.setIcon(0, outline_icon("folder", p["accent"], 14, 1.8))
                            fn_item.setExpanded(True)
                            folder_nodes[key] = fn_item
                        parent_node = folder_nodes[key]
                file_node = QTreeWidgetItem(
                    parent_node,
                    [_bidi_filename(parts[-1] if parts else base_name), _bidi_run(_fmt_bytes(length)) if length else ""],
                )
                file_node.setIcon(0, outline_icon("documents", p["text_sec"], 14, 1.8))
                file_node.setData(0, Qt.ItemDataRole.UserRole, idx)
                file_node.setTextAlignment(1, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                file_node.setForeground(1, QColor(p["muted"]))
                file_node.setFlags(file_node.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                file_node.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
                self._tree_items[idx] = file_node

            self._update_summary()
        finally:
            self._syncing = False

    def _on_master_toggled(self, checked: bool):
        if self._syncing:
            return
        self._syncing = True
        try:
            for cb in self._preview_checks.values():
                cb.setChecked(checked)
            for ti in self._tree_items.values():
                ti.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._update_summary()
        finally:
            self._syncing = False

    def _on_preview_toggled(self, idx: int, checked: bool):
        if self._syncing:
            return
        self._syncing = True
        try:
            ti = self._tree_items.get(idx)
            if ti is not None:
                ti.setCheckState(0, Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self._sync_master_check()
            self._update_summary()
        finally:
            self._syncing = False

    def _on_tree_item_changed(self, item: QTreeWidgetItem, _col: int):
        if self._syncing:
            return
        idx = item.data(0, Qt.ItemDataRole.UserRole)
        if idx is None:
            return
        self._syncing = True
        try:
            checked = item.checkState(0) == Qt.CheckState.Checked
            cb = self._preview_checks.get(int(idx))
            if cb is not None:
                cb.setChecked(checked)
            self._sync_master_check()
            self._update_summary()
        finally:
            self._syncing = False

    def _sync_master_check(self):
        if not self._preview_checks:
            return
        all_on = all(cb.isChecked() for cb in self._preview_checks.values())
        self.chk_master.setChecked(all_on)

    def _update_summary(self):
        sel_idxs = self.selected_indices()
        total_b = sum(int(self._file_by_idx[i]["length"]) for i in sel_idxs if i in self._file_by_idx)
        n_sel, n_tot = len(sel_idxs), len(self._file_by_idx)
        if self.is_ar:
            self.lbl_summary.setText(f"• {_bidi_run(n_sel)}/{_bidi_run(n_tot)} ({_bidi_run(_fmt_bytes(total_b))})")
        else:
            self.lbl_summary.setText(f"• {n_sel}/{n_tot} ({_fmt_bytes(total_b)})")

    def selected_indices(self) -> list[int]:
        sel = [idx for idx, cb in self._preview_checks.items() if cb.isChecked()]
        return sel if sel else list(self._file_by_idx.keys())

    def _emit_apply(self):
        self.selection_applied.emit(self.dl_id, self.selected_indices())


class QueueSchedulerDialog(QDialog):
    """Queue Management & Daily Scheduler Configuration Dialog."""

    def __init__(self, engine, lang: str = "ar", parent=None):
        super().__init__(parent)
        self.engine = engine
        self.is_ar = lang == "ar"
        self.T = (lambda ar, en: ar) if self.is_ar else (lambda ar, en: en)
        self.setWindowTitle(self.T("إدارة الطوابير والجدولة — Scorpion IDM", "Queues & Scheduler — Scorpion IDM"))
        self.resize(620, 490)
        self.setLayoutDirection(Qt.LayoutDirection.RightToLeft if self.is_ar else Qt.LayoutDirection.LeftToRight)

        p = _pal()
        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Settings Card
        cfg = QFrame()
        cfg.setObjectName("CardFrame")
        gl = QGridLayout(cfg)
        gl.setContentsMargins(16, 14, 16, 14)
        gl.setHorizontalSpacing(12)
        gl.setVerticalSpacing(10)
        gl.setColumnStretch(1, 1)

        hdr = QLabel(self.T("إعدادات الطابور والجدول الزمني", "Queue & Schedule Settings"))
        hdr.setStyleSheet(f"font-size: 14px; font-weight: 700; color: {p['accent']};")
        gl.addWidget(hdr, 0, 0, 1, 3)

        gl.addWidget(QLabel(self.T("أقصى عدد تحميلات متزامنة:", "Max simultaneous downloads:")), 1, 0)
        self.spin_conc = QSpinBox()
        self.spin_conc.setRange(1, 20)
        self.spin_conc.setMaximumWidth(120)
        self.spin_conc.setValue(int(engine.settings.get("maxConcurrent", 4)))
        gl.addWidget(self.spin_conc, 1, 1)

        gl.addWidget(QLabel(self.T("حد السرعة الكلي (KB/s — 0 بدون حد):", "Global speed limit (KB/s — 0 = none):")), 2, 0)
        self.spin_limit = QSpinBox()
        self.spin_limit.setRange(0, 10_000_000)
        self.spin_limit.setMaximumWidth(140)
        self.spin_limit.setValue(int(engine.settings.get("globalSpeedLimitKbps", 0)))
        gl.addWidget(self.spin_limit, 2, 1)

        self.chk_sched = QCheckBox(self.T("تشغيل التحميلات المجدولة يومياً الساعة:", "Run scheduled downloads daily at:"))
        self.chk_sched.setChecked(bool(engine.settings.get("schedEnabled", False)))
        gl.addWidget(self.chk_sched, 3, 0, 1, 2)

        self.time_edit = QTimeEdit()
        self.time_edit.setDisplayFormat("HH:mm")
        self.time_edit.setFixedWidth(105)
        self.time_edit.setLayoutDirection(Qt.LayoutDirection.LeftToRight)
        from PyQt6.QtCore import QTime

        hh, mm = (engine.settings.get("schedTime") or "02:00").split(":")[:2]
        self.time_edit.setTime(QTime(int(hh), int(mm)))
        self.time_edit.setEnabled(self.chk_sched.isChecked())
        self.chk_sched.toggled.connect(self.time_edit.setEnabled)
        gl.addWidget(self.time_edit, 3, 2)
        root.addWidget(cfg)

        # Queued / Scheduled items list
        qcard = QFrame()
        qcard.setObjectName("CardFrame")
        ql = QVBoxLayout(qcard)
        ql.setContentsMargins(16, 12, 16, 12)
        ql.setSpacing(8)
        ql.addWidget(QLabel(self.T("التحميلات في الطابور والجدولة:", "Queued & scheduled downloads:")))

        self.list_queue = QListWidget()
        self.list_queue.setStyleSheet(f"QListWidget {{ background: {p['surface3']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 4px; }}")
        ql.addWidget(self.list_queue, 1)

        qbtns = QHBoxLayout()
        self.btn_start_now = QPushButton(self.T("بدء المحدد الآن", "Start Selected Now"))
        self.btn_start_now.clicked.connect(self._start_selected_now)
        self.btn_queue_selected = QPushButton(self.T("تشغيل الكل في الطابور", "Start All Queued"))
        self.btn_queue_selected.clicked.connect(self._start_all_queued)
        qbtns.addWidget(self.btn_start_now)
        qbtns.addWidget(self.btn_queue_selected)
        qbtns.addStretch()
        ql.addLayout(qbtns)
        root.addWidget(qcard, 1)

        footer = QHBoxLayout()
        footer.addStretch()
        btn_cancel = QPushButton(self.T("إغلاق", "Close"))
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton(self.T("حفظ", "Save"))
        btn_save.setObjectName("PrimaryBtn")
        btn_save.setMinimumWidth(115)
        btn_save.clicked.connect(self._save)
        footer.addWidget(btn_cancel)
        footer.addWidget(btn_save)
        root.addLayout(footer)

        self._reload_queue()

    def _reload_queue(self):
        self.list_queue.clear()
        items = sorted(
            (it for it in self.engine.downloads.values() if it.get("status") in ("queued", "scheduled")),
            key=lambda x: int(x.get("createdAt") or 0),
        )
        if not items:
            li = QListWidgetItem(self.T("لا توجد تحميلات منتظرة في الطابور حالياً.", "No downloads waiting in queue or schedule."))
            li.setFlags(Qt.ItemFlag.NoItemFlags)
            self.list_queue.addItem(li)
            return
        for it in items:
            st = self.T("مجدول", "Scheduled") if it.get("status") == "scheduled" else self.T("في الطابور", "Queued")
            li = QListWidgetItem(f"[{st}]  {_bidi_filename(it.get('filename') or it.get('url') or '')}")
            li.setData(Qt.ItemDataRole.UserRole, it["id"])
            self.list_queue.addItem(li)

    def _start_selected_now(self):
        cur = self.list_queue.currentItem()
        dl_id = cur.data(Qt.ItemDataRole.UserRole) if cur else None
        if dl_id:
            self.engine.start_download(dl_id)
            self._reload_queue()

    def _start_all_queued(self):
        for it in list(self.engine.downloads.values()):
            if it.get("status") in ("queued", "scheduled"):
                self.engine.start_download(it["id"])
        self._reload_queue()

    def _save(self):
        s = self.engine.settings
        s["maxConcurrent"] = self.spin_conc.value()
        s["globalSpeedLimitKbps"] = self.spin_limit.value()
        s["schedEnabled"] = self.chk_sched.isChecked()
        new_t = self.time_edit.time().toString("HH:mm")
        if new_t != s.get("schedTime"):
            s["schedLastFired"] = ""
        s["schedTime"] = new_t
        self.engine.save_state()
        self.accept()
