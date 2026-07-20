"""Generate a simple SmartTradeAI app icon (.ico) using PIL."""
import os
from PIL import Image, ImageDraw, ImageFont

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "smarttradeai.ico")
BASE = 256

BG_TOP = (13, 20, 33)      # #0D1421 dark navy
BG_BOT = (23, 37, 60)      # #17253C
GREEN = (34, 197, 94)      # #22C55E
GREEN_HI = (74, 222, 128)  # #4ADE80
WHITE = (241, 245, 249)


def _rounded_bg(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # vertical gradient
    for y in range(size):
        t = y / size
        r = int(BG_TOP[0] + (BG_BOT[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOT[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOT[2] - BG_TOP[2]) * t)
        d.line([(0, y), (size, y)], fill=(r, g, b, 255))
    # rounded-rect mask
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle(
        [0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=255
    )
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(img, (0, 0), mask)
    return out


def _draw(size: int) -> Image.Image:
    img = _rounded_bg(size)
    d = ImageDraw.Draw(img)
    s = size / BASE  # scale factor

    # Upward trend line (chart)
    pts = [
        (0.16, 0.70), (0.34, 0.55), (0.46, 0.63),
        (0.62, 0.40), (0.78, 0.30),
    ]
    px = [(x * size, y * size) for x, y in pts]
    d.line(px, fill=GREEN, width=max(2, int(14 * s)), joint="curve")
    # node dots
    for x, y in px:
        r = max(2, int(9 * s))
        d.ellipse([x - r, y - r, x + r, y + r], fill=GREEN_HI)
    # arrow head at the last point
    ax, ay = px[-1]
    a = int(26 * s)
    d.polygon(
        [(ax + a, ay - a), (ax + a, ay + int(6 * s)), (ax - int(6 * s), ay - a)],
        fill=GREEN_HI,
    )

    # "ST" monogram bottom-left
    try:
        font = ImageFont.truetype("C:\\Windows\\Fonts\\segoeuib.ttf", int(78 * s))
    except Exception:
        font = ImageFont.load_default()
    d.text((int(24 * s), int(150 * s)), "ST", font=font, fill=WHITE)
    return img


def main():
    master = _draw(BASE)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icons = [master.resize(sz, Image.LANCZOS) for sz in sizes]
    icons[-1].save(OUT, format="ICO", sizes=sizes, append_images=icons[:-1])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
