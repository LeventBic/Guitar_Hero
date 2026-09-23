import os

import pytest

from gh.chart import load_song, parse_chart, read_song_ini, scan_songs
from gh.chart import loader as loader_mod
from gh.chart.hopo import chart_hopo_threshold, midi_hopo_threshold
from gh.chart.song_ini import fill_song_info
from gh.models import NoteType, SongInfo

S, H, T = NoteType.STRUM, NoteType.HOPO, NoteType.TAP


def golden_chart(res: int) -> str:
    """192 tabanli tick'ler res'e olceklenir."""
    k = res / 192

    def t(x):
        return int(x * k)

    track = [
        (0, "N 0 0"),
        (192, "N 1 96"),
        (256, "N 2 0"),
        (384, "N 0 192"), (384, "N 1 0"), (384, "S 2 192"),
        (448, "N 1 0"),
        (512, "N 3 0"),
        (576, "N 3 0"),
        (768, "N 7 0"), (768, "E solo"),
        (800, "N 0 0"), (800, "N 5 0"),
        (960, "N 4 0"), (960, "N 5 0"), (960, "E soloend"),
        (1152, "N 2 0"), (1152, "N 6 0"),
        (1500, "S 2 50"),
    ]
    def scale(ev):  # N/S uzunluklarini da olcekle
        p = ev.split()
        if p[0] in ("N", "S"):
            p[2] = str(t(int(p[2])))
        return " ".join(p)

    body = "\n".join(f"  {t(a)} = {scale(b)}" for a, b in track)
    return f"""\ufeff[Song]
{{
  Name = "Test Song"
  Artist = "Tester"
  Charter = "Me"
  Year = ", 2026"
  Offset = 0.5
  Resolution = {res}
}}
[SyncTrack]
{{
  0 = TS 4
  0 = B 120000
  {t(768)} = B 150000
  {t(768)} = A 2000000
}}
[Events]
{{
  0 = E "section Intro"
  {t(768)} = E "section Verse 1"
  {t(960)} = E "prc_chorus_a"
  {t(3072)} = E "end"
}}
[ExpertSingle]
{{
{body}
}}
[ExpertDoubleBass]
{{
  0 = N 4 0
}}
""".replace("\n", "\r\n")


EXPECTED = [  # (tick192, mask, type, length192)
    (0, 0b1, S, 0),
    (192, 0b10, S, 96),
    (256, 0b100, H, 0),
    (384, 0b11, S, 192),
    (448, 0b10, S, 0),      # akordaki perdeye inis
    (512, 0b1000, H, 0),
    (576, 0b1000, S, 0),    # ayni perde tekrari
    (768, 0, S, 0),         # acik nota
    (800, 0b1, S, 0),       # dogal HOPO + N5 -> strum
    (960, 0b10000, H, 0),   # dogal strum + N5 -> HOPO
    (1152, 0b100, T, 0),    # tap
]


@pytest.mark.parametrize("res", [192, 480])
def test_golden_chart(res):
    k = res / 192
    ch = parse_chart(golden_chart(res))
    assert ch.resolution == res
    assert ch.info.name == "Test Song" and ch.info.artist == "Tester"
    assert ch.info.charter == "Me" and ch.info.year == "2026"
    assert ch.offset == pytest.approx(0.5)
    assert list(ch.tracks) == ["expert"]
    notes = ch.tracks["expert"].notes
    got = [(n.tick, n.mask, n.type, n.length_ticks) for n in notes]
    assert got == [(int(a * k), m, ty, int(ln * k)) for a, m, ty, ln in EXPECTED]
    assert [n.index for n in notes] == list(range(len(notes)))
    # zamanlar: 120 BPM -> 768 tick(192) = 2 s, sonra 150 BPM
    assert notes[1].time == pytest.approx(0.5)
    assert notes[1].end_time == pytest.approx(0.75)
    assert notes[7].time == pytest.approx(2.0)
    assert notes[9].time == pytest.approx(2.4)
    assert notes[10].time == pytest.approx(2.8)
    assert notes[0].end_time == notes[0].time and not notes[0].has_sustain
    assert notes[7].is_open


@pytest.mark.parametrize("res", [192, 480])
def test_sp_solo_sections_end(res):
    ch = parse_chart(golden_chart(res))
    tr = ch.tracks["expert"]
    assert len(tr.sp_phrases) == 1          # notasiz cumle atildi
    sp = tr.sp_phrases[0]
    assert (sp.first_note, sp.last_note) == (3, 5)
    assert [n.sp_phrase for n in tr.notes] == [-1, -1, -1, 0, 0, 0, -1, -1, -1, -1, -1]
    assert [n.index for n in tr.notes if n.sp_phrase_end] == [5]
    assert sp.start_time == pytest.approx(1.0) and sp.end_time == pytest.approx(1.5)
    assert len(tr.solos) == 1
    solo = tr.solos[0]
    assert (solo.first_note, solo.last_note) == (7, 9)   # soloend tick'i dahil
    assert solo.start_time == pytest.approx(2.0) and solo.end_time == pytest.approx(2.4)
    assert [(s.name, round(s.time, 6)) for s in ch.sections] == [
        ("Intro", 0.0), ("Verse 1", 2.0), ("chorus a", 2.4)]
    # [end] tick 3072(192) = 2 s + 12 beat * 0.4 = 6.8 s
    assert ch.end_time == pytest.approx(6.8)


