"""The three original RIFF demo songs: harmony, arrangement and hand-written Expert lead patterns.

Lead pitch mapping (see make_demo_songs.lead_pitches): fret f in a bar = scale degree (base + f),
base = the bar's chord degree (folded near the tonic) or Section.lead_pos. So the melodic contour
follows the fret movement and riffs move diatonically with the chords.
"""
from __future__ import annotations

from charting import Section, Song

MAJOR = [0, 2, 4, 5, 7, 9, 11]
AEOLIAN = [0, 2, 3, 5, 7, 8, 10]
PHRYGIAN = [0, 1, 3, 5, 7, 8, 10]
MINOR_PENTA = [0, 3, 5, 7, 10]

ARTIST = "RIFF Demo Band"

COUNT = Section("Count In", 1, [0], [""], drums="count", bass="none", rhythm="none", fill=False, show=False)


def _end(lead: str, chord: int = 0) -> Section:
    return Section("Ending", 1, [chord], [lead], drums="end", bass="hold", rhythm="ring", pad=True,
                   fill=False, final=True, show=False)


# ---------------------------------------------------------------------------------------
# a) easy-going rock, G major, 110 BPM
# ---------------------------------------------------------------------------------------
A_INTRO = ["02:6~ 02:2 1:4 2:4", "02:6~ 02:2 1:4 0:4", "02:6~ 02:2 1:4 2:4", "2:4 1:4 0:8~"]
A_VERSE = ["0 0 1 2 - 2 1 0", "0 2 3 2 1:4~ 0:4", "0 0 1 2 - 2 1 0", "2:4 1:2 0:2 01:8~",
           "0 0 1 2 - 3 2 1", "0 2 3 2 1:4~ 0:4", "0 0 1 2 - 2 1 0", "2:4 3:2 4:2 24:8~"]
A_CHORUS = ["02:4 02:2 13:2 - 13:2 24:4", "13:4 13:2 02:2 - 02:2 01:4",
            "02:4 02:2 13:2 - 13:2 24:4", "13:4 2:2 1:2 0:8~",
            "02:4 02:2 13:2 - 13:2 24:4", "13:4 13:2 02:2 - 02:2 01:4",
            "02:4 02:2 13:2 - 13:2 24:4", "0:2 1:2 2:2 3:2 4:8~"]
A_VERSE2 = ["0 0 1 2 - 2 1 0", "0 2 3 2 1:4~ 0:4", "0 0 1 2 - 2 0:1 1:1 2:1 3:1", "4:4~ 3:2 2:2 13:8~",
            "0 0 1 2 - 3 2 1", "0 2 3 2 1:4~ 0:4", "0 0 1 2 - 2 1:1 2:1 3:1 4:1", "3:4 2:2 1:2 02:8~"]
A_BRIDGE = ["2:8~ 1:4 0:4", "2:8~ 3:4 2:4", "2:8~ 1:4 0:4", "0:2 1:2 2:2 3:2 4:8~"]
A_OUTRO = ["02:4 02:2 13:2 - 13:2 24:4", "13:4 13:2 02:2 - 02:2 01:4",
           "02:4 02:2 13:2 - 13:2 24:4", "13:4 2:2 1:2 0:8~", "0:2 1:2 2:2 3:2 2:2 1:2 0:4"]

SONG_A = Song(
    title="First Light Boulevard", artist=ARTIST, genre="Rock", bpm=110.0, tonic=67, scale=MAJOR, seed=1101,
    drive=2.6, rhythm_drive=2.0, organ=True, diff_guitar=2, preview="Chorus", art="sun",
    loading_phrase="A relaxed cruise to warm up your strumming hand.",
    sections=[
        COUNT,
        Section("Intro", 4, [0, 4, 5, 3], A_INTRO, drums="intro", bass="root4", rhythm="ring", pad=True),
        Section("Verse 1", 8, [0, 3, 0, 4, 5, 3, 0, 4], A_VERSE, drums="rock", bass="walk", rhythm="strum"),
        Section("Chorus", 8, [3, 0, 4, 5, 3, 0, 4, 4], A_CHORUS, drums="rock_open", bass="root8", rhythm="strum8", pad=True),
        Section("Verse 2", 8, [0, 3, 0, 4, 5, 3, 0, 4], A_VERSE2, drums="rock", bass="walk", rhythm="strum"),
        Section("Chorus 2", 8, [3, 0, 4, 5, 3, 0, 4, 4], A_CHORUS, drums="rock_open", bass="root8", rhythm="strum8", pad=True),
        Section("Bridge", 4, [5, 3, 1, 4], A_BRIDGE, drums="half", bass="root4", rhythm="ring", pad=True),
        Section("Outro", 5, [3, 0, 4, 5, 0], A_OUTRO, drums="rock_open", bass="root8", rhythm="strum8", pad=True),
        _end("024:16~"),
    ])

