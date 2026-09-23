import os

import pytest

from gh.chart import load_song, parse_chart, parse_midi
from gh.chart.midi_parser import read_midi
from gh.models import NoteType, SongInfo

from test_chart_parser import EXPECTED, golden_chart

S, H, T = NoteType.STRUM, NoteType.HOPO, NoteType.TAP


# --- minik SMF yazici ------------------------------------------------------------

def vlq(n: int) -> bytes:
    out = [n & 0x7F]
    n >>= 7
    while n:
        out.append(0x80 | (n & 0x7F))
        n >>= 7
    return bytes(reversed(out))


def meta(tick, mtype, data: bytes):
    return (tick, b"\xff" + bytes([mtype]) + vlq(len(data)) + data)


def text(tick, s, mtype=0x01):
    return meta(tick, mtype, s.encode("ascii"))


def note(tick, num, length, vel=100, ch=0):
    return [(tick, bytes([0x90 | ch, num, vel])), (tick + length, bytes([0x80 | ch, num, 0]))]


def tempo(tick, bpm):
    return meta(tick, 0x51, int(round(60_000_000 / bpm)).to_bytes(3, "big"))


def track(name, events):
    evs = ([meta(0, 0x03, name.encode("ascii"))] if name else []) + sorted(events, key=lambda e: e[0])
    body = b""
    last = 0
    for tick, data in evs:
        body += vlq(tick - last) + data
        last = tick
    body += b"\x00\xff\x2f\x00"
    return b"MTrk" + len(body).to_bytes(4, "big") + body


def smf(tracks, division=480, fmt=1):
    return b"MThd" + (6).to_bytes(4, "big") + fmt.to_bytes(2, "big") + len(tracks).to_bytes(2, "big") + \
        division.to_bytes(2, "big") + b"".join(tracks)


def conductor(res=480):
    return track("tempo", [tempo(0, 120), meta(0, 0x58, bytes([4, 2, 24, 8])), tempo(4 * res, 150)])


def golden_midi(res=480):
    """test_chart_parser.golden_chart ile ayni notalar (.mid kurallariyla)."""
    k = res / 192

    def t(x):
        return int(x * k)

    E = 96
    ev = [text(0, "[ENHANCED_OPENS]")]
    ev += note(t(0), E, 10)                       # 10 tick < cutoff -> 0
    ev += note(t(192), E + 1, t(96))
    ev += note(t(256), E + 2, 5)
    ev += note(t(384), E, t(192)) + note(t(384), E + 1, 1)
    ev += note(t(448), E + 1, 1)
    ev += note(t(512), E + 3, 1)
    ev += note(t(576), E + 3, 1)
    ev += note(t(768), E - 1, 1)                  # acik nota
    ev += note(t(800), E, 1) + note(t(800), E + 6, 1)       # force strum
    ev += note(t(960), E + 4, 1) + note(t(960), E + 5, 1)   # force HOPO
    ev += note(t(1152), E + 2, 1) + note(t(1152), 104, 1)   # tap
    ev += note(t(384), 116, t(192))              # SP [384, 576)
    ev += note(t(1500), 116, t(50))              # notasiz SP
    ev += note(t(768), 103, t(192) + 1)          # solo
    events = track("EVENTS", [text(0, "[section Intro]"), text(t(768), "[section Verse 1]"),
                              text(t(960), "[prc_chorus_a]"), text(t(3072), "[end]")])
    bass = track("PART BASS", note(0, 100, 10))
    return smf([conductor(res), events, bass, track("PART GUITAR", ev)], res)


