"""Ses dosyasi etiket okuyuculari (bagimliliksiz, saf Python).

read_metadata(path) -> AudioMeta
  - MP3 / diger: ID3v2.2/2.3/2.4 (TIT2 TPE1 TALB TYER TDRC TCON + APIC), yoksa ID3v1
  - OGG Vorbis / Opus: Vorbis yorumlari (+ METADATA_BLOCK_PICTURE)
  - FLAC: VORBIS_COMMENT + PICTURE bloklari
  - WAV: RIFF LIST/INFO (+ 'id3 ' parcasi)
meta_from_filename(path) -> (artist, title): "Artist - Title.mp3" / "01 - Title.mp3"
"""
from __future__ import annotations

import base64
import os
import re
import struct
from dataclasses import dataclass

MAX_TAG_BYTES = 24 * 1024 * 1024

ID3V1_GENRES = [
    "Blues", "Classic Rock", "Country", "Dance", "Disco", "Funk", "Grunge", "Hip-Hop", "Jazz", "Metal",
    "New Age", "Oldies", "Other", "Pop", "R&B", "Rap", "Reggae", "Rock", "Techno", "Industrial",
    "Alternative", "Ska", "Death Metal", "Pranks", "Soundtrack", "Euro-Techno", "Ambient", "Trip-Hop", "Vocal",
    "Jazz+Funk", "Fusion", "Trance", "Classical", "Instrumental", "Acid", "House", "Game", "Sound Clip",
    "Gospel", "Noise", "AlternRock", "Bass", "Soul", "Punk", "Space", "Meditative", "Instrumental Pop",
    "Instrumental Rock", "Ethnic", "Gothic", "Darkwave", "Techno-Industrial", "Electronic", "Pop-Folk",
    "Eurodance", "Dream", "Southern Rock", "Comedy", "Cult", "Gangsta", "Top 40", "Christian Rap", "Pop/Funk",
    "Jungle", "Native American", "Cabaret", "New Wave", "Psychedelic", "Rave", "Showtunes", "Trailer",
    "Lo-Fi", "Tribal", "Acid Punk", "Acid Jazz", "Polka", "Retro", "Musical", "Rock & Roll", "Hard Rock",
]


@dataclass
class AudioMeta:
    title: str = ""
    artist: str = ""
    album: str = ""
    year: str = ""
    genre: str = ""
    cover: bytes = b""
    cover_mime: str = ""

    def merge(self, other: "AudioMeta") -> None:
        """Bos alanlari digerinden doldur."""
        for k in ("title", "artist", "album", "year", "genre"):
            if not getattr(self, k) and getattr(other, k):
                setattr(self, k, getattr(other, k))
        if not self.cover and other.cover:
            self.cover, self.cover_mime = other.cover, other.cover_mime


def _clean(s: str) -> str:
    s = s.replace("\x00", " ").replace("\r", " ").replace("\n", " ").strip()
    return re.sub(r"\s+", " ", s)


def _year(s: str) -> str:
    m = re.search(r"(\d{4})", s or "")
    return m.group(1) if m else ""


def _genre(s: str) -> str:
    s = _clean(s)
    m = re.fullmatch(r"\((\d+)\)(.*)", s)
    if m:
        rest = m.group(2).strip()
        if rest:
            return rest
        s = m.group(1)
    if s.isdigit():
        i = int(s)
        return ID3V1_GENRES[i] if 0 <= i < len(ID3V1_GENRES) else ""
    return s


# --------------------------------------------------------------------------- ID3v2

def _syncsafe(b: bytes) -> int:
    return (b[0] & 0x7F) << 21 | (b[1] & 0x7F) << 14 | (b[2] & 0x7F) << 7 | (b[3] & 0x7F)


def _unsync(b: bytes) -> bytes:
    return b.replace(b"\xff\x00", b"\xff")


def _decode_text(enc: int, data: bytes) -> str:
    try:
        if enc == 0:
            s = data.decode("latin-1")
        elif enc == 1:
            s = data.decode("utf-16")
        elif enc == 2:
            s = data.decode("utf-16-be")
        else:
            s = data.decode("utf-8", "replace")
    except UnicodeDecodeError:
        s = data.decode("latin-1", "replace")
    s = s.lstrip("﻿")
    # v2.4 coklu deger: ilkini al
    return s.split("\x00")[0]