# ---------------------------------------------------------------------------------------
# b) driving hard rock, E minor, 140 BPM, guitar solo
# ---------------------------------------------------------------------------------------
B_RIFF = "01:2 01:1 01:1 01:2 12:2 01:2 01:1 01:1 2:1 3:1 4:1 3:1"
B_RIFF_END = "12:2 12:1 12:1 12:2 23:2 34:4~ 4:1 3:1 2:1 1:1"
B_INTRO = [B_RIFF, B_RIFF, B_RIFF, B_RIFF_END]
B_VERSE = ["0:2 0:1 0:1 3:2 0:2 0:1 0:1 4:2 3:2 2:2", "0:2 0:1 0:1 3:2 0:2 0:1 0:1 2:2 1:2 0:2",
           "0:2 0:1 0:1 3:2 0:2 0:1 0:1 4:2 3:2 2:2", "01:4 01:2 12:2 23:4~ 2:1 1:1 0:2"]
B_PRE = ["0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:4~",
         "4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 02:4~",
         "0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:4~",
         "01:2 01:2 12:2 12:2 23:2 23:2 34:4~"]
B_CHORUS = ["02:8~ 13:4 13:2 24:2", "13:8~ 02:4 02:2 01:2", "02:8~ 13:4 13:2 24:2", "24:12~ 3:1 2:1 1:1 0:1",
            "02:8~ 13:4 13:2 24:2", "13:8~ 02:4 02:2 01:2", "02:4 13:4 24:4 13:4", "02:16~"]
_S1 = "0:2 1:2 2:1 1:1 0:2 2:4~ 3:2 4:2"
_S2 = "4:1 3:1 2:1 1:1 4:1 3:1 2:1 1:1 0:4~ 1:2 2:2"
_S3 = "2:1 3:1 4:1 3:1 2:1 3:1 4:1 3:1 2:2 1:2 0:4~"
_S4 = "0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:4~"
_S5 = "4:2 4:1 3:1 4:2 4:1 3:1 4:2 2:2 3:4~"
_S6 = "0:1 2:1 1:1 3:1 2:1 4:1 3:1 2:1 1:1 3:1 2:1 4:1 3:4~"
_S7 = "4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:4~"
_S8 = "2:2 3:2 4:2 3:2 4:8~"
_S11 = "0:1 1:1 0:1 1:1 0:1 1:1 0:1 1:1 2:1 3:1 2:1 3:1 2:1 3:1 4:2"
_S15 = "4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1"
B_SOLO = [_S1, _S2, _S3, _S4, _S5, _S6, _S7, _S8, _S1, _S2, _S11, _S4, _S5, _S6, _S15, "4:16~"]

