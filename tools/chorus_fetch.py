"""GELISTIRME ARACI: Chorus Encore'dan (https://www.enchor.us, Clone Hero topluluk chart arama motoru) elle
yapilmis chart indirip Songs klasorune acar. Paket (.sng) chart'i yapanin ses dosyasini da icerir; chart o sese
gore yapildigi icin senkron birebirdir.

Kullanim:
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py "Metallica One"                 # ara, en iyi eslesmeyi indir
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py "Metallica One" --list          # yalniz sonuclari listele
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py --md5 410e6812... --songs D:\\RIFF\\Songs
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py --from-file liste.txt           # satir basina "Sanatci Sarki"

Secim: sanatci + sarki adi eslesen, oyundan cikarilmis resmi chart olmayan (Harmonix / Neversoft / ...),
gitar Expert'i olan ilk sonuc (API alaka sirasi). Indirilen dosyalar ve telif: kisisel kullanim icindir;
Songs/ git'e girmez. Servis bagisla ayakta: istekler arasinda bekleme var, toplu indirmede asiri yuklemeyin.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gh.chart.sng import extract_sng  # noqa: E402
from gh.chart.song_ini import strip_rich_text  # noqa: E402

API = "https://api.enchor.us/search"
FILES = "https://files.enchor.us/{md5}.sng"
UA = "RIFF-rhythm-game/1.0 (chorus_fetch.py)"
OFFICIAL = {"harmonix", "neversoft", "vicarious visions", "freestylegames", "activision", "budcat", "beenox"}
PAUSE_S = 1.5


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


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", strip_rich_text(s or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def is_official(r: dict) -> bool:
    return _norm(r.get("charter", "")) in OFFICIAL


def pick(results: list[dict], query: str, allow_official: bool = False) -> dict | None:
    words = set(_norm(query).split())
    best = None
    for r in results:
        if not allow_official and is_official(r):
            continue
        name, artist = _norm(r.get("name", "")), _norm(r.get("artist", ""))
        have = set(name.split()) | set(artist.split())
        if not words <= have:
            continue
        # canli / cover / remix surumleri, sorguda istenmedikce geride
        extra = {"live", "cover", "remix", "acoustic", "demo"} & (set(name.split()) - words)
        score = (not extra, name == " ".join(w for w in _norm(query).split() if w in name.split()))
        if best is None or score > best[0]:
            best = (score, r)
    return best[1] if best else None


def describe(r: dict) -> str:
    ln = int(r.get("song_length") or 0) // 1000
    return (f"{strip_rich_text(r.get('artist', ''))} - {strip_rich_text(r.get('name', ''))}  "
            f"[{strip_rich_text(r.get('charter', ''))}]  {ln // 60}:{ln % 60:02d}  diff {r.get('diff_guitar')}  "
            f"md5 {r.get('md5')}{'  (OFFICIAL)' if is_official(r) else ''}")


def _folder_name(meta_artist: str, meta_name: str) -> str:
    s = f"{strip_rich_text(meta_artist)} - {strip_rich_text(meta_name)}".strip(" -")
    s = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", s).rstrip(". ")
    return s or "Chorus Song"


def download(md5: str, songs_dir: str, name_hint: tuple[str, str] = ("", "")) -> str:
    """md5 paketini indir, Songs altinda '<Sanatci> - <Sarki>' klasorune ac (varsa ' (2)' ...)."""
    if not re.fullmatch(r"[0-9a-f]{32}", md5):
        raise ValueError(f"bad md5: {md5}")
    os.makedirs(songs_dir, exist_ok=True)
    fd, tmp = tempfile.mkstemp(suffix=".sng")
    os.close(fd)
    try:
        req = urllib.request.Request(FILES.format(md5=md5), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
        from gh.chart.sng import read_sng
        meta, _files = read_sng(tmp)
        base = _folder_name(meta.get("artist", name_hint[0]), meta.get("name", name_hint[1]))
        dest = os.path.join(songs_dir, base)
        k = 2
        while os.path.exists(dest):
            dest = os.path.join(songs_dir, f"{base} ({k})")
            k += 1
        extract_sng(tmp, dest)
        with open(os.path.join(dest, "song.ini"), "a", encoding="utf-8", newline="\n") as f:
            f.write(f"chorus_md5 = {md5}\n")
        return dest
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def fetch(query: str, songs_dir: str, *, allow_official: bool = False, dry: bool = False) -> str | None:
    res = search(query)
    r = pick(res, query, allow_official)
    if r is None:
        print(f"NOT FOUND  {query}  ({len(res)} results, none matched)")
        return None
    print(f"FOUND      {query}  ->  {describe(r)}")
    if dry:
        return None
    dest = download(r["md5"], songs_dir, (r.get("artist", ""), r.get("name", "")))
    print(f"SAVED      {dest}")
    return dest


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Download hand-made Clone Hero charts from Chorus Encore")
    p.add_argument("query", nargs="?", help='"Artist Song"')
    p.add_argument("--songs", default=os.path.join(ROOT, "Songs"), help="target Songs folder")
    p.add_argument("--md5", help="download this exact chart (md5 from --list)")
    p.add_argument("--list", action="store_true", help="only list search results")
    p.add_argument("--from-file", help="text file: one 'Artist Song' query per line (# comments)")
    p.add_argument("--dry-run", action="store_true", help="show picks without downloading")
    p.add_argument("--allow-official", action="store_true", help="also pick charts ripped from official games")
    a = p.parse_args(argv)
    if a.md5:
        print("SAVED", download(a.md5.lower(), a.songs))
        return 0
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as f:
            queries = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        missing = 0
        for q in queries:
            try:
                missing += fetch(q, a.songs, allow_official=a.allow_official, dry=a.dry_run) is None and not a.dry_run
            except Exception as exc:  # ag hatasi: listeye devam
                missing += 1
                print(f"ERROR      {q}: {exc}")
            time.sleep(PAUSE_S)
        print(f"done: {len(queries) - missing}/{len(queries)}")
        return 0
    if not a.query:
        p.error("query, --md5 or --from-file required")
    if a.list:
        for r in search(a.query):
            print(describe(r))
        return 0
    return 0 if fetch(a.query, a.songs, allow_official=a.allow_official, dry=a.dry_run) or a.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
