"""Sarki ekleme: etiket okuyuculari (ID3v2 / Vorbis / FLAC / WAV), dosya adindan metadata, uctan uca ice aktarma
(WAV + OGG), hata temizligi, yeniden chart'lama ve on yuz akisi (surukle-birak, gelen kutusu, R = re-chart)."""
from __future__ import annotations

import os
import struct

import numpy as np
import pytest

from audio_synth import render_song, write_wav
from gh.audio_meta import (meta_from_filename, parse_flac, parse_id3v2, parse_vorbis_comment, read_metadata)
from gh.chart import load_song, scan_songs

PNG_1PX = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
           b"\x00\x00\x00\x0cIDATx\x9cc\xf8\xff\xff?\x00\x05\xfe\x02\xfe\xa7\x35\x81\x84\x00\x00\x00\x00IEND"
           b"\xaeB`\x82")


# --------------------------------------------------------------------------- etiket okuyuculari

def _frame23(fid: str, payload: bytes) -> bytes:
    return fid.encode() + struct.pack(">I", len(payload)) + b"\x00\x00" + payload


def _syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def _frame24(fid: str, payload: bytes) -> bytes:
    return fid.encode() + _syncsafe(len(payload)) + b"\x00\x00" + payload


def test_id3v23_parser_text_encodings_and_cover():
    frames = (
        _frame23("TIT2", b"\x01" + "Şarkı Adı".encode("utf-16")) +           # UTF-16 + BOM
        _frame23("TPE1", b"\x00" + "Motörhead".encode("latin-1")) +           # latin-1
        _frame23("TALB", b"\x00Album X\x00") +
        _frame23("TYER", b"\x001999") +
        _frame23("TCON", b"\x00(17)") +                                       # ID3v1 tur kodu -> Rock
        _frame23("APIC", b"\x00image/png\x00\x03cover\x00" + PNG_1PX) +
        b"\x00" * 32                                                          # dolgu
    )
    tag = b"ID3\x03\x00\x00" + _syncsafe(len(frames)) + frames
    meta, size = parse_id3v2(tag + b"\xff\xfb audio...")
    assert size == len(tag)
    assert meta.title == "Şarkı Adı"
    assert meta.artist == "Motörhead"
    assert meta.album == "Album X" and meta.year == "1999" and meta.genre == "Rock"
    assert meta.cover == PNG_1PX and meta.cover_mime == "image/png"


def test_id3v24_parser_utf8_syncsafe_and_tdrc(tmp_path):
    frames = (_frame24("TIT2", b"\x03" + "Ünlü Şarkı".encode("utf-8")) +
              _frame24("TPE1", b"\x03Band\x00Other Band") +                   # coklu deger: ilki
              _frame24("TDRC", b"\x032020-05-01") + _frame24("TCON", b"\x03Metal"))
    tag = b"ID3\x04\x00\x00" + _syncsafe(len(frames)) + frames
    p = tmp_path / "x.mp3"
    p.write_bytes(tag + b"\x00" * 200)
    meta = read_metadata(str(p))
    assert (meta.title, meta.artist, meta.year, meta.genre) == ("Ünlü Şarkı", "Band", "2020", "Metal")


def test_id3v1_fallback(tmp_path):
    t = b"TAG" + b"Old Title".ljust(30, b"\x00") + b"Old Artist".ljust(30, b"\x00") + b"Old Album".ljust(30, b"\x00")
    t += b"1987" + b"\x00" * 30 + bytes([9])
    p = tmp_path / "old.mp3"
    p.write_bytes(b"\xff\xfb" + b"\x00" * 500 + t)
    meta = read_metadata(str(p))
    assert (meta.title, meta.artist, meta.album, meta.year, meta.genre) == ("Old Title", "Old Artist", "Old Album",
                                                                            "1987", "Metal")


def _vorbis_block(tags: dict[str, str]) -> bytes:
    vendor = b"test"
    out = struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", len(tags))
    for k, v in tags.items():
        e = f"{k}={v}".encode("utf-8")
        out += struct.pack("<I", len(e)) + e
    return out


def test_flac_vorbis_comment_and_picture():
    vc = _vorbis_block({"TITLE": "Flac Song", "ARTIST": "Flac Band", "DATE": "2011", "GENRE": "Jazz"})
    pic = (struct.pack(">I", 3) + struct.pack(">I", 9) + b"image/png" + struct.pack(">I", 0) +
           struct.pack(">IIII", 1, 1, 24, 0) + struct.pack(">I", len(PNG_1PX)) + PNG_1PX)
    data = (b"fLaC" + bytes([0]) + (34).to_bytes(3, "big") + b"\x00" * 34 +
            bytes([4]) + len(vc).to_bytes(3, "big") + vc +
            bytes([0x80 | 6]) + len(pic).to_bytes(3, "big") + pic)
    meta = parse_flac(data)
    assert (meta.title, meta.artist, meta.year, meta.genre) == ("Flac Song", "Flac Band", "2011", "Jazz")
    assert meta.cover == PNG_1PX
    m2 = parse_vorbis_comment(_vorbis_block({"title": "lower", "Artist": "Mixed"}))
    assert (m2.title, m2.artist) == ("lower", "Mixed")


