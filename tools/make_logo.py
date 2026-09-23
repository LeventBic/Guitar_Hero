r"""Oyun logosu: kaynak gorselin (JPEG, koyu arka plan) arka planini parlakliga gore saydamlastirir, metal harflerin
koyu hatlarini opak doldurur, kirpar ve 1000 px genislige olcekler.

Kullanim: .venv\Scripts\python.exe tools\make_logo.py kaynak.jpg assets\logo.png [onizleme.png]
"""
import sys
import numpy as np, pygame
src_path, out_path = sys.argv[1:3]
prev_path = sys.argv[3] if len(sys.argv) > 3 else ""
pygame.init()
src = pygame.image.load(src_path)
rgb = pygame.surfarray.array3d(src).astype(np.float32)
bg = np.array([11., 12., 15.])
mx, mn = rgb.max(axis=2), rgb.min(axis=2)
a = np.clip((mx - 21) / 55.0, 0, 1) ** 0.8
sat = (mx - mn) / np.maximum(mx, 1)
metal = ((mx > 110) & (sat < 0.28)).astype(np.float32)
def shift8(m, op):
    out = m.copy()
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
        out = op(out, np.roll(np.roll(m, dx, 0), dy, 1))
    return out
def dil(m, r):
    for _ in range(r): m = shift8(m, np.maximum)
    return m
def ero(m, r):
    for _ in range(r): m = shift8(m, np.minimum)
    return m
def blur(m, r, n=3):
    for _ in range(n):
        acc = np.zeros_like(m)
        for d in range(-r, r + 1): acc += np.roll(m, d, 0)
        m = acc / (2 * r + 1); acc = np.zeros_like(m)
        for d in range(-r, r + 1): acc += np.roll(m, d, 1)
        m = acc / (2 * r + 1)
    return m
solid = blur(ero(dil(metal, 7), 3), 2) * 0.95           # harflerin ici + koyu dis hat, yumusak kenar
a2 = np.maximum(a, solid)
col = np.clip((rgb - bg * (1 - a[..., None])) / np.maximum(a[..., None], 1e-3), 0, 255)
w = np.clip((solid - a) / 0.3, 0, 1)[..., None]          # doldurulan yerde orijinal (koyu) renge gecis
col = col * (1 - w) + rgb * w
col = np.where(a2[..., None] < 0.004, 0.0, col)             # gorunmez piksellerde renk yok (toplamali cizim icin)
cols = (a2 > 0.35).sum(axis=1); rows = (a2 > 0.35).sum(axis=0)
xs, ys = np.nonzero(cols > 3)[0], np.nonzero(rows > 3)[0]
x0, x1 = max(0, xs.min() - 6), min(a.shape[0] - 1, xs.max() + 6)
y0, y1 = max(0, ys.min() - 6), min(a.shape[1] - 1, ys.max() + 6)
out = pygame.Surface((x1 - x0 + 1, y1 - y0 + 1), pygame.SRCALPHA)
pygame.surfarray.blit_array(out, col[x0:x1 + 1, y0:y1 + 1].astype(np.uint8))
pa = pygame.surfarray.pixels_alpha(out); pa[:] = (a2[x0:x1 + 1, y0:y1 + 1] * 255).astype(np.uint8); del pa
out = pygame.transform.smoothscale(out, (1000, int(out.get_height() * 1000 / out.get_width())))
pygame.image.save(out, out_path); print("logo", out.get_size())
if prev_path:                                            # sicak ve koyu zemin uzerinde onizleme
    p = pygame.Surface((out.get_width() * 2 + 60, out.get_height() + 40))
    p.fill((70, 40, 20))
    p.fill((12, 9, 8), (out.get_width() + 40, 0, out.get_width() + 20, p.get_height()))
    p.blit(out, (20, 20))
    p.blit(out, (out.get_width() + 40, 20))
    pygame.image.save(p, prev_path)