def _mini(res, lines, extra_song="", sync="0 = B 120000"):
    body = "\n".join(lines)
    return (f"[Song]\n{{\nResolution = {res}\n{extra_song}\n}}\n[SyncTrack]\n{{\n{sync}\n}}\n"
            f"[ExpertSingle]\n{{\n{body}\n}}\n")


def _types(text, info=None):
    return [n.type for n in parse_chart(text, info).tracks["expert"].notes]


@pytest.mark.parametrize("res,thr", [(192, 65), (480, 162)])
def test_hopo_threshold_edges(res, thr):
    assert chart_hopo_threshold(res) == thr
    assert _types(_mini(res, ["0 = N 0 0", f"{thr} = N 1 0"])) == [S, H]
    assert _types(_mini(res, ["0 = N 0 0", f"{thr + 1} = N 1 0"])) == [S, S]


def test_same_fret_and_chords_never_natural_hopo():
    assert _types(_mini(192, ["0 = N 2 0", "30 = N 2 0"])) == [S, S]
    # akor, onceki notaya cok yakin olsa da strum
    assert _types(_mini(192, ["0 = N 0 0", "30 = N 1 0", "30 = N 2 0"])) == [S, S]
    # akordan, akorda OLMAYAN perdeye -> HOPO; akordaki perdeye -> strum
    assert _types(_mini(192, ["0 = N 0 0", "0 = N 1 0", "30 = N 2 0"])) == [S, H]
    assert _types(_mini(192, ["0 = N 0 0", "0 = N 1 0", "30 = N 0 0"])) == [S, S]
    # ayni akor tekrari
    assert _types(_mini(192, ["0 = N 0 0", "0 = N 1 0", "30 = N 0 0", "30 = N 1 0"])) == [S, S]


def test_forced_inverts_and_tap_overrides():
    # forced chord -> HOPO; forced ilk nota -> HOPO
    assert _types(_mini(192, ["0 = N 0 0", "0 = N 5 0", "300 = N 0 0", "300 = N 1 0", "300 = N 5 0"])) == [H, H]
    # tap, force'u ezer
    assert _types(_mini(192, ["0 = N 0 0", "40 = N 1 0", "40 = N 5 0", "40 = N 6 0"])) == [S, T]
    # N5 / N6 notasiz tick'te etkisiz
    assert _types(_mini(192, ["0 = N 0 0", "10 = N 5 0", "300 = N 1 0"])) == [S, S]


def test_open_notes():
    notes = parse_chart(_mini(192, ["0 = N 7 96", "40 = N 0 0", "200 = N 7 0", "200 = N 2 50"])).tracks["expert"].notes
    assert [(n.mask, n.type, n.length_ticks) for n in notes] == [(0, S, 96), (1, H, 0), (0b100, S, 50)]
    # acik nota -> perdeye / perde -> acik nota HOPO olabilir
    assert _types(_mini(192, ["0 = N 1 0", "40 = N 7 0"])) == [S, H]


def test_chord_length_is_max_and_not_cut():
    notes = parse_chart(_mini(480, ["0 = N 0 10", "0 = N 3 50", "0 = N 4 20"])).tracks["expert"].notes
    assert len(notes) == 1 and notes[0].mask == 0b11001 and notes[0].length_ticks == 50
    assert notes[0].is_chord and notes[0].gem_count == 3


def test_sp_phrase_boundaries_moonscraper():
    lines = ["0 = N 0 0", "0 = S 2 192", "192 = N 1 0", "192 = S 2 0", "400 = N 2 0", "384 = S 2 16",
             "500 = N 3 0", "500 = S 2 1"]
    tr = parse_chart(_mini(192, lines)).tracks["expert"]
    # [0,192): yalniz 0 ; 0-uzunluk 192'deki notayi kapsar ; [384,400) bos -> atilir ; [500,501)
    assert [n.sp_phrase for n in tr.notes] == [0, 1, -1, 2]
    assert all(n.sp_phrase_end for n in tr.notes if n.sp_phrase >= 0)
    assert [(p.first_note, p.last_note) for p in tr.sp_phrases] == [(0, 0), (1, 1), (3, 3)]


