"""Chorus Encore (https://www.enchor.us) istemcisi: arama, .sng paket indirme ve Songs altina kurma.

pygame IMPORT ETMEZ. Oyun ici setlist indirici (gh/scenes/setlists.py) ve tools/chorus_fetch.py kullanir.
- search(): api.enchor.us/search (gitar Expert'i olan chart'lar)
- download(): files.enchor.us/<md5>[_novideo].sng -> gecici klasore ac -> eksik zorluklari doldur -> song.ini'ye
  chorus_md5 -> tek adimda (os.replace) '<Sanatci> - <Sarki>' klasorune tasi. Iptal / hata: yarim klasor kalmaz.
- installed_md5s(): Songs altinda kurulu paketlerin md5'leri (song.ini chorus_md5) -> kaldigi yerden devam.
Indirilenler (ses + chart) hak sahiplerine aittir; yalniz kullanicinin bilgisayarina iner.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import unicodedata
import urllib.error
import urllib.request

from .chart.song_ini import strip_rich_text

API = "https://api.enchor.us/search"
FILES = "https://files.enchor.us/{md5}{suffix}.sng"
UA = "GuitarHero-rhythm-game/1.2 (+https://github.com/LeventBic/Guitar_Hero)"
OFFICIAL = {"harmonix", "neversoft", "vicarious visions", "freestylegames", "activision", "budcat", "beenox"}
MD5_RE = re.compile(r"[0-9a-f]{32}")


class Cancelled(Exception):
    """Kullanici indirmeyi iptal etti."""


def _post(url: str, payload: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def search(query: str, per_page: int = 25) -> list[dict]:
    d = _post(API, {"search": query, "per_page": per_page, "page": 1, "instrument": "guitar",
                    "difficulty": "expert", "drumType": None, "drumsReviewed": False, "sort": None,
                    "source": "api"})
    return d.get("data", [])


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", strip_rich_text(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def is_official(r: dict) -> bool:
    return norm(r.get("charter", "")) in OFFICIAL


def pick(results: list[dict], query: str, allow_official: bool = False) -> dict | None:
    """Sanatci + sarki adi eslesen, resmi oyun chart'i olmayan, canli / cover olmayan ilk sonuc."""
    words = set(norm(query).split())
    best = None
    for r in results:
        if not allow_official and is_official(r):
            continue
        name, artist = norm(r.get("name", "")), norm(r.get("artist", ""))
        if not words <= (set(name.split()) | set(artist.split())):
            continue
        extra = {"live", "cover", "remix", "acoustic", "demo"} & (set(name.split()) - words)
        score = (not extra, name == " ".join(w for w in norm(query).split() if w in name.split()))
        if best is None or score > best[0]:
            best = (score, r)
    return best[1] if best else None


def describe(r: dict) -> str:
    ln = int(r.get("song_length") or 0) // 1000
    return (f"{strip_rich_text(r.get('artist', ''))} - {strip_rich_text(r.get('name', ''))}  "
            f"[{strip_rich_text(r.get('charter', ''))}]  {ln // 60}:{ln % 60:02d}  diff {r.get('diff_guitar')}  "
            f"md5 {r.get('md5')}{'  (OFFICIAL)' if is_official(r) else ''}")


def folder_name(artist: str, name: str) -> str:
    s = f"{strip_rich_text(artist)} - {strip_rich_text(name)}".strip(" -")
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).rstrip(". ")
    return s or "Chorus Song"


def installed_md5s(root: str) -> set[str]:
    """root altindaki tum song.ini'lerde 'chorus_md5 = ...' satirlari."""
    out: set[str] = set()
    if not os.path.isdir(root):
        return out
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if not d.endswith(".part")]
        if "song.ini" in filenames:
            try:
                with open(os.path.join(dirpath, "song.ini"), encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        if line.startswith("chorus_md5"):
                            out.add(line.split("=", 1)[1].strip())
            except OSError:
                pass
    return out


def _fetch(md5: str, tmp: str, no_video: bool, progress, cancel) -> None:
    for suffix in (("_novideo", "") if no_video else ("",)):
        req = urllib.request.Request(FILES.format(md5=md5, suffix=suffix), headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                got = 0
                while chunk := r.read(1 << 18):
                    if cancel is not None and cancel.is_set():
                        raise Cancelled()
                    f.write(chunk)
                    got += len(chunk)
                    if progress is not None:
                        progress(got, total)
            return
        except urllib.error.HTTPError as exc:
            if exc.code != 404 or not suffix:
                raise


def download(md5: str, songs_dir: str, name_hint: tuple[str, str] = ("", ""), no_video: bool = False,
             progress=None, cancel=None) -> str:
    """md5 paketini indir ve songs_dir altina kur; kurulan klasoru dondur.
    progress(indirilen_bayt, toplam_bayt); cancel: threading.Event (set -> Cancelled, hicbir sey kalmaz)."""
    md5 = md5.lower().strip()
    if not MD5_RE.fullmatch(md5):
        raise ValueError(f"bad md5: {md5}")
    from .chart.sng import extract_sng, read_sng
    from .importer import fill_difficulties
    os.makedirs(songs_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".sng")
    os.close(fd)
    part = ""
    try:
        _fetch(md5, tmp, no_video, progress, cancel)
        meta, _files = read_sng(tmp)
        base = folder_name(meta.get("artist", name_hint[0]), meta.get("name", name_hint[1]))
        part = os.path.join(songs_dir, f".{md5}.part")
        shutil.rmtree(part, ignore_errors=True)
        extract_sng(tmp, part)
        fill_difficulties(part)
        with open(os.path.join(part, "song.ini"), "a", encoding="utf-8", newline="\n") as f:
            f.write(f"chorus_md5 = {md5}\n")
        dest = os.path.join(songs_dir, base)
        k = 2
        while os.path.exists(dest):
            dest = os.path.join(songs_dir, f"{base} ({k})")
            k += 1
        os.replace(part, dest)
        part = ""
        return dest
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
        if part:
            shutil.rmtree(part, ignore_errors=True)


__all__ = ["search", "pick", "describe", "download", "installed_md5s", "is_official", "folder_name", "Cancelled"]
