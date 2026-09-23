"""Clone Hero .sng paketi okuma / acma ve song.ini zengin metin etiketleri."""
from __future__ import annotations

import os
import struct

from gh.chart import load_song
from gh.chart.sng import extract_sng, read_sng
from gh.chart.song_ini import strip_rich_text

CHART = """[Song]
{
  Resolution = 192
  MusicStream = "song.ogg"
}
[SyncTrack]
{
  0 = TS 4
  0 = B 120000
}
[ExpertSingle]
{
  768 = N 0 0
  960 = N 1 0
  1152 = N 2 0
}
"""


def make_sng(meta: dict[str, str], files: dict[str, bytes], mask: bytes = bytes(range(7, 23))) -> bytes:
    md = b"".join(struct.pack("<i", len(k.encode())) + k.encode() + struct.pack("<i", len(v.encode())) + v.encode()
                  for k, v in meta.items())
    meta_sec = struct.pack("<Q", len(md) + 8) + struct.pack("<Q", len(meta)) + md
    names = list(files)
    idx_len = 8 + sum(1 + len(n.encode()) + 16 for n in names)
    head = b"SNGPKG" + struct.pack("<I", 1) + mask
    data_start = len(head) + len(meta_sec) + 8 + idx_len + 8
    idx, blob, off = b"", b"", data_start
    for n in names:
        raw = files[n]
        masked = bytes(b ^ (mask[i % 16] ^ (i & 0xFF)) for i, b in enumerate(raw))
        idx += bytes([len(n.encode())]) + n.encode() + struct.pack("<QQ", len(raw), off)
        blob += masked
        off += len(raw)
    return head + meta_sec + struct.pack("<Q", idx_len) + struct.pack("<Q", len(names)) + idx + \
        struct.pack("<Q", len(blob)) + blob


def test_read_and_extract_sng(tmp_path):
    audio = bytes(range(256)) * 3
    pkg = make_sng({"name": "Test Song", "artist": "Band", "charter": "<b><color=#FF0000>Me</color></b>"},
                   {"notes.chart": CHART.encode(), "song.ogg": audio})
    p = tmp_path / "x.sng"
    p.write_bytes(pkg)
    meta, files = read_sng(str(p))
    assert meta["name"] == "Test Song" and files["song.ogg"] == audio and files["notes.chart"] == CHART.encode()
    dest = extract_sng(str(p), str(tmp_path / "Band - Test Song"))
    assert set(os.listdir(dest)) == {"notes.chart", "song.ogg", "song.ini"}
    song = load_song(dest)
    assert (song.info.name, song.info.artist, song.info.charter) == ("Test Song", "Band", "Me")
    assert len(song.tracks["expert"].notes) == 3


def test_strip_rich_text():
    assert strip_rich_text("<b><i><color=#0091FF>D</color><color=#00ABFF>e</color>lta</i></b>") == "Delta"
    assert strip_rich_text("a<br>b") == "a b"
    assert strip_rich_text("Rock & <Roll>") == "Rock & <Roll>"          # etiket olmayan acili metin korunur
    assert strip_rich_text("<size=20>Big</size>") == "Big"


def test_fill_missing_difficulties_from_hand_expert():
    """Demo sarkinin el yapimi chart'indan yalniz Expert birakilir; eksikler Expert notalarindan uretilir."""
    import glob
    import re

    from gh.autochart.charter import validate
    from gh.autochart.fill import fill_missing_difficulties
    from gh.chart import parse_chart
    src = sorted(glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "Songs",
                                        "RIFF Demo Band - *", "notes.chart")))[0]
    text = open(src, encoding="utf-8").read()
    only_expert = re.sub(r"\[(Hard|Medium|Easy)Single\]\s*\{.*?\n\}\s*", "", text, flags=re.S)
    assert set(parse_chart(only_expert).tracks) == {"expert"}
    new, made = fill_missing_difficulties(only_expert)
    assert made == ["hard", "medium", "easy"]
    c = parse_chart(new)
    n = {d: len(c.tracks[d].notes) for d in ("easy", "medium", "hard", "expert")}
    assert n["easy"] < n["medium"] < n["hard"] <= n["expert"], n
    ex_ticks = {x.tick for x in c.tracks["expert"].notes}
    assert all(x.tick in ex_ticks for d in ("easy", "medium", "hard") for x in c.tracks[d].notes)   # senkron ayni
    assert max(x.mask for x in c.tracks["easy"].notes) < 8                                           # Easy: 3 perde
    assert all(ok for ok, _m in validate(new).values())
    assert fill_missing_difficulties(new) == (new, [])                                               # ikinci kez: degismez