@pytest.mark.parametrize("name,expected", [
    ("Artist Name - Song Title.mp3", ("Artist Name", "Song Title")),
    ("03 - Artist - Title.ogg", ("Artist", "Title")),
    ("07. Only Title.flac", ("", "Only Title")),
    ("my_song_name.wav", ("", "my song name")),
    ("Band - Title - Live Version.mp3", ("Band", "Title - Live Version")),
])
def test_meta_from_filename(name, expected):
    assert meta_from_filename(os.path.join("x", name)) == expected


def test_real_tagged_files_via_soundfile(tmp_path):
    sf = pytest.importorskip("soundfile")
    x = (0.2 * np.sin(np.arange(22050) * 0.05)).astype(np.float32)
    for ext, fmt in (("ogg", "OGG"), ("flac", "FLAC"), ("wav", "WAV")):
        p = str(tmp_path / f"t.{ext}")
        with sf.SoundFile(p, "w", 22050, 1, format=fmt) as f:
            f.title, f.artist, f.album, f.date = "Tägged", "Tag Artist", "Tag Album", "2021"
            f.write(x)
        m = read_metadata(p)
        assert (m.title, m.artist, m.album, m.year) == ("Tägged", "Tag Artist", "Tag Album", "2021"), ext


# --------------------------------------------------------------------------- uctan uca

@pytest.fixture(scope="module")
def synth_song():
    return render_song(128.0, 12, 22050, seed=11)


@pytest.fixture()
def mixer():
    pygame = pytest.importorskip("pygame")
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    if not pygame.mixer.get_init():
        pygame.mixer.init(44100, -16, 2, 1024)
    return pygame


def test_import_wav_end_to_end_with_filename_fallback(tmp_path, synth_song, mixer):
    from gh.importer import import_audio
    src = tmp_path / "Test Artist - Synth Song.wav"
    write_wav(str(src), synth_song)
    songs = tmp_path / "Songs"
    stages = []
    folder = import_audio(str(src), str(songs), lambda f, t: stages.append((f, t)))
    assert os.path.basename(folder) == "Test Artist - Synth Song"
    names = set(os.listdir(folder))
    assert {"song.wav", "notes.chart", "song.ini", "album.png"} <= names
    fr = [f for f, _t in stages]
    assert fr == sorted(fr) and fr[-1] == 1.0 and len({t for _f, t in stages}) >= 6
    ini = open(os.path.join(folder, "song.ini"), encoding="utf-8").read()
    for line in ("name = Synth Song", "artist = Test Artist", "charter = RIFF Auto", "auto_chart = 1", "delay = 0"):
        assert line in ini
    chart = load_song(folder)
    assert chart.info.auto_chart and chart.info.name == "Synth Song" and chart.info.artist == "Test Artist"
    assert set(chart.tracks) == {"easy", "medium", "hard", "expert"}
    assert chart.info.stems["song"].endswith("song.wav")
    assert 20000 < chart.info.song_length_ms < 30000
    assert 0 <= chart.info.diff_guitar <= 6
    # ayni ad tekrar: benzersiz klasor
    folder2 = import_audio(str(src), str(songs))
    assert os.path.basename(folder2) == "Test Artist - Synth Song (2)"
    # _Import taranmaz
    inbox = songs / "_Import"
    inbox.mkdir()
    (inbox / "waiting.wav").write_bytes(src.read_bytes())
    fake = inbox / "Fake - Song"
    fake.mkdir()
    (fake / "notes.chart").write_text(open(os.path.join(folder, "notes.chart"), encoding="utf-8").read(),
                                      encoding="utf-8")
    found = scan_songs(str(songs))
    assert len(found) == 2 and all(s.auto_chart for s in found)


