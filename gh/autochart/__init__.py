"""Otomatik chart uretici (yalniz numpy; pygame IMPORT ETMEZ, deterministik).

analyze(samples, sr, progress=None) -> Analysis       tempo / vuruslar / onset'ler / bolumler (hata ayiklama)
generate_chart(samples, sr, *, title, artist, ...) -> str   Clone Hero .chart metni (4 zorluk)
estimate_difficulty(chart_text | Analysis) -> int 0..6
pick_preview_start(analysis) -> ms
"""
from .analysis import Analysis, Onset, SectionInfo, analyze
from .charter import ChartResult, estimate_difficulty, generate, generate_chart, pick_preview_start

__all__ = ["analyze", "Analysis", "Onset", "SectionInfo", "generate_chart", "generate", "ChartResult",
           "estimate_difficulty", "pick_preview_start"]
