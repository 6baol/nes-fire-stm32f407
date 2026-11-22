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

MAGIC = b'NESCAT5'
HEADER = 32
RECORD = 312
PATH_OFF, PATH_LEN = 12, 161
LABEL_OFF, LABEL_LEN = 173, 97
PINYIN_OFF, PINYIN_LEN = 270, 40


def pinyin_for(label):
    from pypinyin import lazy_pinyin

    short_title = label[1:].partition(']')[0] if label.startswith('[') else label
    if any(ord(c) > 0x7F for c in short_title):
        label = short_title
    chars = [c for c in label if ord(c) > 0x7F or c.isalnum()]
    syl = lazy_pinyin(''.join(chars))
    # Punctuation can pass through lazy_pinyin; keep the field ASCII only.
    full = ''.join(c for c in ''.join(syl).lower() if 32 <= ord(c) < 127)
    initials = ''.join(p[0] for p in syl if p and 32 <= ord(p[0]) < 127).lower()
    if not initials or full == initials:
        return full[:PINYIN_LEN - 1]
    # Keep both aliases usable even when the full title cannot fit.
    initials = initials[:(PINYIN_LEN - 2) // 2]
    return f'{full[:PINYIN_LEN - 2 - len(initials)]} {initials}'


def fill_catalog(data):
    data = bytearray(data)
    if len(data) < HEADER or data[:7] != MAGIC:
        raise ValueError('not a v0.28+ catalog')
    count = struct.unpack_from('<I', data, 8)[0]
    if struct.unpack_from('<I', data, 16)[0] != RECORD:
        raise ValueError('unexpected record size')
    if len(data) != HEADER + count * RECORD:
        raise ValueError('invalid catalog length')
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
    return data, filled


def main(path):
    from prepare_library import write_atomic

    path = Path(path)
    try:
        data, filled = fill_catalog(path.read_bytes())
    except ImportError:
        sys.exit('pip install pypinyin first')
    write_atomic(path, data)
    count = struct.unpack_from('<I', data, 8)[0]
    print(f'filled pinyin for {filled}/{count} entries')


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(sys.argv[1])