def _split_terminated(enc: int, data: bytes) -> tuple[bytes, bytes]:
    """Kodlamaya gore null ile biten alani ayir: (alan, kalan)."""
    if enc in (1, 2):
        i = 0
        while i + 1 < len(data):
            if data[i] == 0 and data[i + 1] == 0:
                return data[:i], data[i + 2:]
            i += 2
        return data, b""
    i = data.find(b"\x00")
    return (data, b"") if i < 0 else (data[:i], data[i + 1:])


def parse_id3v2(data: bytes) -> tuple[AudioMeta, int]:
    """(meta, etiketin toplam boyutu). Gecersizse (bos meta, 0)."""
    meta = AudioMeta()
    if len(data) < 10 or data[:3] != b"ID3":
        return meta, 0
    major = data[3]
    flags = data[5]
    size = _syncsafe(data[6:10])
    total = 10 + size + (10 if flags & 0x10 else 0)
    body = data[10:10 + size]
    if major < 4 and flags & 0x80:
        body = _unsync(body)
    pos = 0
    if flags & 0x40 and major >= 3:          # genisletilmis baslik
        if len(body) >= 4:
            ext = _syncsafe(body[:4]) if major == 4 else struct.unpack(">I", body[:4])[0] + 4
            pos = ext
    covers: list[tuple[int, str, bytes]] = []
    texts: dict[str, str] = {}
    while pos < len(body):
        if major == 2:
            if pos + 6 > len(body):
                break
            fid = body[pos:pos + 3].decode("latin-1", "replace")
            fsize = int.from_bytes(body[pos + 3:pos + 6], "big")
            fflags = 0
            hdr = 6
        else:
            if pos + 10 > len(body):
                break
            fid = body[pos:pos + 4].decode("latin-1", "replace")
            raw = body[pos + 4:pos + 8]
            fsize = _syncsafe(raw) if major == 4 else struct.unpack(">I", raw)[0]
            fflags = int.from_bytes(body[pos + 8:pos + 10], "big")
            hdr = 10
        if not fid.strip("\x00") or not re.fullmatch(r"[A-Z0-9]{3,4}", fid):
            break
        fdata = body[pos + hdr:pos + hdr + fsize]
        pos += hdr + fsize
        if major == 4:
            if fflags & 0x000C:              # sikistirma / sifreleme: atla
                continue
            if fflags & 0x0002:
                fdata = _unsync(fdata)
            if fflags & 0x0001:
                fdata = fdata[4:]            # veri uzunlugu gostergesi
        elif major == 3 and fflags & 0x00C0:
            continue
        if not fdata:
            continue
        if fid[0] == "T" and fid not in ("TXXX", "TXX"):
            texts[fid] = _clean(_decode_text(fdata[0], fdata[1:]))
        elif fid in ("APIC", "PIC"):
            enc = fdata[0]
            if fid == "APIC":
                mime, rest = _split_terminated(0, fdata[1:])
                mime_s = mime.decode("latin-1", "replace").lower()
            else:
                fmt = fdata[1:4].decode("latin-1", "replace").lower()
                mime_s = "image/png" if fmt == "png" else "image/jpeg"
                rest = fdata[4:]
            if not rest:
                continue
            ptype = rest[0]
            _desc, img = _split_terminated(enc, rest[1:])
            if img:
                covers.append((ptype, mime_s, img))
    get = lambda *ks: next((texts[k] for k in ks if texts.get(k)), "")  # noqa: E731
    meta.title = get("TIT2", "TT2")
    meta.artist = get("TPE1", "TP1", "TPE2", "TP2")
    meta.album = get("TALB", "TAL")
    meta.year = _year(get("TDRC", "TYER", "TYE", "TDOR", "TORY"))
    meta.genre = _genre(get("TCON", "TCO"))
    if covers:
        covers.sort(key=lambda c: (c[0] != 3, -len(c[2])))
        meta.cover_mime, meta.cover = covers[0][1], covers[0][2]
    return meta, total


def parse_id3v1(tail: bytes) -> AudioMeta:
    meta = AudioMeta()
    if len(tail) < 128 or tail[-128:-125] != b"TAG":
        return meta
    t = tail[-128:]
    dec = lambda b: _clean(b.split(b"\x00")[0].decode("latin-1", "replace"))  # noqa: E731
    meta.title, meta.artist, meta.album = dec(t[3:33]), dec(t[33:63]), dec(t[63:93])
    meta.year = _year(dec(t[93:97]))
    g = t[127]
    meta.genre = ID3V1_GENRES[g] if g < len(ID3V1_GENRES) else ""
    return meta


# --------------------------------------------------------------------------- Vorbis yorumlari

