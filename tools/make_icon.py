"""assets/icon.png + icon_small.png + icon.ico uretir: oyun logosundan (assets/logo.png). Build sirasinda calisir.

- 64-256 px (masaustu / klasor): logonun tamami; alevlerin disa tasan kenarlari kirpilir, "GUITAR HERO" + gitar kareye
  sigdirilir (ust / alt saydam).
- 16-48 px (gorev cubugu / listeler): genis yazi okunmadigindan logodan kesilen "G" + "H" harfleri (alevler ayiklanir),
  koyu yuvarlatilmis karo uzerinde turuncu cerceve ve parilti.
logo.png yoksa eski cizili simge (pena + 5 perde) uretilir.
"""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np  # noqa: E402
import pygame  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from gh.config import FRET_COLORS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")
SIZES = [16, 24, 32, 48, 64, 128, 256]
CROP = (0.07, 0.10, 0.93, 0.88)      # logo icinde kullanilan bolge (x0, y0, x1, y1 orani): yazi + gitar
SMALL = 48                           # bu boyut ve altinda monogram
G_BOX = (0.095, 0.336, 0.212, 0.789)  # 1000x640 logoda "G" ve "H" harflerinin kutulari (oran)
H_BOX = (0.553, 0.341, 0.662, 0.738)


def from_logo(path: str) -> Image.Image | None:
    if not os.path.isfile(path):
        return None
    logo = Image.open(path).convert("RGBA")
    w, h = logo.size
    box = (int(CROP[0] * w), int(CROP[1] * h), int(CROP[2] * w), int(CROP[3] * h))
    part = logo.crop(box)
    side = max(part.size)
    square = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    square.paste(part, ((side - part.width) // 2, (side - part.height) // 2), part)
    return square


def _letter(logo: Image.Image, box) -> Image.Image:
    """Logodan harf kesiti: yalniz gumus govde + siyah dis hat (doygun turuncu alevler ayiklanir)."""
    w, h = logo.size
    part = logo.crop((int(box[0] * w), int(box[1] * h), int(box[2] * w), int(box[3] * h)))
    a = np.asarray(part).astype(np.float32)
    mx, mn = a[..., :3].max(-1), a[..., :3].min(-1)
    sat = (mx - mn) / np.maximum(mx, 1)
    keep = ((sat < 0.30) | (mx < 45)) & (a[..., 3] > 200)
    mask = Image.fromarray((keep * 255).astype(np.uint8)).filter(ImageFilter.MedianFilter(5))
    part.putalpha(mask.filter(ImageFilter.GaussianBlur(1.2)))
    return part


def monogram(path: str, n: int = 512) -> Image.Image | None:
    if not os.path.isfile(path):
        return None
    logo = Image.open(path).convert("RGBA")
    g, hh = _letter(logo, G_BOX), _letter(logo, H_BOX)
    t = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    outer = Image.new("L", (n, n), 0)
    ImageDraw.Draw(outer).rounded_rectangle((0, 0, n - 1, n - 1), radius=n // 6, fill=255)
    grad = Image.new("RGBA", (n, n))
    d = ImageDraw.Draw(grad)
    for y in range(n):                                   # turuncu cerceve: ustte acik, altta koyu
        k = y / n
        d.line([(0, y), (n, y)], fill=(int(210 - 60 * k), int(70 - 30 * k), 10, 255))
    t.paste(grad, (0, 0), outer)
    inner = Image.new("L", (n, n), 0)
    e = n // 22
    ImageDraw.Draw(inner).rounded_rectangle((e, e, n - 1 - e, n - 1 - e), radius=n // 7, fill=255)
    t.paste(Image.new("RGBA", (n, n), (22, 14, 10, 255)), (0, 0), inner)
    h = int(n * 0.74)
    g = g.resize((int(g.width * h / g.height), h), Image.LANCZOS)
    hh = hh.resize((int(hh.width * h * 0.9 / hh.height), int(h * 0.9)), Image.LANCZOS)
    gap = -int(n * 0.02)
    x0, y0 = (n - (g.width + hh.width + gap)) // 2, (n - h) // 2
    let = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    let.paste(g, (x0, y0), g)
    let.paste(hh, (x0 + g.width + gap, y0 + int(h * 0.03)), hh)
    halo = Image.new("RGBA", (n, n), (255, 110, 20, 0))
    halo.putalpha(let.split()[3].filter(ImageFilter.GaussianBlur(n // 30)).point(lambda v: min(255, int(v * 1.6))))
    t.alpha_composite(halo)
    t.alpha_composite(let)
    return t


def draw_fallback(size: int = 256) -> Image.Image:
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    body = (20, 20, 28)
    pygame.draw.circle(s, body, (int(c), int(size * 0.40)), int(size * 0.38))
    pygame.draw.polygon(s, body, [(size * 0.16, size * 0.55), (size * 0.84, size * 0.55), (c, size * 0.97)])
    r = int(size * 0.075)
    for i, col in enumerate(FRET_COLORS):
        x = int(size * (0.22 + i * 0.14))
        y = int(size * 0.40 + abs(i - 2) * -size * 0.03)
        pygame.draw.circle(s, col, (x, y), r)
        pygame.draw.circle(s, (255, 255, 255), (x, y), r, max(2, size // 64))
    return Image.frombytes("RGBA", (size, size), pygame.image.tobytes(s, "RGBA"))


def main() -> None:
    pygame.init()
    os.makedirs(ASSETS, exist_ok=True)
    logo = os.path.join(ASSETS, "logo.png")
    big = from_logo(logo) or draw_fallback(512)
    small = monogram(logo) or big
    frames = [(small if n <= SMALL else big).resize((n, n), Image.LANCZOS) for n in SIZES]
    frames[-1].save(os.path.join(ASSETS, "icon.png"))
    small.resize((64, 64), Image.LANCZOS).save(os.path.join(ASSETS, "icon_small.png"))   # pencere / gorev cubugu
    frames[-1].save(os.path.join(ASSETS, "icon.ico"), sizes=[(n, n) for n in SIZES], append_images=frames[:-1])
    print("icon ->", ASSETS)


if __name__ == "__main__":
    main()
