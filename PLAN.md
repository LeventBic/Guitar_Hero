# Guitar Hero Klonu — Adım Adım Plan (EXE'ye kadar)

Hedef: Guitar Hero'nun **gitar + nota mekaniğini** birebir kopyalamak ve Windows `.exe` olarak paketlemek.
Teknoloji: Python 3.14 + pygame-ce (render/ses/input) + numpy (ses sentezi) + PyInstaller (exe).

Durum işaretleri: `[x]` bitti · `[~]` devam ediyor · `[ ]` bekliyor

---

## Faz 0 — Ortam
- [x] `guitarhero/` ve `guitarhero/Levo-researches/` klasörleri
- [x] Git + GitHub CLI kurulumu (winget)
- [ ] GitHub girişi (`gh auth login`, kullanıcı yapacak)
- [x] `.venv` (pygame-ce, numpy, pyinstaller)

## Faz 1 — Kaynak inceleme
- [ ] `LeventBic/Levo-Research` → guitar hero bölümünü `Levo-researches/` içine çek
- [ ] Detaylı inceleme → `docs/ANALIZ.md` (hangi mekanikler, hangi sabitler, chart formatı, varsa kod)
- [ ] Bu planı analize göre güncelle

## Faz 2 — Mimari
```
guitarhero/
  src/gh/
    config.py        # tüm sabitler (hit window, HOPO eşiği, puanlar, tuşlar)
    chart/           # .chart ve .mid okuyucular -> Song/Track/Note modelleri
    timing.py        # tick <-> saniye (tempo haritası), ses saatine senkron
    input.py         # klavye + gamepad/gitar kontrolcüsü -> 5 perde, strum, whammy, SP
    engine/          # oyun mantığı (render'dan bağımsız, test edilebilir)
      judge.py       # vuruş penceresi, akor, HOPO, overstrum, sustain
      score.py       # puan, çarpan, seri
      starpower.py   # SP faz, dolum, aktivasyon, boşalma
      rockmeter.py   # rock metre, başarısızlık
    render/          # 3D perspektif otoban, notalar, perdeler, alevler, HUD
    audio.py         # şarkı/gitar stem'i, miss'te gitar kısılması, sfx
    scenes/          # menü, şarkı seçimi, zorluk, oyun, sonuç
  songs/             # demo şarkı(lar)
  tests/
```

## Faz 3 — Chart (nota haritası)
- [ ] `.chart` okuyucu: `[Song]` (Resolution, Offset), `[SyncTrack]` (B tempo, TS ölçü), `[Events]` (section), `[ExpertSingle]`… (`N 0-4` perde, `N 5` force, `N 6` tap, `N 7` açık nota, `S 2` Star Power)
- [ ] `.mid` okuyucu (Rock Band/GH MIDI: 96-100 Expert, 84-88 Hard, 72-76 Medium, 60-64 Easy, 116 SP)
- [ ] Aynı tick'teki notaları **akor** olarak grupla
- [ ] Doğal **HOPO** hesabı: önceki notadan farklı perde + aralık ≤ eşik (res·65/192) + akor değil; force flag'i tersine çevirir
- [ ] Sustain uzunluğu, kısa sustain kırpma
- [ ] Birim testleri

## Faz 4 — Zamanlama
- [ ] Tempo haritası ile tick→saniye
- [ ] Oyun saati = ses çalma pozisyonu (+ kalibrasyon ofseti), sapma düzeltme

## Faz 5 — Girdi
- [ ] Klavye: perdeler `F1–F5` / `A S D F G` / `1–5`, strum `↑ ↓ Enter`, SP `Space/Shift`, whammy `W`
- [ ] Gamepad / USB gitar (pygame joystick; perde butonları, strum bar hat, tilt/whammy ekseni)
- [ ] Olay zaman damgaları (frame'den bağımsız hassas zamanlama)

## Faz 6 — Oyun mantığı (asıl mekanik)
- [ ] **Vuruş penceresi**: ±70 ms (ayarlanabilir), en eski vurulabilir nota öncelikli
- [ ] **Strum**: tek notada daha düşük perdeleri basılı tutmak serbest (anchoring); akorda tam eşleşme
- [ ] **HOPO / hammer-on & pull-off**: seri kırılmamışsa perde değişimi notayı vurur; HOPO'dan sonra kısa süre gelen strum overstrum sayılmaz
- [ ] **Tap** notaları: seri şartı olmadan perdeye basmak vurur
- [ ] **Overstrum**: pencerede nota yokken strum → seri sıfır, rock metre düşer
- [ ] **Miss**: pencere geçerse seri sıfır, gitar stem'i kısılır
- [ ] **Sustain**: perdeyi tutarak beat başına puan; bırakınca biter; whammy ile SP dolumu
- [ ] **Puan**: nota başına 50 (akorda her gem), sustain beat başı 25, çarpan 1x→2x(10)→3x(20)→4x(30), SP ×2 (maks 8x)
- [ ] **Star Power**: faz tamamlanınca +%25; ≥%50 iken aktive; beat başına 1/32 boşalır; SP'de notalar mavi
- [ ] **Rock metre**: vuruşta artar, miss/overstrum'da düşer; boşalırsa şarkı başarısız (No-Fail seçeneği)
- [ ] Birim testleri (sentetik girdi dizileriyle)

## Faz 7 — Görsel
- [ ] Perspektif otoban (kaybolma noktası, beat/ölçü çizgileri, hyperspeed)
- [ ] 5 renkli gem (yeşil/kırmızı/sarı/mavi/turuncu), HOPO gem (beyaz halka/küçük), tap, açık nota barı
- [ ] Sustain kuyrukları (whammy'de dalgalı), perde butonları basılı/boş görünüm
- [ ] Vuruş alevleri, hit/miss efektleri, SP otoban parlaması
- [ ] HUD: puan, çarpan halkası, seri, SP barı, rock metre, ilerleme

## Faz 8 — Ses
- [ ] `song.ogg` + `guitar.ogg` (stem'ler), miss'te gitar sesini kıs
- [ ] Strum/miss sfx (numpy ile sentezlenmiş, telif sorunu yok)
- [ ] Demo şarkı: sentezlenmiş müzik + elle yazılmış `.chart` (4 zorluk)

## Faz 9 — Akış / Menüler
- [ ] Ana menü → şarkı listesi (`songs/` taraması, `song.ini`) → zorluk → oyun → sonuç ekranı
- [ ] Duraklatma, yeniden başlat, ayarlar (tuşlar, ses gecikmesi, hız, no-fail)

## Faz 10 — EXE
- [ ] PyInstaller `.spec` (assets + songs dahil), `--windowed`, ikon
- [ ] `build.ps1` → `dist/GuitarHero/GuitarHero.exe`
- [ ] Temiz makinede çalışma testi
