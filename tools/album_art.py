"""Procedural 512x512 album covers drawn with pygame (headless).

The drawing code lives in gh/album_art.py (shared with the in-game song importer, so the exe has it);
this module keeps the old tools API: draw_album(path, title, artist, style, seed).
"""
from __future__ import annotations

import os
import sys

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from gh.album_art import SIZE, draw_album, draw_cover  # noqa: E402,F401
