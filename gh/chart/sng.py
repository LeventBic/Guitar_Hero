"""Clone Hero .sng paketi (SNGPKG) okuyucu / acici (pygame IMPORT ETMEZ).

Bicim (https://github.com/mdsitton/SngFileFormat, little endian):
  header   "SNGPKG" | version uint32 | xorMask 16 bayt
  metadata uint64 uzunluk | uint64 adet | (int32 anahtarUzunluk, anahtar, int32 degerUzunluk, deger)*
  dosyalar uint64 uzunluk | uint64 adet | (uint8 adUzunluk, ad, uint64 boyut, uint64 konum)*
  veri     uint64 uzunluk | maskeli dosya baytlari (konum dosyanin basindan)
Maske (her dosya icin i = 0'dan): bayt ^= xorMask[i % 16] ^ (i & 0xFF)
Metadata, song.ini'nin [song] bolumudur (paketin icinde ayrica song.ini yoktur).
"""
from __future__ import annotations

import os
import struct

import numpy as np

MAGIC = b"SNGPKG"


class SngError(ValueError):
    pass


def _unmask(data: bytes, mask: bytes) -> bytes:
    a = np.frombuffer(data, dtype=np.uint8)
    i = np.arange(a.size, dtype=np.uint64)
    key = np.frombuffer(mask, dtype=np.uint8)[(i % 16).astype(np.intp)] ^ (i & 0xFF).astype(np.uint8)
    return (a ^ key).tobytes()


def read_sng(path: str) -> tuple[dict[str, str], dict[str, bytes]]:
    """(metadata, {dosya adi: icerik})."""
    with open(path, "rb") as f:
        buf = f.read()
    if buf[:6] != MAGIC:
        raise SngError("not an SNGPKG file")
    mask = buf[10:26]
    pos = 26

    def u64() -> int:
        nonlocal pos
        if pos + 8 > len(buf):
            raise SngError("truncated file")
        v = struct.unpack_from("<Q", buf, pos)[0]
        pos += 8
        return v

    meta_len = u64()
    meta_end = pos + meta_len
    count = u64()
    meta: dict[str, str] = {}
    for _ in range(count):
        kl = struct.unpack_from("<i", buf, pos)[0]
        pos += 4
        k = buf[pos:pos + kl].decode("utf-8", "replace")
        pos += kl
        vl = struct.unpack_from("<i", buf, pos)[0]
        pos += 4
        meta[k] = buf[pos:pos + vl].decode("utf-8", "replace")
        pos += vl
    pos = meta_end
    idx_len = u64()
    idx_end = pos + idx_len
    n = u64()
    entries = []
    for _ in range(n):
        nl = buf[pos]
        pos += 1
        name = buf[pos:pos + nl].decode("utf-8", "replace")
        pos += nl
        size, offset = struct.unpack_from("<QQ", buf, pos)
        pos += 16
        entries.append((name, size, offset))
    pos = idx_end
    u64()                                   # veri bolumu uzunlugu (konumlar dosya basina gore)
    files: dict[str, bytes] = {}
    for name, size, offset in entries:
        if offset + size > len(buf):
            raise SngError(f"truncated data for {name}")
        files[name] = _unmask(buf[offset:offset + size], mask)
    return meta, files


def _safe_name(name: str) -> str:
    base = os.path.basename(name.replace("\\", "/"))
    if not base or base in (".", ".."):
        raise SngError(f"bad file name in package: {name!r}")
    return base


def extract_sng(path: str, dest: str) -> str:
    """Paketi `dest` klasorune ac: icindeki dosyalar + metadata'dan song.ini. Klasor yolunu dondur."""
    meta, files = read_sng(path)
    os.makedirs(dest, exist_ok=True)
    for name, data in files.items():
        with open(os.path.join(dest, _safe_name(name)), "wb") as f:
            f.write(data)
    lines = ["[song]"] + [f"{k} = {str(v).replace(chr(10), ' ').replace(chr(13), ' ')}" for k, v in meta.items()]
    with open(os.path.join(dest, "song.ini"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(lines) + "\n")
    return dest


__all__ = ["read_sng", "extract_sng", "SngError"]