def test_midi_matches_chart():
    res = 480
    ch_mid = parse_midi(golden_midi(res))
    ch_chart = parse_chart(golden_chart(res))
    a = ch_mid.tracks["expert"]
    b = ch_chart.tracks["expert"]
    assert list(ch_mid.tracks) == ["expert"]
    key = lambda n: (n.tick, n.mask, n.type, n.length_ticks, round(n.time, 9), round(n.end_time, 9),
                     n.sp_phrase, n.sp_phrase_end, n.index)
    assert [key(n) for n in a.notes] == [key(n) for n in b.notes]
    assert [(p.first_note, p.last_note, p.tick) for p in a.sp_phrases] == \
        [(p.first_note, p.last_note, p.tick) for p in b.sp_phrases]
    assert [(s.first_note, s.last_note) for s in a.solos] == [(s.first_note, s.last_note) for s in b.solos]
    assert [(s.name, s.tick) for s in ch_mid.sections] == [(s.name, s.tick) for s in ch_chart.sections]
    assert ch_mid.end_time == pytest.approx(ch_chart.end_time)
    assert ch_mid.resolution == res
    assert ch_mid.offset == 0.0


def _guitar(events, res=480, info=None, name="PART GUITAR"):
    return parse_midi(smf([conductor(res), track(name, events)], res), info)


def test_sustain_cutoff():
    ev = note(0, 96, 160) + note(1000, 97, 161) + note(2000, 98, 500)
    notes = _guitar(ev).tracks["expert"].notes
    assert [n.length_ticks for n in notes] == [0, 161, 500]
    assert notes[0].end_time == notes[0].time
    # song.ini sustain_cutoff_threshold ezer
    notes = _guitar(ev, info=SongInfo(sustain_cutoff_threshold=300)).tracks["expert"].notes
    assert [n.length_ticks for n in notes] == [0, 0, 500]


def test_midi_hopo_threshold_and_overrides():
    ev = note(0, 96, 1) + note(161, 97, 1) + note(323, 98, 1)
    assert [n.type for n in _guitar(ev).tracks["expert"].notes] == [S, H, S]
    assert [n.type for n in _guitar(ev, info=SongInfo(hopo_frequency=170)).tracks["expert"].notes] == [S, H, H]
    ev = note(0, 96, 1) + note(241, 97, 1)
    assert [n.type for n in _guitar(ev).tracks["expert"].notes] == [S, S]
    assert [n.type for n in _guitar(ev, info=SongInfo(eighthnote_hopo=True)).tracks["expert"].notes] == [S, H]


def test_force_markers_ranges_and_difficulties():
    ev = []
    ev += note(0, 96, 1) + note(0, 97, 1)                 # akor
    ev += note(100, 96, 1)                                # akordaki perde -> dogal strum
    ev += note(0, 101, 150)                               # force HOPO [0,150): akor + 100
    ev += note(1000, 96, 1) + note(1080, 97, 1)           # dogal HOPO
    ev += note(1000, 102, 200)                            # force strum [1000,1200)
    ev += note(0, 60, 1) + note(400, 61, 1) + note(400, 65, 1)  # easy: force HOPO notanin tick'inde
    ch = _guitar(ev)
    assert [n.type for n in ch.tracks["expert"].notes] == [H, H, S, S]
    assert [n.type for n in ch.tracks["easy"].notes] == [S, H]
    assert set(ch.tracks) == {"expert", "easy"}


def test_tap_marker_and_solo_sp():
    ev = note(0, 96, 1) + note(500, 97, 1) + note(1000, 98, 1) + note(1000, 99, 1)
    ev += note(400, 104, 700)                              # tap [400,1100): tek nota + akor
    ev += note(0, 103, 1000)                               # solo [0,1000): 1000 dahil degil
    ev += note(0, 116, 501)
    tr = _guitar(ev).tracks["expert"]
    assert [n.type for n in tr.notes] == [S, T, T]
    assert [(s.first_note, s.last_note) for s in tr.solos] == [(0, 1)]
    assert [n.sp_phrase for n in tr.notes] == [0, 0, -1] and tr.notes[1].sp_phrase_end
    # multiplier_note = 103 -> 103 SP olur, solo yok
    tr = _guitar(ev, info=SongInfo(multiplier_note=103)).tracks["expert"]
    assert tr.solos == [] and [n.sp_phrase for n in tr.notes] == [0, 0, -1]


