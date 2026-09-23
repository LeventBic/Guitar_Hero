"""Motor, taban skor ve autoplay tarafindan paylasilan saf kural yardimcilari."""
from __future__ import annotations

from ..config import EngineConfig
from ..models import Note


def is_chord_mask(mask: int) -> bool:
    return bool(mask & (mask - 1))


def matches(note_mask: int, held: int) -> bool:
    """Basili perde durumu notayi karsiliyor mu (Clone Hero kurali).

    Acik nota: hic perde yok. Akor: tam esleme. Tek nota: en yuksek basili perde == nota perdesi
    (alttaki perdeler serbest = anchoring).
    """
    if note_mask == 0:
        return held == 0
    if is_chord_mask(note_mask):
        return held == note_mask
    return held != 0 and held.bit_length() == note_mask.bit_length()


def is_ghost_press(note_mask: int, fret: int) -> bool:
    """Anti-ghosting: bu perdeye basmak hedef HOPO/tap icin 'yanlis' mi?

    Tek notada nota perdesinden yuksek bir perde, akorda akorda olmayan bir perde, acik notada her perde.
    Alttaki perdeye basmak (anchoring hazirligi) ghost sayilmaz.
    """
    if note_mask == 0:
        return True
    if is_chord_mask(note_mask):
        return not (note_mask >> fret) & 1
    return fret > note_mask.bit_length() - 1


def sustain_compatible(sus_mask: int, next_mask: int) -> bool:
    """Bir sustain tutulurken sonraki nota ayni anda calinabilir mi (extended sustain)."""
    if sus_mask == 0 or next_mask == 0:
        return False
    if is_chord_mask(next_mask):
        return sus_mask & ~next_mask == 0
    return sus_mask.bit_length() <= next_mask.bit_length()


def sustain_ends(notes: list[Note]) -> tuple[list[float], list[int]]:
    """Her notanin etkin sustain bitisi ve (varsa) sustain'i kesen notanin indeksi.

    Sustain'in suresi icine perdeleri catisan bir nota dusuyorsa sustain o notada biter
    (Clone Hero: sonraki nota calinirken catisan sustain kesilir). Uyumlu notalar (alt perde tutulurken
    ust perdede calinan notalar) sustain'i kesmez = extended sustain.
    """
    ends: list[float] = []
    cuts: list[int] = []
    n = len(notes)
    for i, note in enumerate(notes):
        if not note.has_sustain:
            ends.append(note.time)
            cuts.append(-1)
            continue
        end = note.end_time
        cut = -1
        j = i + 1
        while j < n and notes[j].time < end:
            if not sustain_compatible(note.mask, notes[j].mask):
                cut = j
                end = notes[j].time
                break
            j += 1
        ends.append(end)
        cuts.append(cut)
    return ends, cuts


def multiplier_for_combo(combo: int, cfg: EngineConfig) -> int:
    return min(combo // cfg.streak_per_multiplier + 1, cfg.max_multiplier)