def parse_vorbis_comment(data: bytes) -> AudioMeta:
    """Cerceve bitisi olmadan: vendor_len, vendor, n, [len, 'KEY=deger']..."""
    meta = AudioMeta()
    try:
        vlen = struct.unpack("<I", data[:4])[0]
        pos = 4 + vlen
        n = struct.unpack("<I", data[pos:pos + 4])[0]
        pos += 4
        tags: dict[str, str] = {}
        pics: list[bytes] = []
        for _ in range(min(n, 10000)):
            ln = struct.unpack("<I", data[pos:pos + 4])[0]
            pos += 4
            entry = data[pos:pos + ln]
            pos += ln
            if b"=" not in entry:
                continue
            k, v = entry.split(b"=", 1)
            key = k.decode("ascii", "replace").upper()
            if key == "METADATA_BLOCK_PICTURE":
                try:
                    pics.append(base64.b64decode(v))
                except Exception:
                    pass
                continue
            if key == "COVERART":
                try:
                    img = base64.b64decode(v)
                    if img and not meta.cover:
                        meta.cover, meta.cover_mime = img, "image/jpeg"
                except Exception:
                    pass
                continue
            val = _clean(v.decode("utf-8", "replace"))
            if key not in tags and val:
                tags[key] = val
    except (struct.error, IndexError):
        return meta
    meta.title = tags.get("TITLE", "")
    meta.artist = tags.get("ARTIST", "") or tags.get("ALBUMARTIST", "") or tags.get("ALBUM ARTIST", "")
    meta.album = tags.get("ALBUM", "")
    meta.year = _year(tags.get("DATE", "") or tags.get("YEAR", ""))
    meta.genre = _genre(tags.get("GENRE", ""))
    for p in pics:
        m = parse_flac_picture(p)
        if m.cover:
            meta.cover, meta.cover_mime = m.cover, m.cover_mime
            break
    return meta


def parse_flac_picture(data: bytes) -> AudioMeta:
    meta = AudioMeta()
    try:
        pos = 4
        mlen = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
        mime = data[pos:pos + mlen].decode("ascii", "replace").lower()
        pos += mlen
        dlen = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4 + dlen + 16
        ilen = struct.unpack(">I", data[pos:pos + 4])[0]
        pos += 4
        img = data[pos:pos + ilen]
        if img:
            meta.cover, meta.cover_mime = img, mime or "image/jpeg"
    except (struct.error, IndexError):
        pass
    return meta


def _ogg_packets(data: bytes, max_packets: int = 3) -> list[bytes]:
    """Ilk mantiksal akisin ilk paketleri (sayfa segmentlerinden birlestirilir)."""
    packets: list[bytes] = []
    cur = b""
    pos = 0
    serial = None
    while pos + 27 <= len(data) and len(packets) < max_packets:
        if data[pos:pos + 4] != b"OggS":
            nxt = data.find(b"OggS", pos + 1)
            if nxt < 0:
                break
            pos = nxt
            continue
        ser = data[pos + 14:pos + 18]
        nseg = data[pos + 26]
        table = data[pos + 27:pos + 27 + nseg]
        body = pos + 27 + nseg
        if serial is None:
            serial = ser
        if ser != serial:
            pos = body + sum(table)
            continue
        off = body
        for s in table:
            cur += data[off:off + s]
            off += s
            if s < 255:
                packets.append(cur)
                cur = b""
                if len(packets) >= max_packets:
                    break
        pos = body + sum(table)
    return packets


def parse_ogg(data: bytes) -> AudioMeta:
    for p in _ogg_packets(data, 3)[1:]:
        if p.startswith(b"\x03vorbis"):
            return parse_vorbis_comment(p[7:])
        if p.startswith(b"OpusTags"):
            return parse_vorbis_comment(p[8:])
    return AudioMeta()


def parse_flac(data: bytes) -> AudioMeta:
    meta = AudioMeta()
    pos = 0
    if data[:3] == b"ID3":
        m, size = parse_id3v2(data)
        meta.merge(m)
        pos = size
    if data[pos:pos + 4] != b"fLaC":
        return meta
    pos += 4
    while pos + 4 <= len(data):
        hdr = data[pos]
        btype = hdr & 0x7F
        ln = int.from_bytes(data[pos + 1:pos + 4], "big")
        block = data[pos + 4:pos + 4 + ln]
        if btype == 4:
            meta.merge(parse_vorbis_comment(block))
        elif btype == 6:
            pic = parse_flac_picture(block)
            if pic.cover and not meta.cover:
                meta.cover, meta.cover_mime = pic.cover, pic.cover_mime
        pos += 4 + ln
        if hdr & 0x80:
            break
    return meta


