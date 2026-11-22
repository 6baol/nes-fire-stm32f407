"""Build NES/SEARCH.IDX: compact lowercase keys for fast on-device search.

One fixed record per catalog entry: uint16 catalog index + 24-byte key. Keys are
the lowercase ASCII of the label and its pinyin, so "mario", "bian" and "bfx"
all match. The firmware falls back to a full catalog scan when this file is
missing or its count does not match.

Run after tools/make_pinyin.py (pinyin is part of the key).

Usage:
    make_search_index.py F:/NES/CATALOG.IDX F:/NES/SEARCH.IDX
"""
import struct
import sys
from pathlib import Path

HEADER = 32
RECORD = 312
LABEL_OFF, LABEL_LEN = 173, 97
PINYIN_OFF, PINYIN_LEN = 270, 40
KEY = 24


def ascii_key(text):
    out = ''.join(c for c in text.lower() if 32 <= ord(c) < 127 and c.isprintable())
    return ' '.join(out.split())[:KEY]


def main(catalog_path, out_path):
    data = Path(catalog_path).read_bytes()
    if data[:7] != b'NESCAT5':
        sys.exit('not a v0.28+ catalog')
    count = struct.unpack_from('<I', data, 8)[0]
    if struct.unpack_from('<I', data, 16)[0] != RECORD or len(data) < HEADER + count * RECORD:
        sys.exit('unexpected catalog layout')
    blob = bytearray(b'NESIDX1')
    blob += bytes([0])
    blob += struct.pack('<I', count)
    for i in range(count):
        base = HEADER + i * RECORD
        label = data[base + LABEL_OFF:base + LABEL_OFF + LABEL_LEN].split(b'\0')[0].decode('utf-8', 'replace')
        pinyin = data[base + PINYIN_OFF:base + PINYIN_OFF + PINYIN_LEN].split(b'\0')[0].decode('ascii', 'replace')
        key = ascii_key(label + ' ' + pinyin)
        blob += struct.pack('<H', i) + key.encode('ascii').ljust(KEY, b'\0')
    Path(out_path).write_bytes(bytes(blob))
    print(f'wrote {count} search keys ({len(blob)} bytes) to {out_path}')


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
