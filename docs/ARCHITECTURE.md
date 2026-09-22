# RİFF — Mimari ve Modül Sözleşmeleri

Kaynak araştırma: `Levo-researches/reports/oyun/2026-09-18-gitar-ritim-oyunu-mimari-ve-sprint.md` (+ `...-ekler/ek-01-yazilim-mimari-arastirmasi.md`).
Araştırmanın mimarisi (R02 iki katman, R03 ses saati, R05–R07 mekanik değerleri, R08 klasör, R09 girdi olayı, R14 isim) **korunur**.
Tek sapma: **R01 Unity yerine Python 3.14 + pygame-ce** (bkz. `docs/KARARLAR.md` D01).

## Katmanlar

```
gh/                      (paket; "Riff.Core" karşılığı = config, timing, models, chart/, engine/  -> pygame IMPORT ETMEZ)
  config.py              sabitler (EngineConfig, KeyConfig, ...)           [yazıldı]
  timing.py              TempoMap: tick<->saniye, beat/ölçü konumu, beatline [yazıldı]
  models.py              Note, Track, Chart, SongInfo, SPPhrase, Solo       [yazıldı]
  chart/                 parser'lar                                          [Ajan A]
    chart_parser.py      parse_chart(path_or_text, cfg) -> Chart
    midi_parser.py       parse_midi(path, cfg, ini) -> Chart (kendi SMF okuyucusu, bağımlılıksız)
    song_ini.py          read_song_ini(path) -> dict
    hopo.py              resolve_note_types(notes, threshold_ticks, ...) (ortak HOPO/akor mantığı)
    loader.py            load_song(folder) -> Chart ; scan_songs(root) -> list[SongInfo]
  engine/                oyun mantığı (deterministik, saf)                  [Ajan B]
    input_event.py       InputEvent, InputKind
    events.py            GameEvent, EvType
    guitar_engine.py     GuitarEngine
    scoring.py           taban skor / yıldız hesabı
  --- ön yüz (pygame) ---                                                    [Ajan D]
  audio.py               Conductor (ses saati), stem çalma, gitar kısma, sfx
  input.py               klavye + joystick -> InputEvent (zaman damgalı)
  render/                highway, gem, sustain, perde butonları, efektler, HUD
  scenes/                menü, şarkı listesi, zorluk, oyun, duraklatma, sonuç, kalibrasyon, ayarlar
  settings_store.py      settings.json oku/yaz
  sfx.py                 numpy ile sentezlenmiş efekt sesleri                [Ajan C]
main.py                  giriş noktası
tools/make_demo_songs.py demo şarkı üretici (müzik + chart)                  [Ajan C]
Songs/                   Clone Hero uyumlu şarkı klasörleri (demo şarkılar burada)
tests/                   pytest
```

## Zaman kavramları
- **chart saniyesi**: `TempoMap.tick_to_time(tick)`; `Note.time` bu birimdedir.
- **SongTime** (yargı): `ses_pozisyonu - chart.offset - audio_offset`. Motor sadece bunu görür.
- **VisualTime** (çizim): `SongTime + video_offset`.
- Girdi olayı zamanı: olayın gerçek zaman damgası SongTime'a çevrilmiş halidir (frame zamanı değil).

## Motor API (Ajan B uygular, Ajan D kullanır)