def test_import_ogg_with_tags(tmp_path, synth_song, mixer):
    sf = pytest.importorskip("soundfile")
    from gh.importer import import_audio
    src = str(tmp_path / "whatever.ogg")
    with sf.SoundFile(src, "w", synth_song.sr, 1, format="OGG") as f:
        f.title, f.artist, f.album, f.date, f.genre = "Ogg Title", "Ogg Band", "Ogg Album", "2019", "Rock"
        f.write(synth_song.samples)
    folder = import_audio(src, str(tmp_path / "Songs"))
    assert os.path.basename(folder) == "Ogg Band - Ogg Title"
    info = load_song(folder).info
    assert (info.name, info.artist, info.album, info.year, info.genre) == ("Ogg Title", "Ogg Band", "Ogg Album",
                                                                           "2019", "Rock")
    assert info.stems["song"].endswith("song.ogg")
    # decode -> ayni analiz: ogg kaybi tempo/vuruslari bozmaz
    from gh.autochart import analyze
    from gh.importer import decode_audio
    x, sr = decode_audio(src)
    assert abs(analyze(x, sr).tempo - 128.0) < 1.28


def test_embedded_cover_is_used(tmp_path, synth_song, mixer):
    from gh.importer import import_audio
    pygame = mixer
    img = pygame.Surface((40, 30))
    img.fill((10, 200, 30))
    png = str(tmp_path / "c.png")
    pygame.image.save(img, png)
    cover = open(png, "rb").read()
    frames = (_frame23("TIT2", b"\x00Covered") + _frame23("TPE1", b"\x00Cover Band") +
              _frame23("APIC", b"\x00image/png\x00\x03\x00" + cover))
    tag = b"ID3\x03\x00\x00" + _syncsafe(len(frames)) + frames
    wav = tmp_path / "raw.wav"
    write_wav(str(wav), synth_song)
    # ID3 etiketli WAV: RIFF 'id3 ' parcasi
    data = wav.read_bytes()
    chunk = b"id3 " + struct.pack("<I", len(tag)) + tag + (b"\x00" if len(tag) & 1 else b"")
    body = data[12:] + chunk
    tagged = tmp_path / "tagged.wav"
    tagged.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body)
    folder = import_audio(str(tagged), str(tmp_path / "Songs"))
    assert os.path.basename(folder) == "Cover Band - Covered"
    art = pygame.image.load(os.path.join(folder, "album.png"))
    assert art.get_size() == (512, 512)
    assert tuple(art.get_at((256, 256)))[:3] == (10, 200, 30)


def test_failures_clean_up(tmp_path, mixer, synth_song):
    from gh.importer import ImportFailed, import_audio
    songs = tmp_path / "Songs"
    bad = tmp_path / "Band - Broken.mp3"
    bad.write_bytes(os.urandom(4096))
    with pytest.raises(ImportFailed):
        import_audio(str(bad), str(songs))
    short = render_song(128.0, 2, 22050)
    sp = tmp_path / "Band - Short.wav"
    write_wav(str(sp), short)
    with pytest.raises(ImportFailed, match="too short"):
        import_audio(str(sp), str(songs))
    txt = tmp_path / "notes.txt"
    txt.write_text("hello")
    with pytest.raises(ImportFailed, match="unsupported"):
        import_audio(str(txt), str(songs))
    assert not songs.exists() or os.listdir(songs) == []


def test_rechart_regenerates_same_chart(tmp_path, synth_song, mixer):
    from gh.importer import import_audio, rechart_song
    src = tmp_path / "Re - Chart.wav"
    write_wav(str(src), synth_song)
    folder = import_audio(str(src), str(tmp_path / "Songs"))
    chart_path = os.path.join(folder, "notes.chart")
    original = open(chart_path, encoding="utf-8").read()
    with open(chart_path, "w", encoding="utf-8") as f:
        f.write("[Song]\n{\n}\n")
    rechart_song(folder)
    assert open(chart_path, encoding="utf-8").read() == original
    assert os.path.exists(chart_path + ".bak")


def test_collect_audio_files(tmp_path):
    from gh.importer import collect_audio_files
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "x.mp3").write_bytes(b"x")
    (tmp_path / "a" / "y.txt").write_bytes(b"x")
    (tmp_path / "a" / "sub").mkdir()
    (tmp_path / "a" / "sub" / "z.FLAC").write_bytes(b"x")
    ch = tmp_path / "a" / "Ready Song"
    ch.mkdir()
    (ch / "notes.chart").write_bytes(b"x")
    (ch / "song.ogg").write_bytes(b"x")
    (tmp_path / "b.opus").write_bytes(b"x")
    out = collect_audio_files([str(tmp_path / "a"), str(tmp_path / "b.opus"), str(tmp_path / "missing.mp3")])
    names = [os.path.basename(p) for p in out]
    assert names == ["x.mp3", "Ready Song", "z.FLAC", "b.opus"]    # hazir sarki klasoru tek parca


# --------------------------------------------------------------------------- on yuz akisi

