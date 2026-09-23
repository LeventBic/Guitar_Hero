"""Arayuz dili (Turkce / English): basit anahtar -> {dil: metin} tablosu.

t(key, **fmt)   gecerli dilde metin (eksikse Ingilizce, o da yoksa anahtarin kendisi)
N_(key)         anahtari oldugu gibi dondurur (sonradan ceviri: MenuList ogeleri vb.; test taramasi icin isaret)
upper(text)     dile duyarli buyuk harf (Turkce: i -> I-noktali, ı -> I)
set_language(code) / get_language() / default_language() / LANGUAGES

Gecerli dil AppSettings.extra["language"]'da saklanir; yoksa Windows arayuz dili Turkce ise "tr", degilse "en".
Sahneler metni cizim aninda t() ile alir; dil degisince her sey hemen guncellenir.
"""
from __future__ import annotations

import locale
import sys

LANGUAGES = (("tr", "Türkçe"), ("en", "English"))
_lang = "en"


def N_(key: str) -> str:
    return key


STRINGS: dict[str, dict[str, str]] = {
    # --- ortak
    "common.on": {"en": "ON", "tr": "AÇIK"},
    "common.off": {"en": "OFF", "tr": "KAPALI"},
    "common.yes": {"en": "YES", "tr": "EVET"},
    "common.no": {"en": "NO", "tr": "HAYIR"},
    "common.unknown": {"en": "Unknown", "tr": "Bilinmiyor"},
    "common.bot": {"en": "BOT", "tr": "BOT"},
    "diff.easy": {"en": "Easy", "tr": "Kolay"},
    "diff.medium": {"en": "Medium", "tr": "Orta"},
    "diff.hard": {"en": "Hard", "tr": "Zor"},
    "diff.expert": {"en": "Expert", "tr": "Uzman"},
    # --- ipucu cubugu tuslari / eylemleri
    "key.updown": {"en": "Up/Down", "tr": "Yukarı/Aşağı"},
    "key.leftright": {"en": "Left/Right", "tr": "Sol/Sağ"},
    "key.enter_green": {"en": "Enter / Green", "tr": "Enter / Yeşil"},
    "key.esc_red": {"en": "Esc / Red", "tr": "Esc / Kırmızı"},
    "key.strum_space": {"en": "Strum / Space", "tr": "Strum / Space"},
    "hint.move": {"en": "Move", "tr": "Gezin"},
    "hint.select": {"en": "Select", "tr": "Seç"},
    "hint.change": {"en": "Change", "tr": "Değiştir"},
    "hint.confirm": {"en": "Confirm", "tr": "Onayla"},
    "hint.ok": {"en": "OK", "tr": "Tamam"},
    "hint.back": {"en": "Back", "tr": "Geri"},
    "hint.quit": {"en": "Quit", "tr": "Çık"},
    "hint.fullscreen": {"en": "Fullscreen", "tr": "Tam ekran"},
    "hint.settings": {"en": "Settings", "tr": "Ayarlar"},
    "hint.import": {"en": "Import", "tr": "Şarkı ekle"},
    "hint.import_songs": {"en": "Import songs", "tr": "Şarkı ekle"},
    "hint.rechart": {"en": "Re-chart", "tr": "Notaları yenile"},
    "hint.play": {"en": "Play", "tr": "Oyna"},
    "hint.resume": {"en": "Resume", "tr": "Devam"},
    "hint.start": {"en": "Start", "tr": "Başlat"},
    "hint.skip_video": {"en": "Skip to video", "tr": "Görüntüye geç"},
    "hint.tap": {"en": "Tap", "tr": "Vur"},
    "hint.abort": {"en": "Abort", "tr": "Vazgeç"},
    "hint.toggle_bind": {"en": "Toggle / Bind", "tr": "Aç-kapa / Ata"},
    "hint.save_back": {"en": "Save & back", "tr": "Kaydet ve geri"},
    "hint.song_list": {"en": "Song list", "tr": "Şarkı listesi"},
    "hint.cancel": {"en": "Cancel", "tr": "İptal"},
    "hint.cancel_rest": {"en": "Cancel rest", "tr": "Kalanı iptal et"},
    # --- ana menu
    "title.play": {"en": "PLAY", "tr": "OYNA"},
    "title.import": {"en": "IMPORT SONG", "tr": "ŞARKI EKLE"},
    "title.calibration": {"en": "CALIBRATION", "tr": "KALİBRASYON"},
    "title.settings": {"en": "SETTINGS", "tr": "AYARLAR"},
    "title.quit": {"en": "QUIT", "tr": "ÇIKIŞ"},
    "title.tagline": {"en": "5-FRET RHYTHM GAME", "tr": "5 PERDELİ RİTİM OYUNU"},
    "title.tip": {"en": "Tip: run CALIBRATION once for perfect audio/video sync",
                  "tr": "İpucu: kusursuz ses/görüntü uyumu için bir kez KALİBRASYON yapın"},
    # --- sarki listesi
    "songs.title": {"en": "SELECT SONG", "tr": "ŞARKI SEÇ"},
    "songs.count": {"en": "{n} songs", "tr": "{n} şarkı"},
    "songs.none": {"en": "No songs found.", "tr": "Hiç şarkı bulunamadı."},
    "songs.none_hint": {"en": "Put Clone Hero song folders (notes.chart / notes.mid + song.ogg) into:",
                        "tr": "Clone Hero şarkı klasörlerini (notes.chart / notes.mid + song.ogg) şuraya koyun:"},
    "songs.none_drop": {"en": "...or drop any MP3 / OGG / WAV / FLAC / OPUS file onto this window (I = Import).",
                        "tr": "...ya da bir MP3 / OGG / WAV / FLAC / OPUS dosyasını bu pencereye bırakın (I = Ekle)."},
    "songs.auto": {"en": "AUTO", "tr": "OTO"},
    "songs.album": {"en": "Album", "tr": "Albüm"},
    "songs.year": {"en": "Year", "tr": "Yıl"},
    "songs.genre": {"en": "Genre", "tr": "Tür"},
    "songs.charter": {"en": "Charter", "tr": "Charter"},
    "songs.length": {"en": "Length", "tr": "Süre"},
    "songs.auto_suffix": {"en": "(auto)", "tr": "(otomatik)"},
    "songs.intensity": {"en": "INTENSITY", "tr": "ZORLUK"},
    "songs.difficulties": {"en": "DIFFICULTIES", "tr": "ZORLUKLAR"},
    "songs.track_line": {"en": "{notes} notes   {sp} SP phrases", "tr": "{notes} nota   {sp} Yıldız Gücü cümlesi"},
    "songs.solo": {"en": "{n} solo", "tr": "{n} solo"},
    "songs.chart_error": {"en": "Chart error: {err}", "tr": "Chart hatası: {err}"},
    "songs.rechart_title": {"en": "Re-chart this song?", "tr": "Bu şarkının notaları yenilensin mi?"},
    "songs.rechart_line1": {"en": "The notes will be generated again from the audio.",
                            "tr": "Notalar sesten yeniden üretilecek."},
    "songs.rechart_line2": {"en": "Your old chart is kept as notes.chart.bak.",
                            "tr": "Eski chart notes.chart.bak olarak saklanır."},
    # --- zorluk secimi
    "diffsel.no_fail": {"en": "No Fail", "tr": "No Fail"},
    "diffsel.speed": {"en": "Note Speed", "tr": "Nota Hızı"},
    "diffsel.bot": {"en": "Autoplay (Bot)", "tr": "Otomatik Oynat (Bot)"},
    "diffsel.notes": {"en": "{n} notes", "tr": "{n} nota"},
    "diffsel.loading": {"en": "LOADING...", "tr": "YÜKLENİYOR..."},
    # --- ayarlar
    "set.title": {"en": "SETTINGS", "tr": "AYARLAR"},
    "set.language": {"en": "Language / Dil", "tr": "Dil / Language"},
    "set.h_general": {"en": "GENERAL", "tr": "GENEL"},
    "set.h_gameplay": {"en": "GAMEPLAY", "tr": "OYNANIŞ"},
    "set.h_audio": {"en": "AUDIO", "tr": "SES"},
    "set.h_video": {"en": "VIDEO", "tr": "GÖRÜNTÜ"},
    "set.h_controls": {"en": "CONTROLS  (Enter, then press a key)", "tr": "KONTROLLER  (Enter, sonra bir tuşa basın)"},
    "set.note_speed": {"en": "Note speed", "tr": "Nota hızı"},
    "set.highway_length": {"en": "Highway length", "tr": "Otoban uzunluğu"},
    "set.no_fail": {"en": "No Fail", "tr": "No Fail"},
    "set.timing_meter": {"en": "Timing meter", "tr": "Zamanlama göstergesi"},
    "set.master_volume": {"en": "Master volume", "tr": "Ana ses"},
    "set.sfx_volume": {"en": "SFX volume", "tr": "Efekt sesi"},
    "set.audio_offset": {"en": "Audio offset", "tr": "Ses gecikmesi"},
    "set.audio_buffer": {"en": "Audio buffer", "tr": "Ses tamponu"},
    "set.samples": {"en": "{n} samples", "tr": "{n} örnek"},
    "set.video_offset": {"en": "Video offset", "tr": "Görüntü gecikmesi"},
    "set.fullscreen": {"en": "Fullscreen", "tr": "Tam ekran"},
    "set.debug": {"en": "Show FPS / debug (F3)", "tr": "FPS / hata ayıklama (F3)"},
    "set.fps_limit": {"en": "FPS limit", "tr": "FPS sınırı"},
    "set.unlimited": {"en": "Unlimited", "tr": "Sınırsız"},
    "set.calibrate": {"en": "Calibrate audio / video", "tr": "Ses / görüntü kalibrasyonu"},
    "set.reset_keys": {"en": "Reset keys to default", "tr": "Tuşları varsayılana döndür"},
    "set.back": {"en": "Back", "tr": "Geri"},
    "set.keys_reset": {"en": "Keys reset to defaults", "tr": "Tuşlar varsayılana döndü"},
    "set.bound": {"en": "Bound {key}", "tr": "Atandı: {key}"},
    "set.cancelled": {"en": "Cancelled", "tr": "İptal edildi"},
    "set.press_key": {"en": "press a key...  (Esc cancels)", "tr": "bir tuşa basın...  (Esc iptal)"},
    "set.controller_mapping": {"en": "CONTROLLER MAPPING", "tr": "KONTROLCÜ EŞLEMESİ"},
    "set.connected": {"en": "CONNECTED", "tr": "BAĞLI"},
    "set.no_controller": {"en": "No controller detected (hot-plug supported)",
                          "tr": "Kontrolcü yok (takınca otomatik tanınır)"},
    "key.fret0": {"en": "Green fret", "tr": "Yeşil perde"},
    "key.fret1": {"en": "Red fret", "tr": "Kırmızı perde"},
    "key.fret2": {"en": "Yellow fret", "tr": "Sarı perde"},
    "key.fret3": {"en": "Blue fret", "tr": "Mavi perde"},
    "key.fret4": {"en": "Orange fret", "tr": "Turuncu perde"},
    "key.strum_up": {"en": "Strum up", "tr": "Vuruş yukarı"},
    "key.strum_down": {"en": "Strum down", "tr": "Vuruş aşağı"},
    "key.open_strum": {"en": "Open strum", "tr": "Açık vuruş"},
    "key.star_power": {"en": "Star Power", "tr": "Yıldız Gücü"},
    "key.whammy": {"en": "Whammy", "tr": "Whammy"},
    "key.start": {"en": "Start / Pause", "tr": "Başlat / Duraklat"},
    "key.pause": {"en": "Pause / Back", "tr": "Duraklat / Geri"},
    "ctl.frets": {"en": "Green / Red / Yellow / Blue / Orange", "tr": "Yeşil / Kırmızı / Sarı / Mavi / Turuncu"},
    "ctl.frets_v": {"en": "A / B / Y / X / LB", "tr": "A / B / Y / X / LB"},
    "ctl.strum": {"en": "Strum up / down", "tr": "Vuruş yukarı / aşağı"},
    "ctl.strum_v": {"en": "D-pad up / down (strum bar)", "tr": "D-pad yukarı / aşağı (strum çubuğu)"},
    "ctl.whammy": {"en": "Whammy", "tr": "Whammy"},
    "ctl.whammy_v": {"en": "Right stick X (guitar) or right trigger", "tr": "Sağ çubuk X (gitar) veya sağ tetik"},
    "ctl.sp": {"en": "Star Power", "tr": "Yıldız Gücü"},
    "ctl.sp_v": {"en": "Tilt (right stick Y) or Back / Select", "tr": "Gitarı kaldır (sağ çubuk Y) veya Back / Select"},
    "ctl.open": {"en": "Open strum", "tr": "Açık vuruş"},
    "ctl.open_v": {"en": "RB", "tr": "RB"},
    "ctl.pause": {"en": "Pause / Start", "tr": "Duraklat / Başlat"},
    "ctl.pause_v": {"en": "Start", "tr": "Start"},
    "ctl.menus": {"en": "Menus", "tr": "Menüler"},
    "ctl.menus_v": {"en": "A confirm, B back, D-pad / strum move", "tr": "A onay, B geri, D-pad / strum gezinme"},
    # --- oyun
    "game.sp_ready": {"en": "STAR POWER READY", "tr": "YILDIZ GÜCÜ HAZIR"},
    "game.full_combo": {"en": "FULL COMBO!", "tr": "FULL COMBO!"},
    "game.streak": {"en": "{n} NOTE STREAK!", "tr": "{n} NOTA SERİ!"},
    "game.sp": {"en": "STAR POWER!", "tr": "YILDIZ GÜCÜ!"},
    "game.solo": {"en": "GUITAR SOLO!", "tr": "GİTAR SOLOSU!"},
    "game.solo_perfect": {"en": "PERFECT SOLO!", "tr": "KUSURSUZ SOLO!"},
    "game.solo_awesome": {"en": "AWESOME SOLO!", "tr": "MUHTEŞEM SOLO!"},
    "game.solo_great": {"en": "GREAT SOLO!", "tr": "HARİKA SOLO!"},
    "game.solo_good": {"en": "GOOD SOLO", "tr": "İYİ SOLO"},
    "game.solo_messy": {"en": "MESSY SOLO", "tr": "DAĞINIK SOLO"},
    "sec.intro": {"en": "Intro", "tr": "Giriş"},
    "sec.verse": {"en": "Verse", "tr": "Kıta"},
    "sec.prechorus": {"en": "Pre-Chorus", "tr": "Ön Nakarat"},
    "sec.chorus": {"en": "Chorus", "tr": "Nakarat"},
    "sec.bridge": {"en": "Bridge", "tr": "Köprü"},
    "sec.outro": {"en": "Outro", "tr": "Kapanış"},
    "sec.section": {"en": "Section", "tr": "Bölüm"},
    "sec.guitar_solo": {"en": "Guitar Solo", "tr": "Gitar Solosu"},
    "sec.solo": {"en": "Solo", "tr": "Solo"},
    "pause.title": {"en": "PAUSED", "tr": "DURAKLATILDI"},
    "pause.resume": {"en": "RESUME", "tr": "DEVAM"},
    "pause.restart": {"en": "RESTART", "tr": "YENİDEN BAŞLAT"},
    "pause.settings": {"en": "SETTINGS", "tr": "AYARLAR"},
    "pause.quit": {"en": "QUIT TO SONG LIST", "tr": "ŞARKI LİSTESİNE DÖN"},
    "fail.title": {"en": "SONG FAILED", "tr": "ŞARKI BAŞARISIZ"},
    "fail.retry": {"en": "RETRY", "tr": "TEKRAR DENE"},
    "fail.results": {"en": "RESULTS", "tr": "SONUÇLAR"},
    "fail.progress": {"en": "{p}% of the song completed", "tr": "Şarkının %{p} kadarı tamamlandı"},
    # --- HUD
    "hud.streak": {"en": "STREAK", "tr": "SERİ"},
    "hud.rock_meter": {"en": "ROCK METER", "tr": "ROCK METRE"},
    "hud.no_fail": {"en": "NO FAIL", "tr": "NO FAIL"},
    "hud.star_power": {"en": "STAR POWER", "tr": "YILDIZ GÜCÜ"},
    "hud.ready": {"en": "READY!", "tr": "HAZIR!"},
    "hud.active": {"en": "ACTIVE", "tr": "AKTİF"},
    "hud.early": {"en": "EARLY", "tr": "ERKEN"},
    "hud.late": {"en": "LATE", "tr": "GEÇ"},
    "hud.solo": {"en": "SOLO", "tr": "SOLO"},
    # --- sonuc
    "res.failed": {"en": "SONG FAILED", "tr": "ŞARKI BAŞARISIZ"},
    "res.fc": {"en": "FULL COMBO!", "tr": "FULL COMBO!"},
    "res.complete": {"en": "SONG COMPLETE", "tr": "ŞARKI TAMAMLANDI"},
    "res.gold": {"en": "GOLD STARS!", "tr": "ALTIN YILDIZLAR!"},
    "res.notes_hit": {"en": "Notes hit", "tr": "Vurulan nota"},
    "res.max_combo": {"en": "Max combo", "tr": "En uzun seri"},
    "res.overstrums": {"en": "Overstrums", "tr": "Boşa vuruş"},
    "res.sp_phrases": {"en": "Star Power phrases", "tr": "Yıldız Gücü cümleleri"},
    "res.stars": {"en": "Stars", "tr": "Yıldız"},
    "res.timing": {"en": "TIMING", "tr": "ZAMANLAMA"},
    "res.median_mean": {"en": "median {med} ms   mean {mean} ms", "tr": "medyan {med} ms   ortalama {mean} ms"},
    "res.continue": {"en": "CONTINUE", "tr": "DEVAM"},
    "res.retry": {"en": "RETRY", "tr": "TEKRAR DENE"},
    # --- kalibrasyon
    "cal.title": {"en": "CALIBRATION", "tr": "KALİBRASYON"},
    "cal.current": {"en": "current:  audio {a} ms   video {v} ms", "tr": "şu an:  ses {a} ms   görüntü {v} ms"},
    "cal.audio_title": {"en": "AUDIO CALIBRATION", "tr": "SES KALİBRASYONU"},
    "cal.audio_1": {"en": "You will hear a metronome at 120 BPM.", "tr": "120 BPM hızında bir metronom duyacaksınız."},
    "cal.audio_2": {"en": "After {n} count-in clicks, press STRUM (Up/Down) or SPACE",
                    "tr": "{n} sayım tıkından sonra STRUM (Yukarı/Aşağı) ya da SPACE tuşuna"},
    "cal.audio_3": {"en": "exactly on every click. Listen - don't watch.",
                    "tr": "her tıkta tam zamanında basın. Ekrana değil, sese odaklanın."},
    "cal.audio_4": {"en": "At least {n} taps are needed; the median error becomes the audio offset.",
                    "tr": "En az {n} vuruş gerekir; hataların medyanı ses gecikmesi olur."},
    "cal.audio_5": {"en": "Use headphones / your normal speakers and play volume.",
                    "tr": "Oynarken kullandığınız kulaklık / hoparlör ve ses seviyesini kullanın."},
    "cal.video_title": {"en": "VIDEO CALIBRATION", "tr": "GÖRÜNTÜ KALİBRASYONU"},
    "cal.video_1": {"en": "No sound this time. Markers fall onto the target line.",
                    "tr": "Bu kez ses yok. İşaretler hedef çizgiye düşer."},
    "cal.video_2": {"en": "Press STRUM or SPACE exactly when a marker hits the line.",
                    "tr": "İşaret çizgiye değdiği anda STRUM ya da SPACE tuşuna basın."},
    "cal.video_3": {"en": "This measures display + input delay (video offset).",
                    "tr": "Bu, ekran + giriş gecikmesini ölçer (görüntü gecikmesi)."},
    "cal.audio_offset": {"en": "AUDIO OFFSET", "tr": "SES GECİKMESİ"},
    "cal.video_offset": {"en": "VIDEO OFFSET", "tr": "GÖRÜNTÜ GECİKMESİ"},
    "cal.failed": {"en": "CALIBRATION FAILED", "tr": "KALİBRASYON BAŞARISIZ"},
    "cal.too_few": {"en": "Only {n} valid taps (need {m}). Tap on every click!",
                    "tr": "Yalnızca {n} geçerli vuruş (en az {m} gerekli). Her tıkta vurun!"},
    "cal.inconsistent": {"en": "Inconsistent taps (stdev {sd} ms > {mx} ms). Try again.",
                         "tr": "Tutarsız vuruşlar (std. sapma {sd} ms > {mx} ms). Tekrar deneyin."},
    "cal.stats": {"en": "stdev {sd} ms over {n} taps", "tr": "{n} vuruşta std. sapma {sd} ms"},
    "cal.save_video": {"en": "SAVE & CALIBRATE VIDEO", "tr": "KAYDET, GÖRÜNTÜYE GEÇ"},
    "cal.save_finish": {"en": "SAVE & FINISH", "tr": "KAYDET VE BİTİR"},
    "cal.retry": {"en": "RETRY", "tr": "TEKRAR DENE"},
    "cal.cancel": {"en": "CANCEL", "tr": "İPTAL"},
    "cal.get_ready": {"en": "Get ready...", "tr": "Hazır ol..."},
    "cal.tap": {"en": "TAP!", "tr": "VUR!"},
    "cal.taps": {"en": "taps: {n} / {m}+", "tr": "vuruş: {n} / {m}+"},
    "cal.left": {"en": "{n} clicks left", "tr": "{n} tık kaldı"},
    # --- sarki ekleme
    "imp.title": {"en": "IMPORT SONGS", "tr": "ŞARKI EKLE"},
    "imp.drop_here": {"en": "Drop your audio files here", "tr": "Ses dosyalarını buraya bırakın"},
    "imp.drop_many": {"en": "Several files or whole folders at once are fine",
                      "tr": "Aynı anda birden çok dosya ya da klasör bırakabilirsiniz"},
    "imp.drop_auto": {"en": "Notes for all 4 difficulties are generated automatically",
                      "tr": "4 zorluğun notaları otomatik olarak üretilir"},
    "imp.drop_anywhere": {"en": "You can also drop files on any menu screen",
                          "tr": "Dosyaları herhangi bir menü ekranına da bırakabilirsiniz"},
    "imp.formats": {"en": "ACCEPTED FORMATS", "tr": "DESTEKLENEN BİÇİMLER"},
    "imp.recommended": {"en": "RECOMMENDED", "tr": "ÖNERİLER"},
    "imp.tip1": {"en": "OGG or MP3, 44.1 kHz", "tr": "OGG ya da MP3, 44,1 kHz"},
    "imp.tip2": {"en": "The full song, 1 to 10 minutes", "tr": "Şarkının tamamı, 1-10 dakika"},
    "imp.tip3": {"en": "No tags? Name the file", "tr": "Etiket yoksa dosyayı şöyle adlandırın:"},
    "imp.tip3b": {"en": "'Artist - Title.mp3'", "tr": "'Sanatçı - Şarkı.mp3'"},
    "imp.tip4": {"en": "Clear mixes with a lead melody", "tr": "Belirgin bir ana melodisi olan"},
    "imp.tip4b": {"en": "give the best charts", "tr": "kayıtlar en iyi sonucu verir"},
    "imp.folder_title": {"en": "OR USE THE IMPORT FOLDER", "tr": "YA DA İÇE AKTARMA KLASÖRÜNÜ KULLANIN"},
    "imp.folder_waiting": {"en": "{n} file(s) waiting - choose IMPORT NOW",
                           "tr": "{n} dosya bekliyor - ŞİMDİ EKLE'yi seçin"},
    "imp.folder_empty": {"en": "Copy files there, then choose IMPORT NOW",
                         "tr": "Dosyaları oraya kopyalayın, sonra ŞİMDİ EKLE'yi seçin"},
    "imp.btn_open": {"en": "OPEN IMPORT FOLDER", "tr": "KLASÖRÜ AÇ"},
    "imp.btn_now": {"en": "IMPORT NOW", "tr": "ŞİMDİ EKLE"},
    "imp.btn_now_n": {"en": "IMPORT NOW ({n})", "tr": "ŞİMDİ EKLE ({n})"},
    "imp.btn_back": {"en": "BACK", "tr": "GERİ"},
    "imp.btn_play": {"en": "PLAY NOW", "tr": "HEMEN OYNA"},
    "imp.btn_list": {"en": "SONG LIST", "tr": "ŞARKI LİSTESİ"},
    "imp.btn_more": {"en": "IMPORT MORE", "tr": "DAHA FAZLA EKLE"},
    "imp.btn_cancel": {"en": "CANCEL", "tr": "İPTAL ET"},
    "imp.no_audio": {"en": "No audio files found in the drop (MP3, OGG, WAV, FLAC, OPUS).",
                     "tr": "Bırakılanlar arasında ses dosyası yok (MP3, OGG, WAV, FLAC, OPUS)."},
    "imp.opened": {"en": "Opened: {path}", "tr": "Açıldı: {path}"},
    "imp.open_failed": {"en": "Cannot open folder: {err}", "tr": "Klasör açılamadı: {err}"},
    "imp.inbox_empty": {"en": "The import folder is empty - copy audio files into it first.",
                        "tr": "İçe aktarma klasörü boş - önce içine ses dosyası kopyalayın."},
    "imp.cancelling": {"en": "Cancelling...", "tr": "İptal ediliyor..."},
    "imp.done_title": {"en": "{n} song(s) added", "tr": "{n} şarkı eklendi"},
    "imp.done_failed": {"en": ", {n} failed", "tr": ", {n} başarısız"},
    "imp.done_sub": {"en": "Your songs are in the song list (marked GUITAR or AUTO).",
                     "tr": "Şarkılarınız şarkı listesinde (GİTAR ya da OTO işaretli)."},
    "imp.done_none": {"en": "Nothing was imported.", "tr": "Hiçbir şey eklenmedi."},
    "imp.waiting": {"en": "Waiting", "tr": "Bekleniyor"},
    "imp.song_n": {"en": "Song {i} of {n}", "tr": "Şarkı {i} / {n}"},
    "imp.added": {"en": "added: {name}", "tr": "eklendi: {name}"},
    "imp.cancelled": {"en": "cancelled", "tr": "iptal edildi"},
    "imp.err_not_found": {"en": "file not found", "tr": "dosya bulunamadı"},
    "imp.err_type": {"en": "unsupported file type '{ext}' (use MP3, OGG, WAV, FLAC or OPUS)",
                     "tr": "desteklenmeyen dosya türü '{ext}' (MP3, OGG, WAV, FLAC ya da OPUS kullanın)"},
    "imp.err_short": {"en": "audio is too short ({dur} s, need at least {min} s)",
                      "tr": "ses çok kısa ({dur} sn, en az {min} sn gerekli)"},
    "imp.err_long": {"en": "audio is too long ({dur} min, max {max} min)",
                     "tr": "ses çok uzun ({dur} dk, en fazla {max} dk)"},
    "imp.err_silent": {"en": "audio is silent", "tr": "ses dosyası sessiz"},
    "imp.err_decode": {"en": "cannot decode audio ({err})", "tr": "ses çözülemedi ({err})"},
    "imp.err_chart": {"en": "auto-charting failed: {err}", "tr": "otomatik nota üretimi başarısız: {err}"},
    "imp.err_write": {"en": "cannot write files: {err}", "tr": "dosyalar yazılamadı: {err}"},
    "imp.err_no_audio": {"en": "no audio file in this song folder", "tr": "bu şarkı klasöründe ses dosyası yok"},
    "imp.err_not_song": {"en": "not a song folder (no notes.chart / notes.mid)",
                         "tr": "şarkı klasörü değil (notes.chart / notes.mid yok)"},
    "imp.err_already": {"en": "this song is already in the Songs folder", "tr": "bu şarkı zaten Songs klasöründe"},
    # ice aktarma asamalari (gh.importer / gh.autochart ilerleme metinleri; Ingilizce metin = anahtar)
    "stage.Starting": {"en": "Starting", "tr": "Başlıyor"},
    "stage.Reading tags": {"en": "Reading tags", "tr": "Etiketler okunuyor"},
    "stage.Decoding audio": {"en": "Decoding audio", "tr": "Ses çözülüyor"},
    "stage.Preparing audio": {"en": "Preparing audio", "tr": "Ses hazırlanıyor"},
    "stage.Detecting onsets": {"en": "Detecting onsets", "tr": "Vuruşlar algılanıyor"},
    "stage.Estimating tempo": {"en": "Estimating tempo", "tr": "Tempo bulunuyor"},
    "stage.Tracking beats": {"en": "Tracking beats", "tr": "Ritim izleniyor"},
    "stage.Analysing pitch": {"en": "Analysing pitch", "tr": "Perdeler analiz ediliyor"},
    "stage.Finding notes": {"en": "Finding notes", "tr": "Notalar bulunuyor"},
    "stage.Finding song sections": {"en": "Finding song sections", "tr": "Şarkı bölümleri bulunuyor"},
    "stage.Building tempo map": {"en": "Building tempo map", "tr": "Tempo haritası oluşturuluyor"},
    "stage.Charting Expert": {"en": "Charting Expert", "tr": "Uzman notaları yazılıyor"},
    "stage.Charting Hard / Medium / Easy": {"en": "Charting Hard / Medium / Easy",
                                           "tr": "Zor / Orta / Kolay notaları yazılıyor"},
    "stage.Checking playability": {"en": "Checking playability", "tr": "Oynanabilirlik denetleniyor"},
    "stage.Writing song files": {"en": "Writing song files", "tr": "Şarkı dosyaları yazılıyor"},
    "stage.Writing chart": {"en": "Writing chart", "tr": "Chart yazılıyor"},
    "stage.Drawing album art": {"en": "Drawing album art", "tr": "Albüm kapağı çiziliyor"},
    "stage.Copying song folder": {"en": "Copying song folder", "tr": "Şarkı klasörü kopyalanıyor"},
    "stage.Done": {"en": "Done", "tr": "Bitti"},
    # gitar kalibrasyonu (gh.ai.pipeline.STAGES)
    "stage.Separating guitar": {"en": "Separating the guitar", "tr": "Gitar ayrıştırılıyor"},
    "stage.Transcribing guitar notes": {"en": "Transcribing guitar notes", "tr": "Gitar notaları çıkarılıyor"},
    "stage.Finding tempo and bars": {"en": "Finding tempo and bars", "tr": "Tempo ve ölçü bulunuyor"},
    "stage.Placing notes": {"en": "Placing notes", "tr": "Notalar yerleştiriliyor"},
    "stage.Preparing difficulties": {"en": "Preparing difficulties", "tr": "Zorluklar hazırlanıyor"},
    "imp.cal_title": {"en": "GUITAR CALIBRATION", "tr": "GİTAR KALİBRASYONU"},
    "imp.cal_sub": {"en": "The AI isolates the guitar and learns its notes - this takes a minute or two.",
                    "tr": "Yapay zekâ gitarı ayırıp notalarını öğreniyor - bir iki dakika sürer."},
    "imp.cal_prep": {"en": "Reading the song", "tr": "Şarkı okunuyor"},
    "imp.elapsed": {"en": "Elapsed {t}", "tr": "Geçen {t}"},
    "imp.remaining": {"en": "Remaining ~{t}", "tr": "Kalan ~{t}"},
    "imp.estimating": {"en": "Estimating time...", "tr": "Süre hesaplanıyor..."},
    "imp.no_guitar": {"en": "No clear guitar found in this song - notes were generated from the whole mix",
                      "tr": "Bu şarkıda belirgin gitar bulunamadı, genel miksle nota üretildi"},
    "imp.no_ai": {"en": "Guitar detection is off or unavailable - notes follow the whole mix",
                  "tr": "Gitar algılama kapalı ya da kullanılamıyor - notalar genel miksten"},
    "imp.guitar_ok": {"en": "charted from the guitar", "tr": "gitardan nota üretildi"},
    "songs.guitar": {"en": "GUITAR", "tr": "GİTAR"},
    "set.guitar_ai": {"en": "Guitar detection (AI)", "tr": "Gitar algılama (yapay zekâ)"},
}

