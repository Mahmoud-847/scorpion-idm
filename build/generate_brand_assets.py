"""Generates Scorpion IDM Golden-Scorpion PNGs, multi-size ICO, and extension icons using PyQt6."""
import os
import shutil
import struct
import sys

from PyQt6.QtCore import Qt, QRectF
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer


ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUILD_DIR = os.path.join(ROOT, "build")
BUILD_ICONS_DIR = os.path.join(BUILD_DIR, "icons")
EXT_DIR = os.path.join(ROOT, "browser-extension")
EXT_ICONS_DIR = os.path.join(EXT_DIR, "icons")

MASTER_SVG = os.path.join(BUILD_DIR, "scorpion_logo.svg")
TRAY_SVG = os.path.join(BUILD_DIR, "scorpion_tray.svg")


def render_svg_png(svg_path: str, out_path: str, size: int) -> bytes:
    """Renders SVG cleanly with 4x supersampling on transparent ARGB32 canvas."""
    renderer = QSvgRenderer(svg_path)
    if not renderer.isValid():
        raise RuntimeError(f"Invalid SVG: {svg_path}")
    hi = max(128, size * 4)
    img_hi = QImage(hi, hi, QImage.Format.Format_ARGB32_Premultiplied)
    img_hi.fill(Qt.GlobalColor.transparent)
    p = QPainter(img_hi)
    p.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
    pad = hi * 0.04
    renderer.render(p, QRectF(pad, pad, hi - 2 * pad, hi - 2 * pad))
    p.end()

    final = (
        img_hi
        if hi == size
        else img_hi.scaled(
            size,
            size,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    )
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    if not final.save(out_path, "PNG"):
        raise RuntimeError(f"Failed saving PNG: {out_path}")
    with open(out_path, "rb") as f:
        return f.read()


def write_multi_ico(entries: list[tuple[int, bytes]], ico_path: str) -> None:
    """Packs multiple PNG-encoded icon sizes into a standard Windows .ico file."""
    count = len(entries)
    header = struct.pack("<HHH", 0, 1, count)
    offset = 6 + 16 * count
    dir_bytes = bytearray()
    payload = bytearray()
    for sz, png_bytes in entries:
        dim = 0 if sz >= 256 else sz
        dir_bytes.extend(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png_bytes), offset))
        payload.extend(png_bytes)
        offset += len(png_bytes)
    with open(ico_path, "wb") as f:
        f.write(header)
        f.write(dir_bytes)
        f.write(payload)


def main() -> int:
    _app = QGuiApplication(sys.argv)
    os.makedirs(BUILD_ICONS_DIR, exist_ok=True)
    os.makedirs(EXT_ICONS_DIR, exist_ok=True)

    ico_entries = []
    for sz in (16, 24, 32, 48, 64, 128, 256, 512):
        src_svg = TRAY_SVG if sz <= 24 else MASTER_SVG
        out_png = os.path.join(BUILD_ICONS_DIR, f"icon-{sz}.png")
        png_bytes = render_svg_png(src_svg, out_png, sz)
        if sz <= 256:
            ico_entries.append((sz, png_bytes))

    # Top-level app icon & tray PNGs
    shutil.copy2(os.path.join(BUILD_ICONS_DIR, "icon-256.png"), os.path.join(BUILD_DIR, "icon.png"))
    render_svg_png(TRAY_SVG, os.path.join(BUILD_DIR, "tray.png"), 64)
    write_multi_ico(ico_entries, os.path.join(BUILD_DIR, "icon.ico"))

    # Extension brand assets
    shutil.copy2(MASTER_SVG, os.path.join(EXT_DIR, "scorpion-logo.svg"))
    shutil.copy2(os.path.join(BUILD_ICONS_DIR, "icon-128.png"), os.path.join(EXT_DIR, "icon.png"))
    for sz in (16, 32, 48, 128):
        shutil.copy2(
            os.path.join(BUILD_ICONS_DIR, f"icon-{sz}.png"),
            os.path.join(EXT_ICONS_DIR, f"icon-{sz}.png"),
        )
    print(f"Generated {len(ico_entries)} ICO sizes and extension icons cleanly.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
