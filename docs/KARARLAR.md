# Uygulama kararları (Levo-Researches R01–R16'ya ek)

| # | Karar | Gerekçe |
|---|---|---|
| D01 | **R01 sapması:** Unity 6.3 yerine Python 3.14 + pygame-ce 2.5 + numpy, PyInstaller ile `.exe` | Makinede Unity/.NET SDK yok; hedef tek gecede EXE. İki katman (R02) korunur: `gh.engine/chart/timing/models` pygame import etmez, saf ve test edilebilir → ileride C# `Riff.Core`'a birebir taşınabilir. |
| D02 | Oyun adı **RİFF** (R14) | "Guitar Hero" adı/ticari takdimi kullanılmaz; klasör adı `guitarhero` kullanıcı isteği olarak kaldı. |
| D03 | Mekanik değerleri Clone Hero/YARG varsayılanları (R05, R06): ±70 ms, 50/25, 1x→4x, SP %25/%50/8 ölçü, whammy 1/30 | Araştırmada üç implementasyonda doğrulanmış değerler. |
| D04 | Ses saati: pygame `Sound` stem'leri aynı anda başlatılır, saat `perf_counter` tabanlı monoton, `audio_offset` ile düzeltilir | pygame'de dspTime yok; tüm stem'ler RAM'de, aynı çağrıda başlar → sapma ihmal edilebilir. |
| D05 | Demo şarkılar tamamen sentezlenmiş, özgün (telif yok) | R14: lisanssız şarkı dağıtılmaz. Gitar stem'i chart'taki notaları çalar → "kaçırınca gitar kesilir" gerçekten çalışır. |
| D06 | `.mid` okuyucu kendi SMF parser'ı (bağımlılıksız) | R07 DryWetMidi C#'a özgü; Python'da mido gerekmez, format basit. |
| D07 | No Fail varsayılan açık (R13), ayarlardan kapatılabilir | — |
| D08 | ~~Klavye: A S J K L / ↑ ↓ / Space (açık nota) / H / ; / Enter~~ **DEPRECATED** → D09 | Clone Hero standardı (ek-01 §4.7). |
| D09 | Klavye (kullanıcı isteği, 2026-09-23): perdeler **1 2 3 4 5**, **Space = strum** (↑ ↓ de strum), H = SP, ; = whammy, Enter/Esc = duraklat. Ayrı açık-strum tuşu yok (açık notalar perdesiz strum ile). Ayarlar ana menü, şarkı listesi (Tab) ve duraklatma menüsünden açılır. `settings.json` v2: eski dosyaların tuşları yok sayılır. | Kullanıcı tercihi; Space açık-strum iken basılı perdeleri yok sayıp nota kaçırtıyordu. |
