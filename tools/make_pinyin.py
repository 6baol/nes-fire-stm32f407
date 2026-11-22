"""Fill the pinyin field of NES/CATALOG.IDX so Chinese names are searchable.

Type ASCII in the on-screen search: "bian", "bianfuxia" or "bfx" all match
蝙蝠侠. English names keep matching directly. Run this whenever the catalog was
rebuilt (new games) — the firmware preserves the field for unchanged entries.

Usage:
    make_pinyin.py F:/NES/CATALOG.IDX
"""
import struct
import sys
from pathlib import Path

try:
    from pypinyin import lazy_pinyin
except ImportError:
    sys.exit('pip install pypinyin first')

MAGIC = b'NESCAT5'
HEADER = 32
RECORD = 312
PATH_OFF, PATH_LEN = 12, 161
LABEL_OFF, LABEL_LEN = 173, 97
PINYIN_OFF, PINYIN_LEN = 270, 40


def pinyin_for(label):
    chars = [c for c in label if ord(c) > 0x7F or c.isalnum()]
    syl = lazy_pinyin(''.join(chars))
    # Punctuation can pass through lazy_pinyin; keep the field ASCII only.
    full = ''.join(c for c in ''.join(syl).lower() if 32 <= ord(c) < 127)
    initials = ''.join(p[0] for p in syl if p and 32 <= ord(p[0]) < 127).lower()
    text = full if full == initials else f'{full} {initials}'
    return text[:PINYIN_LEN - 1]


def main(path):
    data = bytearray(Path(path).read_bytes())
    if data[:7] != MAGIC:
        sys.exit('not a v0.28+ catalog')
    count = struct.unpack_from('<I', data, 8)[0]
    if struct.unpack_from('<I', data, 16)[0] != RECORD:
        sys.exit('unexpected record size')
    if len(data) < HEADER + count * RECORD:
        sys.exit('truncated catalog')
    filled = 0
    for i in range(count):
        base = HEADER + i * RECORD
        label = data[base + LABEL_OFF:base + LABEL_OFF + LABEL_LEN].split(b'\0')[0]
        text = pinyin_for(label.decode('utf-8', 'replace'))
        field = text.encode('ascii')
        if not field:
            continue
        data[base + PINYIN_OFF:base + PINYIN_OFF + PINYIN_LEN] = field.ljust(PINYIN_LEN, b'\0')
        filled += 1
    Path(path).write_bytes(bytes(data))
    print(f'filled pinyin for {filled}/{count} entries')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