SONG_B = Song(
    title="Voltage Run", artist=ARTIST, genre="Hard Rock", bpm=140.0, tonic=64, scale=AEOLIAN, seed=1402,
    drive=6.0, rhythm_drive=5.0, diff_guitar=4, preview="Chorus", art="bolt",
    loading_phrase="Sixteenth-note runs hammer on by themselves. Save Star Power for the solo!",
    sections=[
        COUNT,
        Section("Intro", 4, [0, 0, 5, 6], B_INTRO, drums="drive", bass="root8", rhythm="chug8"),
        Section("Verse 1", 8, [0, 0, 5, 6, 0, 0, 3, 4], B_VERSE, drums="rock", bass="root8", rhythm="chug8"),
        Section("Pre-Chorus", 4, [5, 6, 5, 6], B_PRE, drums="build", bass="root8", rhythm="chug16"),
        Section("Chorus", 8, [5, 2, 6, 0, 5, 2, 6, 6], B_CHORUS, drums="rock_open", bass="root8", rhythm="power8", pad=True),
        Section("Verse 2", 8, [0, 0, 5, 6, 0, 0, 3, 4], B_VERSE, drums="rock", bass="root8", rhythm="chug8"),
        Section("Chorus 2", 8, [5, 2, 6, 0, 5, 2, 6, 6], B_CHORUS, drums="rock_open", bass="root8", rhythm="power8", pad=True),
        Section("Guitar Solo", 16, [0, 5, 6, 0, 3, 5, 6, 4, 0, 5, 6, 0, 3, 5, 6, 0], B_SOLO, drums="drive",
                bass="root8", rhythm="chug8", scale=MINOR_PENTA,
                lead_pos=[0, 0, 0, 0, 2, 2, 1, 1, 3, 3, 2, 2, 5, 5, 4, 1], solo=True),
        Section("Chorus 3", 8, [5, 2, 6, 0, 5, 2, 6, 6], B_CHORUS, drums="rock_open", bass="root8", rhythm="power8", pad=True),
        Section("Outro", 4, [0, 0, 5, 6], [B_RIFF, B_RIFF, B_RIFF, B_RIFF_END], drums="drive", bass="root8", rhythm="chug8"),
        _end("01:16~"),
    ])

# ---------------------------------------------------------------------------------------
# c) metal / prog, D minor, 170 BPM, 7/8 section, 130 BPM bridge, taps, opens, forced notes
# ---------------------------------------------------------------------------------------
C_N1 = "024:4 o:1 o:1 o:1 o:1 13:4 o:1 o:1 o:1 o:1"
C_N2 = "024:4 o:1 o:1 o:1 o:1 13:2 24:2 4:1 3:1 2:1 1:1"
C_N4 = "0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:4~"
C_INTRO = [C_N1, C_N2, C_N1, C_N4]
C_R1 = "o:2 o:1 o:1 0:2! o:1 o:1 1:2! o:1 o:1 0:2! 3:2!"
C_R2 = "o:2 o:1 o:1 0:2! o:1 o:1 1:2! o:1 o:1 2:1! 1:1 0:2"
C_R4 = "01:2 01:1 01:1 12:2 01:2 o:1 o:1 o:1 o:1 12:4~"
C_R7 = "02:4 13:4 24:4 o:1 o:1 o:1 o:1"
C_R8 = "01:2 12:2 23:2 34:2 4:1 3:1 2:1 1:1 0:4~"
C_VERSE = [C_R1, C_R2, C_R1, C_R4, C_R1, C_R2, C_R7, C_R8]
C_VERSE2 = [C_R1, C_R2, C_R1, C_R4,
            "0:2 1:2! 2:2! 3:2! 4:2! 3:2! 2:2! 1:2!", C_R1,
            "4:2 3:2! 2:2! 1:2! 0:2 1:2! 2:2! 3:2!", C_R8]
C_ODD = ["02:2 o:2 13:2 o:2 24:2 o:1 o:1 13:2",
         "02:2 o:2 13:2 o:2 4:1 3:1 2:1 1:1 0:2",
         "02:2 o:2 13:2 o:2 24:2 o:1 o:1 13:2",
         "0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:2~"]
C_CHORUS = ["02:6~ 02:2 13:4 24:4", "13:6~ 13:2 02:4 01:4", "02:6~ 02:2 13:4 24:4", "34:8~ 4:1 3:1 2:1 1:1 0:4",
            "02:6~ 02:2 13:4 24:4", "13:6~ 13:2 02:4 01:4", "02:4 13:4 24:4 34:4", "024:16~"]
_T1 = "0:1t 2:1t 4:1t 2:1t " * 4
_T2 = "0:1t 2:1t 4:1t 2:1t " * 2 + "4:1t 3:1t 2:1t 1:1t 0:4t~"
_T3 = "0:1t 1:1t 2:1t 3:1t 4:1t 3:1t 2:1t 1:1t 0:1t 1:1t 2:1t 3:1t 4:4t~"
C_TAP = [_T1, _T2, _T1, _T3]
C_BRIDGE = ["2:6~ 1:2! 0:8~", "0:2 1:2! 2:2! 3:2! 4:8~", "4:6~ 3:2! 2:8~", "1:4 2:4 3:4 4:4",
            "02:8~ 13:8~", "24:8~ 34:4 24:4", "2:2 3:2! 4:2! 3:2! 2:2! 1:2! 0:4~", "o:4 0:4 1:4 2:4"]
