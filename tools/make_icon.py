"""assets/icon.png + assets/icon.ico uretir (5 renkli perde + pena). Build sirasinda calisir."""
import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pygame  # noqa: E402
from PIL import Image  # noqa: E402

from gh.config import FRET_COLORS  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.path.join(ROOT, "assets")


def draw(size: int = 256) -> pygame.Surface:
    s = pygame.Surface((size, size), pygame.SRCALPHA)
    c = size / 2
    # pena (yuvarlatilmis ucgen)
    body = (20, 20, 28)
    pygame.draw.circle(s, body, (int(c), int(size * 0.40)), int(size * 0.38))
    pygame.draw.polygon(s, body, [(size * 0.16, size * 0.55), (size * 0.84, size * 0.55), (c, size * 0.97)])
    # 5 gem
    r = int(size * 0.075)
    for i, col in enumerate(FRET_COLORS):
        x = int(size * (0.22 + i * 0.14))
        y = int(size * 0.40 + abs(i - 2) * -size * 0.03)
        pygame.draw.circle(s, col, (x, y), r)
        pygame.draw.circle(s, (255, 255, 255), (x, y), r, max(2, size // 64))
    return s


def main() -> None:
    pygame.init()
    os.makedirs(ASSETS, exist_ok=True)
    png = os.path.join(ASSETS, "icon.png")
    pygame.image.save(draw(256), png)
    Image.open(png).save(os.path.join(ASSETS, "icon.ico"),
                         sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("icon ->", ASSETS)


if __name__ == "__main__":
    main()
