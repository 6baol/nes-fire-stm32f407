"""Sort NES/CATALOG.IDX by the English title shown in the list.

The firmware writes the catalog in directory-walk order, so the list looks
sorted by the Chinese prefix.  This tool reorders the fixed 312-byte records
by the English title (the text after the last ']'), keeping the pinyin field
and the header snapshot/count intact.

    python tools/sort_catalog.py F:/NES/CATALOG.IDX
    python tools/sort_catalog.py F:/NES/CATALOG.IDX --apply
"""
import argparse
import re
import struct
from pathlib import Path

MAGIC = b'NESCAT5'
HEADER = 32
RECORD = 312
PATH_OFF, PATH_LEN = 12, 161
LABEL_OFF, LABEL_LEN = 173, 97


def field(record, offset, length):
    return record[offset:offset + length].split(b'\0')[0].decode('utf-8', 'replace')


def english_title(label, path):
    text = label.strip() or Path(path).stem
    if ']' in text:
        text = text.rsplit(']', 1)[1]
    return re.split(r'\s*[\(\[]', text, 1)[0].strip()


def sort_key(record):
    label = field(record, LABEL_OFF, LABEL_LEN)
    path = field(record, PATH_OFF, PATH_LEN)
    return (english_title(label, path).lower(), label.lower(), path.lower())


def sort_catalog(data):
    data = bytearray(data)
    if len(data) < HEADER or data[:7] != MAGIC:
        raise ValueError('not a v0.28+ catalog')
    count = struct.unpack_from('<I', data, 8)[0]
    if struct.unpack_from('<I', data, 16)[0] != RECORD:
        raise ValueError('unexpected record size')
    if len(data) != HEADER + count * RECORD:
        raise ValueError('invalid catalog length')
    records = [bytes(data[HEADER + i * RECORD:HEADER + (i + 1) * RECORD])
               for i in range(count)]
    records.sort(key=sort_key)
    for index, record in enumerate(records):
        data[HEADER + index * RECORD:HEADER + (index + 1) * RECORD] = record
    return data


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('catalog', type=Path)
    parser.add_argument('--apply', action='store_true', help='rewrite the catalog')
    args = parser.parse_args()

    data = args.catalog.read_bytes()
    result = sort_catalog(data)
    count = struct.unpack_from('<I', result, 8)[0]
    first = field(result, HEADER + LABEL_OFF, LABEL_LEN)
    last = field(result, HEADER + (count - 1) * RECORD + LABEL_OFF, LABEL_LEN)
    print(f'entries: {count}')
    print(f'first: {first}')
    print(f'last:  {last}')
    if not args.apply:
        print('dry-run only; pass --apply to rewrite the catalog.')
        return
    from prepare_library import write_atomic
    write_atomic(args.catalog, result)
    print(f'sorted {count} entries by English title')


if __name__ == '__main__':
    main()