def test_enhanced_opens_required():
    ev = note(0, 95, 1) + note(480, 96, 1)
    assert [n.mask for n in _guitar(ev).tracks["expert"].notes] == [1]
    ev2 = ev + [text(0, "[ENHANCED_OPENS]")]
    notes = _guitar(ev2).tracks["expert"].notes
    assert [n.mask for n in notes] == [0, 1] and notes[0].is_open
    # acik + perdeli ayni tick: acik atilir
    ev3 = ev2 + note(480, 95, 1)
    assert [n.mask for n in _guitar(ev3).tracks["expert"].notes] == [0, 1]


def test_running_status_velocity_zero_and_t1_gems():
    # elle: running status + hiz 0 note-off, T1 GEMS adi, sysex atlama
    body = b"\x00\xff\x03\x07T1 GEMS"
    body += b"\x00\xf0\x03\x7e\x7f\xf7"                  # sysex (atlanir)
    body += b"\x00\x90\x60\x64"                           # note on 96
    body += b"\x00\x61\x64"                               # running status: note on 97
    body += b"\x83\x60\x60\x00"                           # delta 480, 96 off (vel 0)
    body += b"\x00\x61\x00"                               # 97 off
    body += b"\x00\xff\x01\x03abc"                        # text meta
    body += b"\x00\x62\x64"                               # meta sonrasi running status (toleransli)
    body += b"\x10\x62\x00"
    body += b"\x00\xff\x2f\x00"
    trk = b"MTrk" + len(body).to_bytes(4, "big") + body
    mid = smf([trk], 480, fmt=0)
    parsed = read_midi(mid)
    assert parsed.tracks[0].name == "T1 GEMS" and len(parsed.tracks[0].notes) == 6
    notes = parse_midi(mid).tracks["expert"].notes
    assert [(n.tick, n.mask, n.length_ticks) for n in notes] == [(0, 0b11, 480), (480, 0b100, 0)]
    assert notes[0].end_time == pytest.approx(0.5)   # tempo yok -> 120 BPM


def test_retrigger_same_tick_and_zero_length():
    # 96: [0,480) sonra ayni tick'te on-once/off-sonra sirasiyla yeniden [480, 960)
    ev = [(0, bytes([0x90, 96, 100])), (480, bytes([0x90, 96, 100])), (480, bytes([0x80, 96, 0])),
          (960, bytes([0x80, 96, 0]))]
    ev += [(1500, bytes([0x90, 97, 100])), (1500, bytes([0x80, 97, 0]))]   # 0 uzunluk
    notes = _guitar(ev).tracks["expert"].notes
    assert [(n.tick, n.length_ticks) for n in notes] == [(0, 480), (480, 480), (1500, 0)]


def test_ps_sysex_tap_and_open():
    def ps(tick, diff, kind, on):
        payload = bytes([0x50, 0x53, 0, 0, diff, 1, kind, on, 0xF7])
        return (tick, b"\xf0" + vlq(len(payload)) + payload)

    ev = note(0, 96, 1) + note(480, 96, 1) + note(960, 97, 1)
    ev += [ps(0, 3, 1, 1), ps(10, 3, 1, 0), ps(960, 0xFF, 4, 1), ps(970, 0xFF, 4, 0)]
    notes = _guitar(ev).tracks["expert"].notes
    assert [(n.mask, n.type) for n in notes] == [(0, S), (1, S), (0b10, T)]


def test_load_song_prefers_mid(tmp_path):
    folder = tmp_path / "Both"
    folder.mkdir()
    (folder / "notes.chart").write_text(golden_chart(192), encoding="utf-8")
    (folder / "NOTES.MID").write_bytes(golden_midi(480))
    (folder / "song.ini").write_text("[song]\nname = Mid Song\ndelay = -50\n", encoding="utf-8")
    ch = load_song(folder)
    assert ch.resolution == 480 and ch.info.name == "Mid Song"
    assert ch.offset == pytest.approx(-0.05)
    assert os.path.basename(ch.info.chart_path) == "NOTES.MID"
    assert len(ch.tracks["expert"].notes) == len(EXPECTED)
