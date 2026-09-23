"""Dil secimi (Turkce / English): tablo butunlugu, kaynak koddaki tum anahtarlar tabloda, dil degisimi ana menuyu
aninda degistirir, ayarlardan secilir ve kaydedilir, Turkce karakterler yazi tiplerinde var."""
from __future__ import annotations

import glob
import os
import re

import pytest

from gh import i18n

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY_PREFIXES = ("common", "diff", "key", "hint", "title", "songs", "diffsel", "set", "ctl", "game", "pause", "fail",
                "hud", "res", "cal", "imp", "sec", "stage")
TR_CHARS = "çğıİöşüÇĞÖŞÜ"


@pytest.fixture(autouse=True)
def _restore_language():
    old = i18n.get_language()
    yield
    i18n.set_language(old)


def test_every_entry_has_english_and_turkish():
    for key, entry in i18n.STRINGS.items():
        assert entry.get("en"), key
        assert entry.get("tr"), key
        # bicim alanlari iki dilde ayni
        f_en = set(re.findall(r"{(\w+)}", entry["en"]))
        f_tr = set(re.findall(r"{(\w+)}", entry["tr"]))
        assert f_en == f_tr, key


def _source_keys() -> set[str]:
    pat = re.compile(r"""["']((?:%s)\.[A-Za-z0-9_.]+)["']""" % "|".join(KEY_PREFIXES))
    keys = set()
    for path in glob.glob(os.path.join(ROOT, "gh", "**", "*.py"), recursive=True):
        if path.endswith("i18n.py"):
            continue
        src = open(path, encoding="utf-8-sig").read()
        for m in pat.finditer(src):
            k = m.group(1)
            if k.endswith("."):
                continue
            keys.add(k)
    return keys


def test_all_keys_used_in_source_are_in_table():
    keys = _source_keys()
    assert len(keys) > 150                               # tarama gercekten anahtar buluyor
    missing = sorted(k for k in keys if k not in i18n.STRINGS)
    assert not missing, missing
    # dinamik kullanilan anahtarlar
    for d in ("easy", "medium", "hard", "expert"):
        assert i18n.DIFF_KEYS[d] in i18n.STRINGS
    for k in i18n.SECTION_KEYS.values():
        assert k in i18n.STRINGS


def test_import_stage_texts_are_translated():
    """gh.importer / gh.autochart ilerleme metinlerinin hepsinin Turkcesi var."""
    texts = set()
    for path in [os.path.join(ROOT, "gh", "importer.py")] + glob.glob(os.path.join(ROOT, "gh", "autochart", "*.py")):
        src = open(path, encoding="utf-8-sig").read()
        texts |= set(re.findall(r"_progress\([^,]+,\s*[^,]+,\s*\"([^\"]+)\"\)", src))
        texts |= set(re.findall(r"sub\([\d.]+,\s*\"([^\"]+)\"\)", src))
    assert len(texts) >= 12
    i18n.set_language("tr")
    for s in texts:
        assert ("stage." + s) in i18n.STRINGS, s
        assert i18n.stage(s) != s or s in ("Done",), s


def test_t_fallbacks_and_formatting():
    i18n.set_language("tr")
    assert i18n.t("title.play") == "OYNA"
    assert i18n.t("songs.count", n=3) == "3 şarkı"
    assert i18n.t("no.such.key") == "no.such.key"
    i18n.set_language("xx")                              # bilinmeyen -> Ingilizce
    assert i18n.get_language() == "en" and i18n.t("title.play") == "PLAY"
    i18n.set_language("tr")
    assert i18n.upper("istanbul ılık") == "İSTANBUL ILIK"
    assert i18n.section_label("Verse 2") == "Kıta 2"
    assert i18n.section_label("Chorus") == "Nakarat"
    assert i18n.section_label("Pre-Chorus") == "Ön Nakarat"
    assert i18n.section_label("Odd Time") == "Odd Time"
    assert i18n.diff_name("expert") == "Uzman"
    assert i18n.default_language() in ("tr", "en")


def test_language_switch_changes_title_menu_and_is_saved():
    pygame = pytest.importorskip("pygame")
    from gh import headless
    from gh.scenes import SettingsScene, TitleScene
    from gh.settings_store import default_settings
    app = headless.make_app(default_settings())
    app.stack = []
    title = TitleScene(app)
    app.push(title)
    i18n.set_language("en")
    assert [i18n.t(k) for k in title.menu.items] == ["PLAY", "IMPORT SONG", "DOWNLOAD SETLISTS", "CALIBRATION", "SETTINGS", "QUIT"]
    i18n.set_language("tr")
    assert [i18n.t(k) for k in title.menu.items] == ["OYNA", "ŞARKI EKLE", "SETLIST İNDİR", "KALİBRASYON", "AYARLAR", "ÇIKIŞ"]
    # ayarlar: ilk secilebilir satir dil secimi; Saga -> diger dil, hemen uygulanir ve kaydedilir
    st = SettingsScene(app)
    app.push(st)
    row = st.rows[st.index]
    assert row[0] == "choice" and row[1] == "set.language"
    st.on_menu("RIGHT")
    assert i18n.get_language() == "en" and app.settings.extra["language"] == "en"
    st.on_menu("RIGHT")
    assert i18n.get_language() == "tr" and app.settings.extra["language"] == "tr"
    st.draw(app.screen)                                 # Turkce cizim hatasiz
    app.stack = []
    del pygame


def test_fonts_have_turkish_glyphs():
    pygame = pytest.importorskip("pygame")
    from gh import headless
    app = headless.make_app()
    for family in ("ui", "title", "mono"):
        for bold in (False, True):
            font = app.assets.fonts.get(24, family, bold)
            metrics = font.metrics(TR_CHARS)
            assert all(m is not None for m in metrics), (family, bold)
    del pygame
