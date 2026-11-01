from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "assets"
BG = "#f4f3ef"
INK = "#182b36"
MUTED = "#52616a"
ACCENT = "#14685e"
LINE = "#d2d8d6"


def font(n, bold=False):
    return ImageFont.truetype(
        "/usr/share/fonts/noto-cjk/NotoSansCJK-" + ("Bold" if bold else "Regular") + ".ttc",
        n,
        index=2,
    )


def text(im, xy, s, n=32, color=INK, bold=False):
    draw = ImageDraw.Draw(im)
    max_width = im.width - xy[0] - (56 if im.width == 1080 else 160)
    while draw.textlength(s, font=font(n, bold)) > max_width and n > 20:
        n -= 1
    draw.text(xy, s, font=font(n, bold), fill=color)


def photo(im, name, box, crop=None):
    p = Image.open(ASSETS / (name + ".png")).convert("RGB")
    if crop:
        p = p.crop(crop)
    x, y, w, h = box
    p = ImageOps.contain(p, (w, h), Image.Resampling.LANCZOS)
    im.paste(p, (x + (w - p.width) // 2, y + (h - p.height) // 2))


def rule(im, y, w=968, x=56):
    ImageDraw.Draw(im).line((x, y, x + w, y), fill=LINE, width=2)
