"""Chart okuma katmani (pygame IMPORT ETMEZ).

load_song(folder) -> Chart ; scan_songs(root, errors=None) -> list[SongInfo]
(tarama hatalari: `gh.chart.loader.last_scan_errors` / `gh.chart.last_scan_errors`, [(klasor, mesaj)])
parse_chart(path_or_text, info=None) -> Chart ; parse_midi(path_or_bytes, info=None) -> Chart
read_song_ini(path) -> dict ; fill_song_info(ini, info=None) -> SongInfo
"""
from .chart_parser import parse_chart
from .loader import last_scan_errors, load_song, scan_songs
from .midi_parser import MidiError, parse_midi
from .song_ini import fill_song_info, read_song_ini

__all__ = ["load_song", "scan_songs", "parse_chart", "parse_midi", "read_song_ini", "fill_song_info",
           "last_scan_errors", "MidiError"]
