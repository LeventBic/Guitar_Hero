"""GELISTIRME ARACI (cekirdek: gh/chorus.py): Chorus Encore'dan (https://www.enchor.us, Clone Hero topluluk chart arama motoru) elle
yapilmis chart indirip Songs klasorune acar. Paket (.sng) chart'i yapanin ses dosyasini da icerir; chart o sese
gore yapildigi icin senkron birebirdir.

Kullanim:
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py "Metallica One"                 # ara, en iyi eslesmeyi indir
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py "Metallica One" --list          # yalniz sonuclari listele
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py --md5 410e6812...,5077d61c... --no-video --songs D:\\RIFF\\Songs
  .venv\\Scripts\\python.exe tools\\chorus_fetch.py --from-file liste.txt           # satir basina "Sanatci Sarki"

Yalniz Expert'i olan chart'lara Hard / Medium / Easy, Expert notalarindan secilerek eklenir (senkron ayni kalir);
var olan klasor icin: --fill <klasor>.

Secim: sanatci + sarki adi eslesen, oyundan cikarilmis resmi chart olmayan (Harmonix / Neversoft / ...),
gitar Expert'i olan ilk sonuc (API alaka sirasi). Indirilen dosyalar ve telif: kisisel kullanim icindir;
Songs/ git'e girmez. Servis bagisla ayakta: istekler arasinda bekleme var, toplu indirmede asiri yuklemeyin.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from gh import chorus  # noqa: E402
from gh.chorus import describe, pick, search  # noqa: E402
from gh.importer import fill_difficulties  # noqa: E402

PAUSE_S = 1.5


def download(md5: str, songs_dir: str, name_hint: tuple[str, str] = ("", ""), no_video: bool = False) -> str:
    return chorus.download(md5, songs_dir, name_hint, no_video=no_video)


def fetch(query: str, songs_dir: str, *, allow_official: bool = False, dry: bool = False,
          no_video: bool = False) -> str | None:
    res = search(query)
    r = pick(res, query, allow_official)
    if r is None:
        print(f"NOT FOUND  {query}  ({len(res)} results, none matched)")
        return None
    print(f"FOUND      {query}  ->  {describe(r)}")
    if dry:
        return None
    dest = download(r["md5"], songs_dir, (r.get("artist", ""), r.get("name", "")), no_video=no_video)
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
    p.add_argument("--fill", metavar="FOLDER", help="add missing Hard/Medium/Easy to an existing song folder")
    p.add_argument("--no-video", action="store_true", help="download the package without the music video")
    a = p.parse_args(argv)
    if a.fill:
        made = fill_difficulties(a.fill)
        print(f"FILLED     {', '.join(made)}" if made else "nothing to fill (no Expert-only notes.chart)")
        return 0
    if a.md5:
        for m in a.md5.lower().split(","):
            print("SAVED", download(m.strip(), a.songs, no_video=a.no_video))
            time.sleep(PAUSE_S)
        return 0
    if a.from_file:
        with open(a.from_file, encoding="utf-8") as f:
            queries = [ln.strip() for ln in f if ln.strip() and not ln.lstrip().startswith("#")]
        missing = 0
        for q in queries:
            try:
                missing += fetch(q, a.songs, allow_official=a.allow_official, dry=a.dry_run,
                                 no_video=a.no_video) is None and not a.dry_run
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
    return 0 if fetch(a.query, a.songs, allow_official=a.allow_official, dry=a.dry_run,
                      no_video=a.no_video) or a.dry_run else 1


if __name__ == "__main__":
    sys.exit(main())
