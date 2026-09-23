"""Sahne temel sinifi. App bir sahne yigini tutar; ustteki sahne girdileri alir, opak olmayan sahneler
altlarindaki sahnenin uzerine cizilir (duraklatma menusu, zorluk secimi)."""
from __future__ import annotations

import pygame


class Scene:
    opaque = True          # False: alttaki sahne once cizilir
    capture_keys = False   # True: yalnizca ham KEYDOWN olaylari (tus atama)
    blocks_import = False  # True: birakilan dosyalar bu sahne kapanana kadar bekletilir (oyun, kalibrasyon)

    def __init__(self, app):
        self.app = app
        self.t = 0.0

    # yasam dongusu
    def enter(self) -> None: ...
    def exit(self) -> None: ...
    def resume(self) -> None: ...     # ustteki sahne kapaninca

    # girdi
    def on_menu(self, action: str) -> None: ...
    def on_game(self, gi) -> None: ...
    def on_key(self, ev: pygame.event.Event) -> None: ...
    def on_shortcut(self, key: int) -> None: ...      # menu eylemi olmayan tuslar (capture_keys=False iken)

    # dongu
    def update(self, dt: float) -> None:
        self.t += dt

    def draw(self, surf: pygame.Surface) -> None: ...

    # kisayollar
    @property
    def assets(self):
        return self.app.assets

    def sfx(self, name: str, vol: float = 1.0) -> None:
        self.app.audio.play_sfx(name, vol)
