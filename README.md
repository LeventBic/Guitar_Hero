# RİFF — Guitar Hero tarzı 5 perdeli ritim oyunu

Guitar Hero / Clone Hero'nun gitar ve nota mekaniğinin birebir kopyası (Python 3.14 + pygame-ce).
Kaynak araştırma: `Levo-researches/` (LeventBic/Levo-Researches → `reports/oyun/2026-09-18-gitar-ritim-oyunu-*`).
Plan: [PLAN.md](PLAN.md) · Mimari: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) · Kararlar: [docs/KARARLAR.md](docs/KARARLAR.md)

![oyun](docs/screenshots/gameplay_star_power.png)

## Oynamak
`dist\RIFF\RIFF.exe` (klasörün tamamı birlikte taşınmalı; `Songs\` exe'nin yanında).
Kendi şarkıların: Clone Hero formatındaki klasörleri (`notes.chart`/`notes.mid`, `song.ini`, `song.ogg`, `guitar.ogg`) `Songs\` içine at.

| Aksiyon | Klavye | Xbox 360 gitar |
|---|---|---|
| Perdeler (yeşil→turuncu) | 1 2 3 4 5 | A B Y X LB |
| Strum (vuruş) | Space / ↑ / ↓ | D-pad yukarı/aşağı |
| Açık nota | hiç perde basmadan Space | — |
| Star Power | H | Tilt / Back |
| Whammy | ; | Whammy çubuğu |
| Duraklat | Enter / Esc | Start |
| Tam ekran / debug | F11 / F3 | — |

Menüler: ok tuşları + Enter/Space/Esc veya GH usulü (yeşil = seç, kırmızı = geri, strum = gezin).
**Ayarlar** (tuş atama, nota hızı, ses/görüntü offset, No Fail, tam ekran): ana menü → SETTINGS, şarkı listesinde **Tab**, oyunda Esc → SETTINGS. Tuş değiştirmek için satırda Enter'a basıp yeni tuşa bas.

## Mekanik (Clone Hero / YARG değerleri)
±70 ms vuruş penceresi · tek notada anchoring, akorda tam eşleşme · doğal HOPO (`.chart` 65/192·res, `.mid` res/3+1) ve force/tap/açık notalar · strum leniency 50/25 ms, HOPO leniency 80 ms, anti-ghosting · sustain 25 puan/beat (akor çarpmaz), whammy ile SP dolumu · nota 50 puan, çarpan 1x→4x (her 10 nota), SP ×2 (8x) · SP cümlesi %25, ≥%50 aktivasyon, tam bar 8 ölçü · rock metre (No Fail varsayılan açık) · yıldızlar (0.06…1.15 × taban skor) · miss/overstrum'da gitar stem'i kısılır.

## Geliştirme
```powershell
.\.venv\Scripts\python.exe main.py                     # oyunu kaynaktan çalıştır
.\.venv\Scripts\python.exe -m pytest tests -q           # 123 test
.\.venv\Scripts\python.exe main.py --smoke              # tüm şarkı × zorluk bot ile headless
.\.venv\Scripts\python.exe main.py --song "Songs\RIFF Demo Band - Voltage Run" --diff expert --autoplay
.\.venv\Scripts\python.exe tools\make_demo_songs.py     # demo şarkıları yeniden üret (~11 s)
powershell -ExecutionPolicy Bypass -File build.ps1      # test + ikon + PyInstaller -> dist\RIFF\RIFF.exe
```
Diğer bayraklar: `--screenshot out.png --at 30`, `--screenshot-menu out.png`, `--no-bot`, `--quit-after N`, `--fps N`.
Çökme olursa `riff_crash.log` exe'nin yanına yazılır.
