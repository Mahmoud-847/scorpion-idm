import os
from PIL import Image, ImageDraw, ImageFilter

def create_scorpion_icon(base_dir):
    os.makedirs(base_dir, exist_ok=True)
    size = 512
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Rounded dark obsidian background with glowing border
    margin = 24
    draw.rounded_rectangle(
        [margin, margin, size - margin, size - margin],
        radius=110,
        fill=(13, 17, 26, 255),
        outline=(245, 158, 11, 255),
        width=10
    )

    # Subtle inner hexagonal/shield glow
    inner_margin = 44
    draw.rounded_rectangle(
        [inner_margin, inner_margin, size - inner_margin, size - inner_margin],
        radius=90,
        fill=(18, 24, 38, 255),
        outline=(6, 182, 212, 110),
        width=4
    )

    # Draw stylized Scorpion Tail + Stinger curving into a sharp Download Arrow
    # Tail segments (curving from bottom-left up to top-right and striking down-center)
    tail_segments = [
        [(135, 340), (110, 275), (150, 245), (175, 305)],
        [(118, 262), (125, 190), (175, 185), (165, 248)],
        [(135, 178), (185, 120), (230, 145), (185, 190)],
        [(198, 115), (275, 92), (292, 138), (232, 150)],
        [(288, 95), (365, 118), (345, 162), (288, 142)],
    ]
    for seg in tail_segments:
        draw.polygon(seg, fill=(245, 158, 11, 255), outline=(254, 243, 199, 200))

    # Scorpion Pincers (left & right lower claws)
    left_claw = [(140, 365), (95, 330), (88, 375), (125, 405), (175, 395)]
    right_claw = [(372, 365), (417, 330), (424, 375), (387, 405), (337, 395)]
    draw.polygon(left_claw, fill=(217, 119, 6, 255), outline=(251, 191, 36, 220))
    draw.polygon(right_claw, fill=(217, 119, 6, 255), outline=(251, 191, 36, 220))

    # Central High-Speed Download Arrow (Cyan-to-Amber Stinger Strike)
    arrow_shaft = [
        (226, 165),
        (286, 165),
        (286, 295),
        (356, 295),
        (256, 405),
        (156, 295),
        (226, 295),
    ]
    # Glow behind arrow
    glow_layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.polygon(arrow_shaft, fill=(6, 182, 212, 180))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(18))
    img = Image.alpha_composite(img, glow_layer)
    draw = ImageDraw.Draw(img)

    # Crisp arrow foreground
    draw.polygon(arrow_shaft, fill=(6, 182, 212, 255), outline=(165, 243, 252, 255))

    # Bottom speed base bar (Segmented like IDM chunks!)
    bar_y1, bar_y2 = 425, 445
    chunk_colors = [
        (245, 158, 11, 255),
        (251, 191, 36, 255),
        (6, 182, 212, 255),
        (34, 211, 238, 255),
        (16, 185, 129, 255),
    ]
    start_x = 126
    chunk_w = 46
    gap = 8
    for i, col in enumerate(chunk_colors):
        x1 = start_x + i * (chunk_w + gap)
        draw.rounded_rectangle([x1, bar_y1, x1 + chunk_w, bar_y2], radius=6, fill=col)

    png_path = os.path.join(base_dir, "icon.png")
    ico_path = os.path.join(base_dir, "icon.ico")
    tray_path = os.path.join(base_dir, "tray.png")

    img.save(png_path, format="PNG")
    img.resize((64, 64), Image.Resampling.LANCZOS).save(tray_path, format="PNG")
    img.save(
        ico_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    )
    print(f"Icons generated successfully in {base_dir}")

if __name__ == "__main__":
    create_scorpion_icon(r"C:\Users\Mahmoud.emad\.gemini\antigravity\scratch\scorpion-idm\build")
    create_scorpion_icon(r"C:\Users\Mahmoud.emad\.gemini\antigravity\scratch\scorpion-idm\public")