DIFF_KEYS = {"easy": N_("diff.easy"), "medium": N_("diff.medium"), "hard": N_("diff.hard"),
             "expert": N_("diff.expert")}


def default_language() -> str:
    """Windows arayuz dili Turkce ise 'tr', degilse sistem yereline bak, o da degilse 'en'."""
    if sys.platform == "win32":
        try:
            import ctypes
            if ctypes.windll.kernel32.GetUserDefaultUILanguage() & 0x3FF == 0x1F:   # LANG_TURKISH
                return "tr"
            return "en"
        except Exception:
            pass
    try:
        loc = (locale.getlocale()[0] or "").lower()
    except Exception:
        loc = ""
    return "tr" if loc.startswith(("tr", "turkish")) else "en"


def set_language(code: str | None) -> str:
    global _lang
    codes = [c for c, _ in LANGUAGES]
    _lang = code if code in codes else "en"
    return _lang


def get_language() -> str:
    return _lang


def language_name(code: str | None = None) -> str:
    return dict(LANGUAGES).get(code or _lang, code or _lang)


def t(key: str, **fmt) -> str:
    entry = STRINGS.get(key)
    if entry is None:
        s = key
    else:
        s = entry.get(_lang) or entry.get("en") or key
    if fmt:
        try:
            s = s.format(**fmt)
        except (KeyError, IndexError, ValueError):
            pass
    return s


