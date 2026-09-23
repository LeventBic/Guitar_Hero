# RİFF (Guitar Hero klonu) — Adım Adım Plan (EXE'ye kadar)

Kaynak: `Levo-researches/reports/oyun/2026-09-18-gitar-ritim-oyunu-*` (LeventBic/Levo-Researches, sparse checkout).
Hedef: Guitar Hero / Clone Hero'nun **gitar + nota mekaniğini** birebir kopyalamak ve Windows `.exe` olarak paketlemek.
Yığın: Python 3.14 + pygame-ce + numpy + PyInstaller (Unity sapması için bkz. `docs/KARARLAR.md` D01).
Mimari ve modül sözleşmeleri: `docs/ARCHITECTURE.md`.

Durum: `[x]` bitti · `[~]` devam ediyor · `[ ]` bekliyor · (A/B/C/D = alt ajan)

## Faz 0 — Ortam
- [x] `guitarhero/` + `.venv` (pygame-ce 2.5.8, numpy, pyinstaller 6.22, pytest, soundfile)
- [x] Git + GitHub CLI kurulumu, GitHub girişi
- [x] Levo-Researches → `Levo-researches/` (yalnız gitar ritim oyunu raporları, sparse checkout)

## Faz 1 — İnceleme
- [x] Ana rapor (R01–R16, S00–S06) ve ek-01 mekanik bölümleri (§1.7 pencere/leniency, §1.8 nota kuralları, §2 formatlar, §4.7 klavye, §5.4 skor, §5.5 rock metre) okundu
- [x] Değerler `gh/config.py`'ye işlendi; kararlar `docs/KARARLAR.md`

## Faz 2 — Çekirdek (pygame'siz, test edilebilir) — S00/S01/S02 kapsamı
- [x] `timing.py` TempoMap, `models.py`
- [~] (A) `.chart` + `.mid` + `song.ini` okuyucu, HOPO çözücü, şarkı tarayıcı + testler
- [~] (B) GuitarEngine: pencere, strum/HOPO/tap/açık, anchoring, akor, leniency'ler, anti-ghosting, sustain, whammy, Star Power, çarpan, rock metre, yıldızlar, autoplay botu + testler
- [~] (C) Demo içerik: 3 özgün sentez şarkı (stem'li: song.ogg + guitar.ogg), 4 zorluk chart'ı, efekt sesleri

## Faz 3 — Ön yüz (pygame) — (D)
- [ ] Conductor: ses saati, stem'ler, miss'te gitar kısılması, audio/video offset
- [ ] Girdi: klavye (A S J K L, ↑↓, Space, H, ;, Enter) + joystick/gitar kontrolcüsü, zaman damgalı olaylar
- [ ] Highway: perspektif otoban, beatline'lar, gem'ler (strum/HOPO/tap/açık/SP), sustain kuyrukları (whammy dalgası), perde butonları, alevler
- [ ] HUD: skor, çarpan, combo, SP barı, rock metre, ilerleme, solo yüzdesi
- [ ] Sahneler: ana menü, şarkı listesi, zorluk, geri sayım, duraklatma, sonuç (yıldız, isabet, histogram), kalibrasyon, ayarlar (tuş atama, hız, offset, no-fail)

## Faz 4 — Doğrulama
- [ ] Tüm testler yeşil
- [ ] Headless duman testi: her şarkı × her zorluk bot ile baştan sona → full combo
- [ ] Ekran görüntüsü ile görsel kontrol

## Faz 5 — EXE
- [ ] `RIFF.spec` + `build.ps1` → `dist/RIFF/RIFF.exe` (+ `Songs/` yanında)
- [ ] EXE duman testi (açılış, şarkı yükleme)
