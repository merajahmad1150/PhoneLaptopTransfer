"""
assets/make_logo.py
Generates the tool's logo (PNG + ICO + SVG) using only Pillow.
Run:  python assets/make_logo.py
Design: a rounded square with a purple -> blue -> teal gradient, a phone and
a laptop in white, and two coloured arrows between them (the two-way transfer).
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
STOPS = [(0.0, (124, 77, 255)), (0.5, (44, 140, 255)), (1.0, (28, 214, 180))]


def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def grad_color(t):
    for (t0, c0), (t1, c1) in zip(STOPS, STOPS[1:]):
        if t <= t1:
            return lerp(c0, c1, (t - t0) / (t1 - t0) if t1 > t0 else 0)
    return STOPS[-1][1]


def make(size=1024):
    S = size
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # diagonal gradient background
    bg = Image.new("RGBA", (S, S))
    px = bg.load()
    for y in range(S):
        for x in range(S):
            px[x, y] = grad_color((x + y) / (2 * S - 2)) + (255,)
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.22), fill=255)
    img.paste(bg, (0, 0), mask)

    d = ImageDraw.Draw(img)
    u = S / 100.0
    white = (255, 255, 255, 255)
    soft = (255, 255, 255, 70)

    # laptop (right/bottom): screen + base
    d.rounded_rectangle([40 * u, 40 * u, 84 * u, 66 * u], radius=3 * u, fill=white)
    d.rounded_rectangle([43 * u, 43 * u, 81 * u, 63 * u], radius=2 * u, fill=(40, 60, 140, 255))
    d.rounded_rectangle([34 * u, 67 * u, 90 * u, 72 * u], radius=2.5 * u, fill=white)
    # phone (left/top)
    d.rounded_rectangle([14 * u, 22 * u, 36 * u, 62 * u], radius=4 * u, fill=white)
    d.rounded_rectangle([16.5 * u, 27 * u, 33.5 * u, 56 * u], radius=2 * u, fill=(40, 60, 140, 255))
    d.ellipse([23.2 * u, 57.4 * u, 26.8 * u, 61 * u], fill=(190, 200, 235, 255))
    # transfer arrows (orange up-right, yellow down-left) over the screens
    def arrow(x0, y0, x1, y1, color):
        d.line([x0 * u, y0 * u, x1 * u, y1 * u], fill=color, width=int(4.2 * u))
        import math
        ang = math.atan2(y1 - y0, x1 - x0)
        L = 9
        for da in (2.55, -2.55):
            xa = x1 + L * math.cos(ang + da)
            ya = y1 + L * math.sin(ang + da)
            d.line([x1 * u, y1 * u, xa * u, ya * u], fill=color, width=int(4.2 * u))
        d.ellipse([(x1 - 2.1) * u, (y1 - 2.1) * u, (x1 + 2.1) * u, (y1 + 2.1) * u], fill=color)
    arrow(38, 34, 64, 20, (255, 196, 61, 255))     # phone -> laptop
    arrow(62, 82, 30, 82, (255, 120, 90, 255))     # laptop -> phone
    return img


def main():
    big = make(1024)
    big512 = big.resize((512, 512), Image.LANCZOS)
    big512.save(HERE / "logo.png")
    big.resize((256, 256), Image.LANCZOS).save(HERE / "logo_256.png")
    big.resize((64, 64), Image.LANCZOS).save(HERE / "logo_64.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    big.resize((256, 256), Image.LANCZOS).save(HERE / "logo.ico", sizes=sizes)
    # web copies
    static = ROOT / "web" / "static"
    static.mkdir(parents=True, exist_ok=True)
    big.resize((192, 192), Image.LANCZOS).save(static / "logo.png")
    big.resize((180, 180), Image.LANCZOS).save(static / "apple-touch-icon.png")
    big.resize((256, 256), Image.LANCZOS).save(static / "favicon.ico", sizes=sizes)
    (static / "logo.svg").write_text(SVG, encoding="utf-8")
    print("Logo files written to", HERE, "and", static)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100" width="128" height="128">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
<stop offset="0" stop-color="#7c4dff"/><stop offset="0.5" stop-color="#2c8cff"/><stop offset="1" stop-color="#1cd6b4"/>
</linearGradient></defs>
<rect width="100" height="100" rx="22" fill="url(#g)"/>
<rect x="40" y="40" width="44" height="26" rx="3" fill="#fff"/><rect x="43" y="43" width="38" height="20" rx="2" fill="#283c8c"/>
<rect x="34" y="67" width="56" height="5" rx="2.5" fill="#fff"/>
<rect x="14" y="22" width="22" height="40" rx="4" fill="#fff"/><rect x="16.5" y="27" width="17" height="29" rx="2" fill="#283c8c"/>
<circle cx="25" cy="59.2" r="1.8" fill="#bec8eb"/>
<path d="M38 34 L64 20 M64 20 L55.5 21.5 M64 20 L59 27" stroke="#ffc43d" stroke-width="4.2" stroke-linecap="round" fill="none"/>
<path d="M62 82 L30 82 M30 82 L38 77.5 M30 82 L38 86.5" stroke="#ff785a" stroke-width="4.2" stroke-linecap="round" fill="none"/>
</svg>
"""

if __name__ == "__main__":
    main()