def stage(text: str) -> str:
    """Ice aktarma ilerleme metni (Ingilizce) -> gecerli dil."""
    return t("stage." + text) if ("stage." + text) in STRINGS else text


def upper(text: str) -> str:
    if _lang == "tr":
        text = text.replace("i", "İ").replace("ı", "I")
    return text.upper()


def diff_name(diff: str) -> str:
    return t(DIFF_KEYS.get(diff, diff))


SECTION_KEYS = {"intro": N_("sec.intro"), "verse": N_("sec.verse"), "pre-chorus": N_("sec.prechorus"),
                "chorus": N_("sec.chorus"), "bridge": N_("sec.bridge"), "outro": N_("sec.outro"),
                "section": N_("sec.section"), "guitar solo": N_("sec.guitar_solo"), "solo": N_("sec.solo")}


def section_label(name: str) -> str:
    """Bilinen bolum adlarini ('Verse 2', 'Chorus', 'Section 3', ...) cevir; digerleri oldugu gibi."""
    import re
    m = re.fullmatch(r"\s*([A-Za-z][A-Za-z -]*?)(?:\s+(\d+))?\s*", name or "")
    if not m:
        return name
    key = SECTION_KEYS.get(m.group(1).lower())
    if key is None:
        return name
    return t(key) + (f" {m.group(2)}" if m.group(2) else "")
