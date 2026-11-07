"""Encode the engine's three binary sound comments into real Ogg packets."""
import base64
from pathlib import Path
import struct
import sys

from ogg_fixture_data import mono, stereo


def crc(data):
    value = 0
    for byte in data:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
    return value


def comment(source, metadata):
    page = 0
    while page < len(source):
        assert source[page:page+4] == b"OggS"
        end = page + 27 + source[page+26]
        laces = source[page+27:end]
        following = end + sum(laces)
        if source[end:end+7] != b"\x03vorbis":
            page = following
            continue
        last = next(i for i, lace in enumerate(laces) if lace != 255)
        old = sum(laces[:last+1])
        packet = (b"\x03vorbis" + struct.pack("<I", 4) + b"IXR!" +
                  struct.pack("<II", 1, len(metadata)) + metadata + b"\x01")
        laces = bytes([len(packet)]) + laces[last+1:]
        header = bytearray(source[page:page+27])
        header[26] = len(laces)
        header[22:26] = b"\0"*4
        patched = header + laces + packet + source[end+old:following]
        patched[22:26] = struct.pack("<I", crc(patched))
        return source[:page] + patched + source[following:]
    raise ValueError("comment not found")


target = Path(sys.argv[1])
target.mkdir(parents=True, exist_ok=True)
m = base64.b64decode(mono)
s = base64.b64decode(stereo)
v1 = comment(m, struct.pack("<IffI", 1, 2.0, 190.0, 10))
v2 = comment(s, struct.pack("<IfffI", 2, 3.0, 180.0, .75, 11))
v3 = comment(m, struct.pack("<IfffIf", 3, 4.0, 170.0, .625, 12, 250.0))
for name, data in {
    "v1": v1, "v2": v2, "v3": v3, "chained": v3 + v2,
    "bad-comment": comment(m, struct.pack("<I", 999)), "bad-stream": m[:20],
    "unrecognised": m,
}.items():
    (target / (name + ".ogg")).write_bytes(data)
