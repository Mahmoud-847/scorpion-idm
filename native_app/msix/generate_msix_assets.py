# -*- coding: utf-8 -*-
"""Generate Microsoft Store MSIX visual assets from build/scorpion_logo.svg."""
import os
import sys
from pathlib import Path

os.environ.pop("QT_QPA_PLATFORM", None)

from PyQt6.QtCore import QRectF, Qt
from PyQt6.QtGui import QColor, QFont, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PyQt6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[2]
SVG_PATH = ROOT / "build" / "scorpion_logo.svg"


def _render_square_icon(renderer: QSvgRenderer, size: int, out_path: Path, plated: bool = True) -> None:
    img = QImage(size, size, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    if plated:
        bg = QLinearGradient(0, 0, size, size)
        bg.setColorAt(0.0, QColor("#181820"))
        bg.setColorAt(1.0, QColor("#0D0D11"))
        p.fillRect(0, 0, size, size, bg)
        glow = QRadialGradient(size * 0.5, size * 0.48, size * 0.46)
        glow.setColorAt(0.0, QColor(255, 149, 0, 52))
        glow.setColorAt(0.65, QColor(255, 90, 0, 14))
        glow.setColorAt(1.0, QColor(255, 90, 0, 0))
        p.fillRect(0, 0, size, size, glow)
        pad = size * 0.16
    else:
        pad = size * 0.08
    renderer.render(p, QRectF(pad, pad, size - 2 * pad, size - 2 * pad))
    p.end()
    img.save(str(out_path), "PNG")


def _render_wide_tile(renderer: QSvgRenderer, width: int, height: int, out_path: Path) -> None:
    img = QImage(width, height, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

    bg = QLinearGradient(0, 0, width, height)
    bg.setColorAt(0.0, QColor("#181820"))
    bg.setColorAt(1.0, QColor("#0D0D11"))
    p.fillRect(0, 0, width, height, bg)

    glow = QRadialGradient(width * 0.25, height * 0.5, height * 0.68)
    glow.setColorAt(0.0, QColor(255, 149, 0, 62))
    glow.setColorAt(0.65, QColor(255, 90, 0, 16))
    glow.setColorAt(1.0, QColor(255, 90, 0, 0))
    p.fillRect(0, 0, width, height, glow)

    scale = width / 310.0
    logo_sz = 84.0 * scale
    logo_x = 24.0 * scale
    logo_y = (height - logo_sz) * 0.5
    renderer.render(p, QRectF(logo_x, logo_y, logo_sz, logo_sz))

    f_title = QFont("Segoe UI")
    f_title.setPixelSize(int(round(20.0 * scale)))
    f_title.setWeight(QFont.Weight.Bold)
    p.setFont(f_title)
    p.setPen(QColor("#F3F3F7"))
    tx = 122.0 * scale
    p.drawText(QRectF(tx, 34.0 * scale, width - tx - 14.0 * scale, 34.0 * scale), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "Scorpion IDM")

    f_sub = QFont("Segoe UI")
    f_sub.setPixelSize(int(round(11.5 * scale)))
    f_sub.setWeight(QFont.Weight.Medium)
    p.setFont(f_sub)
    p.setPen(QColor("#FF9500"))
    p.drawText(
        QRectF(tx, 70.0 * scale, width - tx - 14.0 * scale, 46.0 * scale),
        Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop | Qt.TextFlag.TextWordWrap,
        "Download Manager, Media & Torrents",
    )

    p.end()
    img.save(str(out_path), "PNG")


def generate_assets(out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    _ = app
    renderer = QSvgRenderer(str(SVG_PATH))
    if not renderer.isValid():
        raise RuntimeError(f"Invalid logo SVG: {SVG_PATH}")

    _render_square_icon(renderer, 50, out_dir / "StoreLogo.png", plated=True)
    _render_square_icon(renderer, 100, out_dir / "StoreLogo.scale-200.png", plated=True)
    _render_square_icon(renderer, 44, out_dir / "Square44x44Logo.png", plated=True)
    _render_square_icon(renderer, 88, out_dir / "Square44x44Logo.scale-200.png", plated=True)
    _render_square_icon(renderer, 24, out_dir / "Square44x44Logo.targetsize-24_altform-unplated.png", plated=False)
    _render_square_icon(renderer, 48, out_dir / "Square44x44Logo.targetsize-48_altform-unplated.png", plated=False)
    _render_square_icon(renderer, 256, out_dir / "Square44x44Logo.targetsize-256_altform-unplated.png", plated=False)
    _render_square_icon(renderer, 150, out_dir / "Square150x150Logo.png", plated=True)
    _render_square_icon(renderer, 300, out_dir / "Square150x150Logo.scale-200.png", plated=True)
    _render_wide_tile(renderer, 310, 150, out_dir / "Wide310x150Logo.png")
    _render_wide_tile(renderer, 620, 300, out_dir / "Wide310x150Logo.scale-200.png")


if __name__ == "__main__":
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else (ROOT / "native_app" / "_build" / "msix" / "Assets")
    generate_assets(dest)
    print(f"Generated MSIX assets in {dest}")
