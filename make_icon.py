"""
Regenerates bw.ico — the app/exe/shortcut icon.

Run once whenever you want to tweak the icon:  python make_icon.py
Requires Pillow (pip install pillow). The committed bw.ico is the output of
this script, so end users never need to run it.
"""

from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "bw.ico"

# Palette mirrors the app (see bandwidth_report_manager.py).
BG_TOP = (17, 24, 39)       # #111827 raised card
BG_BOT = (11, 17, 32)       # #0B1120 main background
BORDER = (37, 99, 235)      # #2563EB accent
BARS = [
    (59, 130, 246),         # #3B82F6 light
    (37, 99, 235),          # #2563EB
    (29, 78, 216),          # #1D4ED8
    (96, 165, 250),         # #60A5FA lightest (tallest bar)
]

S = 256                     # master render size (downsampled for the .ico)


def rounded(draw, box, radius, fill):
    draw.rounded_rectangle(box, radius=radius, fill=fill)


def render(size: int = S) -> Image.Image:
    scale = size / S
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    pad = int(10 * scale)
    radius = int(52 * scale)

    # Vertical-ish background: paint bottom colour then a slightly lighter
    # top band so the tile has a little depth without a full gradient lib.
    rounded(d, (pad, pad, size - pad, size - pad), radius, BG_BOT)
    rounded(d, (pad, pad, size - pad, int(size * 0.55)), radius, BG_TOP)
    rounded(d, (pad, int(size * 0.35), size - pad, size - pad), radius, BG_BOT)

    # Accent border.
    d.rounded_rectangle(
        (pad, pad, size - pad, size - pad),
        radius=radius,
        outline=BORDER,
        width=max(1, int(6 * scale)),
    )

    # Four ascending signal bars (the "bandwidth" motif).
    n = len(BARS)
    left = int(58 * scale)
    right = int(size - 58 * scale)
    baseline = int(size - 66 * scale)
    top_min = int(60 * scale)
    gap = int(12 * scale)
    bar_w = (right - left - gap * (n - 1)) / n
    bar_r = max(1, int(bar_w * 0.30))

    for i, colour in enumerate(BARS):
        x0 = left + i * (bar_w + gap)
        x1 = x0 + bar_w
        height_frac = (i + 1) / n
        y0 = baseline - int((baseline - top_min) * height_frac)
        d.rounded_rectangle((x0, y0, x1, baseline), radius=bar_r, fill=colour)

    return img


def main():
    master = render(S)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [master.resize((s, s), Image.LANCZOS) for s in sizes]
    master.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    # Pillow embeds all sizes from the master when given `sizes`; the explicit
    # frames above are kept for clarity/debugging if a PNG export is wanted.
    print(f"Wrote {OUT}  ({', '.join(f'{s}x{s}' for s in sizes)})")


if __name__ == "__main__":
    main()