_X1 = "0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1"
_X2 = "0:1 2:1 4:1 2:1 1:1 3:1 4:1 3:1 2:1 4:1 3:1 2:1 1:4~"
_X3 = "4:1t 2:1t 0:1t 2:1t 4:1t 2:1t 0:1t 2:1t 4:1t 3:1t 2:1t 1:1t 0:4~"
_X4 = "02:2 13:2 24:2 13:2 02:2 o:1 o:1 o:1 o:1 0:2"
_X5 = "4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1 4:1 3:1 2:1 1:1 0:1 1:1 2:1 3:1"
_X6 = "4:2 3:1 4:1 3:1 2:1 3:1 2:1 1:1 2:1 1:1 0:1 1:4~"
_X7 = "0:1t 2:1t 4:1t 2:1t " * 2 + "1:1t 3:1t 4:1t 3:1t " * 2
_X8 = "0:1 1:1 2:1 3:1 4:1 3:1 2:1 3:1 4:8~"
C_SOLO = [_X1, _X2, _X3, _X4, _X5, _X6, _X7, _X8, _X1, _X2, _X3, _X4, _X5, _X6, _X7, "0:1 1:1 2:1 3:1 4:12~"]
C_CHORUS2 = C_CHORUS[:7] + ["024:8~ o:1 o:1 o:1 o:1 o:4"]

SONG_C = Song(
    title="Fractal Engine", artist=ARTIST, genre="Progressive Metal", bpm=170.0, tonic=62, scale=AEOLIAN, seed=1703,
    drive=8.0, rhythm_drive=7.0, diff_guitar=6, preview="Chorus", art="fractal",
    loading_phrase="7/8, a slow bridge, taps and open notes. Good luck.",
    sections=[
        COUNT,
        Section("Intro", 4, [0, 5, 6, 4], C_INTRO, drums="metal_half", bass="follow", rhythm="chug16"),
        Section("Verse 1", 8, [0, 0, 0, 1, 0, 0, 5, 1], C_VERSE, drums="metal", bass="follow", rhythm="chug16",
                scale=PHRYGIAN),
        Section("Odd Time", 8, [0, 5, 6, 4, 0, 5, 2, 4], C_ODD, drums="odd", bass="follow", rhythm="chug8", ts=(7, 8)),
        Section("Chorus", 8, [0, 5, 2, 6, 0, 5, 6, 4], C_CHORUS, drums="metal_open", bass="root8", rhythm="power8",
                pad=True, ts=(4, 4)),
        Section("Verse 2", 8, [0, 0, 0, 1, 0, 0, 5, 1], C_VERSE2, drums="metal", bass="follow", rhythm="chug16",
                scale=PHRYGIAN),
        Section("Tap Break", 8, [0, 5, 6, 4, 0, 5, 2, 4], C_TAP, drums="metal", bass="root8", rhythm="chug8", pad=True),
        Section("Bridge", 8, [3, 0, 5, 4, 3, 0, 5, 4], C_BRIDGE, drums="half", bass="root4", rhythm="ring", pad=True,
                bpm=130.0),
        Section("Guitar Solo", 16, [0, 5, 6, 4, 0, 5, 2, 4, 0, 5, 6, 4, 0, 5, 6, 0], C_SOLO, drums="metal",
                bass="follow", rhythm="chug16", bpm=170.0, solo=True,
                lead_oct=[0, 0, 0, 0, 0, 0, 0, 0, 1, 1, 1, 1, 1, 1, 1, 1]),
        Section("Chorus 2", 8, [0, 5, 2, 6, 0, 5, 6, 4], C_CHORUS2, drums="metal_open", bass="root8", rhythm="power8",
                pad=True),
        Section("Outro", 4, [0, 5, 6, 4], [C_N1, C_N2, C_N1, C_N4], drums="metal_half", bass="follow", rhythm="chug16"),
        _end("024:16~"),
    ])

SONGS = [SONG_A, SONG_B, SONG_C]
