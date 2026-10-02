"""Generate the live-interpreter launcher icon (assets/app.ico + assets/app.png).

Pure-Pillow, no network and no external assets: the mark is drawn from
scratch at 4x supersampling so it stays crisp from 16 px up to 256 px.

Run from the project root:

    .venv\\Scripts\\python.exe tools\\make_icon.py
"""

from __future__ import annotations

import os

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")

# palette: deep violet tile, cream/gold mark (matches docs/mascot.png)
TOP = (128, 104, 248)
BOTTOM = (72, 58, 176)
GOLD = (255, 214, 138)
WHITE = (255, 255, 255)

SS = 4  # supersampling factor
ICO_SIZES = [16, 24, 32, 48, 64, 128, 256]

FONT_CANDIDATES = (
    r"C:\Windows\Fonts\msyhbd.ttc",
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
)


def load_font(px: int) -> ImageFont.FreeTypeFont | None:
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, px)
            except OSError:
                continue
    return None


def gradient_tile(size: int) -> Image.Image:
    """Rounded-square tile with a soft vertical gradient, glow and rim light."""
    s = size * SS
    t = np.linspace(0.0, 1.0, s, dtype=np.float32)[:, None]
    base = np.empty((s, s, 3), dtype=np.float32)
    for i in range(3):
        base[:, :, i] = (TOP[i] + (BOTTOM[i] - TOP[i]) * t) / 255.0

    yy, xx = np.mgrid[0:s, 0:s].astype(np.float32)
    # soft glow drifting in from the top-left corner
    d = np.sqrt(((xx - s * 0.28) / (s * 0.72)) ** 2 + ((yy - s * 0.10) / (s * 0.62)) ** 2)
    glow = np.clip(1.0 - d, 0.0, 1.0) ** 2 * 0.30
    # gentle bottom vignette so the tile does not look flat
    vig = np.clip((yy / s - 0.55) / 0.45, 0.0, 1.0) ** 2 * 0.16
    base = base * (1.0 - vig[..., None]) + np.array(BOTTOM, dtype=np.float32) / 255.0 * vig[..., None]
    base = base * (1.0 - glow[..., None]) + glow[..., None]

    arr = (np.clip(base, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    img = Image.fromarray(arr, "RGB").convert("RGBA")

    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * 0.225), fill=255)
    img.putalpha(mask)

    # inner rim light
    rim = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rim)
    inset = int(s * 0.008)
    rd.rounded_rectangle(
        (inset, inset, s - 1 - inset, s - 1 - inset),
        radius=int(s * 0.215),
        outline=(255, 255, 255, 46),
        width=max(2, int(s * 0.009)),
    )
    img = Image.alpha_composite(img, rim)
    return img.resize((size, size), Image.LANCZOS)


def _round_cap(d: ImageDraw.ImageDraw, xy, r: float, fill) -> None:
    x, y = xy
    d.ellipse((x - r, y - r, x + r, y + r), fill=fill)


def render(size: int) -> Image.Image:
    """Draw the launcher mark at one exact pixel size."""
    s = size * SS
    img = gradient_tile(size).resize((s, s), Image.LANCZOS)
    d = ImageDraw.Draw(img)

    # tiny sizes lose the fine detail, so draw a slightly bolder, simplified mark
    simple = size < 48
    cx, cy = s * 0.5, s * 0.505
    R = s * (0.315 if simple else 0.30)   # headband radius
    W = s * (0.092 if simple else 0.075)  # stroke width
    cup_w, cup_h = s * (0.135 if simple else 0.115), s * 0.275
    cup_r = cup_w * 0.52

    band = WHITE
    # headband: upper half circle, then round the two ends
    d.arc((cx - R, cy - R, cx + R, cy + R), 180, 360, fill=band, width=int(W))
    _round_cap(d, (cx - R, cy), W / 2, band)
    _round_cap(d, (cx + R, cy), W / 2, band)

    # ear cups (slightly elongated, aligned under the band ends)
    for sign in (-1, 1):
        x = cx + sign * R
        d.rounded_rectangle(
            (x - cup_w / 2, cy - cup_h * 0.12, x + cup_w / 2, cy + cup_h * 0.88),
            radius=cup_r,
            fill=band,
        )
        if not simple:
            # inner shade so the cup reads as a cushion, not a blob
            pad = cup_w * 0.30
            d.rounded_rectangle(
                (x - cup_w / 2 + pad, cy - cup_h * 0.12 + pad * 1.15,
                 x + cup_w / 2 - pad, cy + cup_h * 0.88 - pad * 1.15),
                radius=cup_r * 0.6,
                fill=(126, 108, 230),
            )

    # centre glyph
    font = load_font(int(s * (0.315 if simple else 0.300)))
    if font is not None:
        d.text((cx, cy + s * 0.004), "译", font=font, fill=GOLD, anchor="mm")
    else:
        d.polygon(
            [(cx, cy - s * 0.13), (cx + s * 0.13, cy), (cx, cy + s * 0.13), (cx - s * 0.13, cy)],
            fill=GOLD,
        )

    return img.resize((size, size), Image.LANCZOS)


def main() -> None:
    os.makedirs(ASSETS, exist_ok=True)
    master = render(1024)
    png_path = os.path.join(ASSETS, "app.png")
    master.resize((512, 512), Image.LANCZOS).save(png_path)

    ico_path = os.path.join(ASSETS, "app.ico")
    frames = [render(n) for n in ICO_SIZES]
    frames[-1].save(ico_path, format="ICO", sizes=[(n, n) for n in ICO_SIZES],
                    append_images=frames[:-1])
    print("wrote", png_path)
    print("wrote", ico_path)


if __name__ == "__main__":
    main()