```python
# gh/engine/input_event.py
class InputKind(IntEnum):
    FRET_DOWN = 0; FRET_UP = 1; STRUM = 2; OPEN_STRUM = 3; WHAMMY = 4; STAR_POWER = 5
@dataclass
class InputEvent:
    time: float           # SongTime (saniye)
    kind: InputKind
    fret: int = -1        # FRET_DOWN/UP için 0..4
    value: float = 0.0    # WHAMMY için 0..1 (klavyede basılı=1, bırak=0)

# gh/engine/events.py
class EvType(IntEnum):
    HIT; MISS; OVERSTRUM; SUSTAIN_START; SUSTAIN_END; SP_PHRASE_COMPLETE; SP_PHRASE_FAILED;
    SP_ACTIVATED; SP_ENDED; MULTIPLIER_CHANGED; COMBO_BROKEN; FAILED; SOLO_START; SOLO_END
@dataclass
class GameEvent:
    type: EvType
    time: float
    note: int = -1        # not indeksi
    mask: int = 0
    offset: float = 0.0   # HIT: vuruş - nota zamanı (negatif = erken)
    value: float = 0.0    # MULTIPLIER_CHANGED: yeni çarpan; SUSTAIN_END: 1=tamamlandı 0=bırakıldı; SOLO_END: yüzde

# gh/engine/guitar_engine.py
class GuitarEngine:
    def __init__(self, chart: Chart, track: Track, cfg: EngineConfig): ...
    def reset(self) -> None
    def push(self, ev: InputEvent) -> None        # zaman sıralı gelir
    def update(self, song_time: float) -> None    # kuyruğu ve zaman aşımlarını song_time'a kadar KRONOLOJİK işler
    def pop_events(self) -> list[GameEvent]
    # salt-okunur durum
    score: int; combo: int; max_combo: int
    multiplier: int            # SP dahil (1..8)
    sp_meter: float            # 0..1
    sp_active: bool
    rock_meter: float          # 0..1
    failed: bool
    held_mask: int             # basılı perdeler
    whammy_active: bool
    note_state: list[int]      # 0 bekliyor, 1 vuruldu, 2 kaçtı  (track.notes ile aynı indeks)
    sustaining: dict[int, float]  # aktif sustain: not indeksi -> başlangıç
    sp_phrase_ok: list[bool]   # cümle hâlâ tamamlanabilir mi (render: SP notaları beyaz/mavi)
    notes_hit: int; notes_missed: int; overstrums: int; total_notes: int
    hit_offsets: list[float]   # histogram için
    base_score: int            # FC + tüm sustain + SP'siz taban skor (yıldızlar için)
    def stars(self) -> float   # 0..6 (6 = altın), kesirli
    def activate_star_power(self, t: float) -> bool   # STAR_POWER girdisiyle de tetiklenir
```

## Mekanik kuralları (özet, detay ek-01 §1.7, §1.8, §5.4, §5.5)
- Pencere: `cfg.window_front` / `cfg.window_back` (±70 ms).
- Strum: en eski bekleyen nota pencerede ve perde eşleşiyorsa vurulur.
  - Tek nota: en yüksek basılı perde == nota perdesi (alttakiler serbest, "anchoring").
  - Akor: basılı maske == akor maskesi (tam eşleşme).
  - Açık nota: hiç perde basılı değil (veya OPEN_STRUM tuşu: perdeler yok sayılır).
  - `strum_leniency` (50 ms): pencerede nota yoksa strum hemen overstrum olmaz; bu süre içinde nota pencereye girer ve perdeler eşleşirse vurur, yoksa süre dolunca OVERSTRUM.
  - `strum_leniency_small` (25 ms): strum'dan kısa süre sonra perde değişip eşleşirse aynı strum geçerli.
- HOPO: combo > 0 ise perde değişimi (basma/bırakma) eşleşmeyi sağladığında vurulur. Combo 0 ise strum gerekir.
- Tap: combo şartı yok; perde eşleşince vurulur.
- `hopo_leniency` (80 ms): HOPO/tap perdeyle vurulduktan sonraki strum tüketilir (overstrum değil).
- Anti-ghosting: HOPO/tap için, yanlış (gereksiz yüksek) perdeye basılması o basışla vurmayı engeller.
- Overstrum: combo sıfırlanır, aktif SP cümlesi iptal, rock metre `miss × 0.333`, puan düşmez.
- Miss: nota `time + window_back`'i geçerse. Combo sıfır, SP cümlesi iptal, rock metre düşer.
- Sustain: vurulan sustain notasının perdeleri tutuldukça beat başına 25 × çarpan (akor çarpmaz, yukarı yuvarla); `sustain_drop_leniency` 25 ms.
- Whammy: SP cümlesindeki sustain tutulurken whammy (son hareketten `whammy_buffer` 250 ms) → beat başına bar'ın 1/30'u.
- Star Power: cümle tamamlanınca +0.25 (maks 1); ≥0.5 iken aktive; aktifken bar 8 ölçüde boşalır (`TempoMap.measure_position`); çarpan ×2; aktifken tekrar dolabilir.
- Çarpan: `min(combo // 10 + 1, 4)`, notanın puanı vuruştan ÖNCEKİ combo ile hesaplanır (10. nota 1x, 11. nota 2x).
- Rock metre: başlangıç 0.833; miss −1/42; isabet +1/168 (SP aktif ×5); ≤0 → FAILED (no_fail kapalıysa).
- Yıldızlar: `base_score × (0.06, 0.12, 0.20, 0.47, 0.78, 1.15)`.

## Şarkı klasörü (R08, Clone Hero uyumlu)
`Songs/<Sanatçı - Şarkı>/notes.chart | notes.mid`, `song.ini`, `song.ogg` (gitarsız mix), `guitar.ogg` (izole gitar), opsiyonel `rhythm/bass/keys/drums*/vocals/crowd` + `album.png`. Ses uzantıları: `.ogg .opus .mp3 .wav`.