def test_unclosed_solo_and_other_difficulties():
    text = _mini(192, ["0 = N 0 0", "100 = E solo", "200 = N 1 0", "300 = N 2 0"]) + \
        "[EasySingle]\n{\n0 = N 4 0\n}\n[HardDrums]\n{\n0 = N 0 0\n}\n"
    ch = parse_chart(text)
    assert set(ch.tracks) == {"expert", "easy"}
    assert [(s.first_note, s.last_note) for s in ch.tracks["expert"].solos] == [(1, 2)]


def test_offset_delay_and_ini_overrides():
    info = SongInfo(name="Ini Name", delay_ms=250, hopo_frequency=100)
    text = _mini(192, ["0 = N 0 0", "90 = N 1 0"], extra_song='Offset = 1.0\nName = "Chart Name"')
    ch = parse_chart(text, info)
    assert ch.offset == pytest.approx(1.25)
    assert ch.info.name == "Ini Name"
    assert [n.type for n in ch.tracks["expert"].notes] == [S, H]   # 90 <= hopo_frequency 100


def test_timesig_and_tempo_parsing():
    ch = parse_chart(_mini(192, ["0 = N 0 0"], sync="0 = TS 4\n0 = B 120000\n768 = TS 7 3\n768 = B 150325"))
    tm = ch.tempo_map
    assert (tm.timesigs[1].numerator, tm.timesigs[1].denominator) == (7, 8)
    assert tm.tempos[1].bpm == pytest.approx(150.325)


def test_song_ini_encodings(tmp_path):
    p = tmp_path / "song.ini"
    p.write_bytes("\ufeff[Song]\r\nName = Ça Marche\r\nARTIST= Bänd \r\nfrets = X\r\n[Other]\r\nname = no\r\n"
                  .encode("utf-8"))
    ini = read_song_ini(p)
    assert ini["name"] == "Ça Marche" and ini["artist"] == "Bänd" and ini["frets"] == "X"
    p.write_bytes("[song]\nname = Caf\xe9\ndelay = -120\nhopo_frequency = 170\neighthnote_hopo = 1\n"
                  "sustain_cutoff_threshold = 0\ndiff_guitar = 4\nsong_length = 1000\n".encode("cp1252"))
    info = fill_song_info(read_song_ini(p))
    assert info.name == "Café" and info.delay_ms == -120 and info.hopo_frequency == 170
    assert info.eighthnote_hopo and info.sustain_cutoff_threshold == 0
    assert info.diff_guitar == 4 and info.song_length_ms == 1000 and info.charter == ""
    assert midi_hopo_threshold(480) == 161 and midi_hopo_threshold(480, None, True) == 241


def _make_song(folder, chart_text, ini="[Song]\nname = Folder Song\nartist = Band\ndelay = 100\n"):
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "notes.chart"), "w", encoding="utf-8") as f:
        f.write(chart_text)
    if ini is not None:
        with open(os.path.join(folder, "song.ini"), "wb") as f:
            f.write(b"\xef\xbb\xbf" + ini.encode("utf-8"))
    for name in ("song.ogg", "Guitar.OGG", "rhythm.mp3", "drums_2.opus", "crowd.wav", "album.png",
                 "notes.txt", "bass.flac"):
        with open(os.path.join(folder, name), "wb") as f:
            f.write(b"x")


def test_load_song_folder(tmp_path):
    folder = tmp_path / "Band - Song"
    _make_song(str(folder), golden_chart(192))
    ch = load_song(folder)
    info = ch.info
    assert info.name == "Folder Song" and info.artist == "Band"
    assert ch.offset == pytest.approx(0.6)
    assert set(info.stems) == {"song", "guitar", "rhythm", "drums_2", "crowd"}
    assert os.path.basename(info.stems["guitar"]) == "Guitar.OGG"
    assert os.path.basename(info.album_art) == "album.png"
    assert os.path.basename(info.chart_path) == "notes.chart"
    assert info.folder == str(folder)
    assert len(ch.tracks["expert"].notes) == len(EXPECTED)


def test_scan_songs(tmp_path, monkeypatch):
    _make_song(str(tmp_path / "pack" / "A - One"), golden_chart(192), ini=None)
    _make_song(str(tmp_path / "Two"), golden_chart(480))
    _make_song(str(tmp_path / "Broken"), golden_chart(192))
    (tmp_path / "empty").mkdir()
    real = loader_mod.read_song_ini

    def flaky(path):
        if "Broken" in str(path):
            raise ValueError("bad ini")
        return real(path)

    monkeypatch.setattr(loader_mod, "read_song_ini", flaky)
    errors = []
    songs = scan_songs(tmp_path, errors)
    names = sorted(s.name for s in songs)
    assert names == ["Folder Song", "Test Song"]      # ini'siz sarki .chart [Song]'dan
    one = next(s for s in songs if s.name == "Test Song")
    assert one.artist == "Tester" and one.chart_path.endswith("notes.chart")
    assert len(errors) == 1 and "Broken" in errors[0][0] and "bad ini" in errors[0][1]
    assert loader_mod.last_scan_errors == errors
    assert scan_songs(tmp_path / "missing") == []