@pytest.fixture()
def app_songs(tmp_path, monkeypatch):
    pygame = pytest.importorskip("pygame")
    from gh import headless, importer, library
    songs = tmp_path / "Songs"
    songs.mkdir()
    monkeypatch.setattr(importer, "songs_dir", lambda: str(songs))
    monkeypatch.setattr(library, "song_roots", lambda: [str(songs)])
    app = headless.make_app()
    pygame.event.clear()
    yield app, songs
    app.stack = []


def _press(app, key, frames=2):
    import pygame
    pygame.event.post(pygame.event.Event(pygame.KEYDOWN, key=key, mod=0, unicode="", scancode=0))
    pygame.event.post(pygame.event.Event(pygame.KEYUP, key=key, mod=0, unicode="", scancode=0))
    app.poll()
    for _ in range(frames):
        app.frame(1 / 60)


def test_drop_file_imports_and_play_now(app_songs, tmp_path, synth_song):
    import pygame
    from gh.scenes import DifficultyScene, ImportScene, SongListScene, TitleScene
    app, songs = app_songs
    wav = tmp_path / "Drop Band - Dropped Song.wav"
    write_wav(str(wav), synth_song)
    app.running = True
    app.stack = []
    app.push(TitleScene(app))
    pygame.event.post(pygame.event.Event(pygame.DROPBEGIN))
    pygame.event.post(pygame.event.Event(pygame.DROPFILE, file=str(wav)))
    pygame.event.post(pygame.event.Event(pygame.DROPCOMPLETE))
    app.poll()
    assert isinstance(app.top, ImportScene)
    scene = app.top
    scene.wait()
    app.frame(1 / 60)
    assert scene.mode == "done" and scene.jobs[0].status == "ok", scene.jobs[0].message
    _press(app, pygame.K_RETURN)                 # PLAY NOW
    assert isinstance(app.top, DifficultyScene)
    sl = app.stack[-2]
    assert isinstance(sl, SongListScene) and sl.sel.name == "Dropped Song" and sl.sel.auto_chart
    assert os.path.exists(wav)                   # birakilan dosya yerinde kalir (yalniz gelen kutusu silinir)
    # oyun sirasinda birakilan dosya bekletilir
    _press(app, pygame.K_RETURN, frames=5)
    from gh.scenes import GameplayScene
    assert isinstance(app.top, GameplayScene)
    app.handle_drop([str(wav)])
    assert isinstance(app.top, GameplayScene) and app.pending_drops


def test_inbox_import_removes_originals_and_keeps_failures(app_songs, tmp_path, synth_song):
    from gh.scenes import ImportScene, TitleScene
    app, songs = app_songs
    inbox = songs / "_Import"
    inbox.mkdir(exist_ok=True)
    good = inbox / "Inbox Band - Inbox Song.wav"
    write_wav(str(good), synth_song)
    bad = inbox / "Bad - File.mp3"
    bad.write_bytes(os.urandom(2048))
    app.stack = []
    app.push(TitleScene(app))
    assert app.check_inbox()
    scene = app.top
    assert isinstance(scene, ImportScene)
    scene.wait()
    app.frame(1 / 60)
    st = {j.name: j.status for j in scene.jobs}
    assert st == {"Inbox Band - Inbox Song": "ok", "Bad - File": "error"}
    assert not good.exists() and bad.exists()
    assert app.inbox_pending() == []             # basarisiz dosya bu oturumda tekrar denenmez
    assert app.inbox_pending(include_failed=True) == [str(bad)]
    assert [s.name for s in scan_songs(str(songs))] == ["Inbox Song"]


def test_songlist_rechart_with_confirmation(app_songs, tmp_path, synth_song):
    import pygame
    from gh.importer import import_audio
    from gh.scenes import ConfirmScene, ImportScene, SongListScene, TitleScene
    app, songs = app_songs
    wav = tmp_path / "Band - Rechart Me.wav"
    write_wav(str(wav), synth_song)
    folder = import_audio(str(wav), str(songs))
    app.stack = []
    app.push(TitleScene(app))
    app.push(SongListScene(app, select_folder=folder))
    _press(app, pygame.K_r)
    assert isinstance(app.top, ConfirmScene)
    _press(app, pygame.K_LEFT)
    _press(app, pygame.K_RETURN)
    assert isinstance(app.top, ImportScene)
    app.top.wait()
    app.frame(1 / 60)
    assert app.top.jobs[0].kind == "rechart" and app.top.jobs[0].status == "ok"
    assert os.path.exists(os.path.join(folder, "notes.chart.bak"))
    _press(app, pygame.K_ESCAPE)                 # sonuc -> sarki listesi
    assert isinstance(app.top, SongListScene) and app.top.sel.folder == folder
    _press(app, pygame.K_i)                      # I = ice aktarma ekrani
    assert isinstance(app.top, ImportScene) and app.top.mode == "drop"