def _wav_chunks(fh) -> list[tuple[bytes, bytes]]:
    """RIFF/WAVE parcalarindan yalniz etiket tasiyanlari (LIST, id3) oku; ses verisi atlanir (seek)."""
    out = []
    head = fh.read(12)
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        return out
    while True:
        hdr = fh.read(8)
        if len(hdr) < 8:
            break
        cid = hdr[:4]
        ln = struct.unpack("<I", hdr[4:])[0]
        if cid in (b"LIST", b"id3 ", b"ID3 ") and ln <= MAX_TAG_BYTES:
            out.append((cid, fh.read(ln)))
            if ln & 1:
                fh.seek(1, os.SEEK_CUR)
        else:
            fh.seek(ln + (ln & 1), os.SEEK_CUR)
    return out


def parse_wav(data: bytes) -> AudioMeta:
    import io
    return parse_wav_chunks(_wav_chunks(io.BytesIO(data)))


def parse_wav_chunks(chunks: list[tuple[bytes, bytes]]) -> AudioMeta:
    meta = AudioMeta()
    for cid, body in chunks:
        if cid == b"LIST" and body[:4] == b"INFO":
            p = 4
            info: dict[bytes, str] = {}
            while p + 8 <= len(body):
                sid = body[p:p + 4]
                sl = struct.unpack("<I", body[p + 4:p + 8])[0]
                raw = body[p + 8:p + 8 + sl].split(b"\x00")[0]
                try:
                    info[sid] = _clean(raw.decode("utf-8"))
                except UnicodeDecodeError:
                    info[sid] = _clean(raw.decode("latin-1"))
                p += 8 + sl + (sl & 1)
            meta.merge(AudioMeta(title=info.get(b"INAM", ""), artist=info.get(b"IART", ""),
                                 album=info.get(b"IPRD", ""), year=_year(info.get(b"ICRD", "")),
                                 genre=info.get(b"IGNR", "")))
        elif cid in (b"id3 ", b"ID3 "):
            meta.merge(parse_id3v2(body)[0])
    return meta


def _read_head(path: str) -> bytes:
    """Etiketler dosyanin basindadir; ID3 boyutu biliniyorsa o kadarini oku."""
    with open(path, "rb") as fh:
        head = fh.read(64 * 1024)
        need = 0
        if head[:3] == b"ID3" and len(head) >= 10:
            need = 10 + _syncsafe(head[6:10]) + 64 * 1024
        elif head[:4] in (b"fLaC", b"OggS"):
            need = 2 * 1024 * 1024        # yorum + kapak blogu genelde ilk ~2 MB'ta
        if need > len(head):
            head += fh.read(min(need, MAX_TAG_BYTES) - len(head))
    return head


def read_metadata(path: str) -> AudioMeta:
    """Hata durumunda bos AudioMeta (asla istisna firlatmaz)."""
    try:
        head = _read_head(path)
    except OSError:
        return AudioMeta()
    try:
        if head[:4] == b"OggS":
            meta = parse_ogg(head)
        elif head[:4] == b"fLaC" or (head[:3] == b"ID3" and b"fLaC" in head[:MAX_TAG_BYTES]
                                      and path.lower().endswith(".flac")):
            meta = parse_flac(head)
        elif head[:4] == b"RIFF":
            with open(path, "rb") as fh:          # etiket parcalari ses verisinden SONRA olabilir
                meta = parse_wav_chunks(_wav_chunks(fh))
        else:
            meta = parse_id3v2(head)[0]
            if not (meta.title and meta.artist):
                try:
                    with open(path, "rb") as fh:
                        fh.seek(0, os.SEEK_END)
                        if fh.tell() >= 128:
                            fh.seek(-128, os.SEEK_END)
                            meta.merge(parse_id3v1(fh.read(128)))
                except OSError:
                    pass
    except Exception:
        return AudioMeta()
    return meta


def meta_from_filename(path: str) -> tuple[str, str]:
    """(sanatci, baslik) dosya adindan. 'Artist - Title' / '01 - Artist - Title' / '01. Title'."""
    stem = os.path.splitext(os.path.basename(path))[0]
    stem = _clean(stem.replace("_", " "))
    stripped = re.sub(r"^\s*\d{1,3}\s*[-._)]\s*", "", stem)
    if stripped:
        stem = stripped
    if " - " in stem:
        artist, title = stem.split(" - ", 1)
        return artist.strip(), title.strip() or stem
    return "", stem
