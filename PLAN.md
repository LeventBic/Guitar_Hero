# RİFF (Guitar Hero klonu) — Adım Adım Plan (EXE'ye kadar)

Kaynak: `Levo-researches/reports/oyun/2026-09-18-gitar-ritim-oyunu-*` (LeventBic/Levo-Researches, sparse checkout).
Hedef: Guitar Hero / Clone Hero'nun **gitar + nota mekaniğini** birebir kopyalamak ve Windows `.exe` olarak paketlemek.
Yığın: Python 3.14 + pygame-ce + numpy + PyInstaller (Unity sapması için bkz. `docs/KARARLAR.md` D01).
Mimari ve modül sözleşmeleri: `docs/ARCHITECTURE.md`.

Durum: `[x]` bitti · `[x]` devam ediyor · `[ ]` bekliyor · (A/B/C/D = alt ajan)

## Faz 0 — Ortam
- [x] `guitarhero/` + `.venv` (pygame-ce 2.5.8, numpy, pyinstaller 6.22, pytest, soundfile)
- [x] Git + GitHub CLI kurulumu, GitHub girişi
- [x] Levo-Researches → `Levo-researches/` (yalnız gitar ritim oyunu raporları, sparse checkout)

## Faz 1 — İnceleme
- [x] Ana rapor (R01–R16, S00–S06) ve ek-01 mekanik bölümleri (§1.7 pencere/leniency, §1.8 nota kuralları, §2 formatlar, §4.7 klavye, §5.4 skor, §5.5 rock metre) okundu
- [x] Değerler `gh/config.py`'ye işlendi; kararlar `docs/KARARLAR.md`

## Faz 2 — Çekirdek (pygame'siz, test edilebilir) — S00/S01/S02 kapsamı
- [x] `timing.py` TempoMap, `models.py`
- [x] (A) `.chart` + `.mid` + `song.ini` okuyucu, HOPO çözücü, şarkı tarayıcı + testler
- [x] (B) GuitarEngine: pencere, strum/HOPO/tap/açık, anchoring, akor, leniency'ler, anti-ghosting, sustain, whammy, Star Power, çarpan, rock metre, yıldızlar, autoplay botu + testler
- [x] (C) Demo içerik: 3 özgün sentez şarkı (stem'li: song.ogg + guitar.ogg), 4 zorluk chart'ı, efekt sesleri

## Faz 3 — Ön yüz (pygame) — (D)
- [x] Conductor: ses saati, stem'ler, miss'te gitar kısılması, audio/video offset
- [x] Girdi: klavye (A S J K L, ↑↓, Space, H, ;, Enter) + joystick/gitar kontrolcüsü, zaman damgalı olaylar
- [x] Highway: perspektif otoban, beatline'lar, gem'ler (strum/HOPO/tap/açık/SP), sustain kuyrukları (whammy dalgası), perde butonları, alevler
- [x] HUD: skor, çarpan, combo, SP barı, rock metre, ilerleme, solo yüzdesi
- [x] Sahneler: ana menü, şarkı listesi, zorluk, geri sayım, duraklatma, sonuç (yıldız, isabet, histogram), kalibrasyon, ayarlar (tuş atama, hız, offset, no-fail)

## Faz 4 — Doğrulama
- [x] Tüm testler yeşil
- [x] Headless duman testi: her şarkı × her zorluk bot ile baştan sona → full combo
- [x] Ekran görüntüsü ile görsel kontrol

## Faz 5 — EXE
- [x] `RIFF.spec` + `build.ps1` → `dist/RIFF/RIFF.exe` (+ `Songs/` yanında)
- [x] EXE duman testi (açılış, şarkı yükleme)

## Sonuç (2026-09-23)
- 123 test yeşil; bot 3 şarkı × 4 zorlukta full combo (kaynak ve EXE); ~645 FPS uncapped
- `dist\RIFF\RIFF.exe` (73 MB, onedir, `Songs\` yanında)
- Açık: gerçek gitar kontrolcüsü donanımla test edilmedi; pygame olay zaman damgası vermediği için girdi ~1 kHz poll (±1 ms)
