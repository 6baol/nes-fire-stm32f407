"""Read a firmware-generated NES catalog and optionally export library metadata.

Without output options, this only inventories the catalog and checks ROMs.
COMPAT.IDX belongs beside CATALOG.IDX on the card after the firmware has scanned
the library. Regenerate it when the catalog snapshot changes.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import struct
import tempfile
import zlib

import embed_roms

CATALOG_HEADER = struct.Struct('<8s4I8x')
CATALOG_ENTRY = struct.Struct('<III161s97s40s2x')
COMPAT_HEADER = struct.Struct('<8sIII')
COMPAT_ENTRY = struct.Struct('<HBb')
UNKNOWN_MAPPER = 0xFFFF
CHECK_FAILED = -10
HEADER_OK = 1
DESCRIPTIONS = {
    1: 'Static checks passed',
    -1: 'Bad ROM signature',
    -2: 'Unsupported mapper',
    -3: 'Unsupported PRG or CHR layout',
    -4: 'Image exceeds SRAM arena',
    -5: 'Unsupported timing region',
    -6: 'Trainer present',
    -7: 'Four-screen mirroring',
    -8: 'Unsupported console variant',
    -9: 'Unsupported NES 2.0 fields',
    -10: 'Missing or unavailable for inspection',
    -11: 'Reset vector outside PRG',
    -12: 'Unsupported or unidentified hardware variant',
    -13: 'File length differs from the header',
}


def catalog_records(data):
    if len(data) < CATALOG_HEADER.size:
        raise ValueError('truncated catalog header')
    magic, count, snapshot, width, window = CATALOG_HEADER.unpack_from(data)
    if (magic != b'NESCAT5\0' or not 0 < count <= 2048 or
            width != CATALOG_ENTRY.size or window != 4 or
            len(data) != CATALOG_HEADER.size + count * width):
        raise ValueError('invalid NESCAT5 layout')
    return snapshot, list(CATALOG_ENTRY.iter_unpack(data[CATALOG_HEADER.size:]))


def decode_field(field):
    return field.split(b'\0', 1)[0].decode('utf-8', 'replace')


def inspect_rom(path, catalog_size):
    try:
        with path.open('rb') as source:
            size = os.fstat(source.fileno()).st_size
            if size != catalog_size:
                return CHECK_FAILED, UNKNOWN_MAPPER, 0
            info = embed_roms.classify_header(source.read(16), size)
            code = info.status
            submapper = info.submapper
            if code == 0 and info.vector_offset:
                source.seek(info.vector_offset)
                if int.from_bytes(source.read(2), 'little') < 0x8000:
                    code = -11
            if code == 0 and info.mapper == 16 and submapper == 0:
                source.seek(16)
                submapper = embed_roms.mapper16_submapper(zlib.crc32(source.read()))
                if not submapper:
                    code = -12
            return code or HEADER_OK, info.mapper, submapper
    except OSError:
        return CHECK_FAILED, UNKNOWN_MAPPER, 0


def inspect_catalog(rom_root, catalog):
    snapshot, records = catalog_records(catalog)
    results = []
    payload = bytearray()
    for size, _, _, raw_path, raw_label, _ in records:
        relative = decode_field(raw_path)
        parts = relative.split('/')
        if any(part in ('', '.', '..') for part in parts) or '\\' in relative or ':' in relative:
            code, mapper, submapper = CHECK_FAILED, UNKNOWN_MAPPER, 0
        else:
            code, mapper, submapper = inspect_rom(rom_root.joinpath(*parts), size)
        payload += COMPAT_ENTRY.pack(mapper, submapper, 0 if code == CHECK_FAILED else code)
        results.append({'path': relative, 'title': decode_field(raw_label),
                        'bytes': size, 'status': code, 'reason': DESCRIPTIONS[code],
                        'mapper': None if mapper == UNKNOWN_MAPPER else mapper,
                        'submapper': submapper})
    compat = COMPAT_HEADER.pack(b'NESCMP1\0', len(records), snapshot, zlib.crc32(payload)) + payload
    return snapshot, results, compat


def write_atomic(path, data):
    out = tempfile.NamedTemporaryFile(dir=path.parent, prefix=path.name + '.', delete=False)
    scratch = Path(out.name)
    try:
        with out:
            out.write(data)
            out.flush()
            os.fsync(out.fileno())
        scratch.replace(path)
    finally:
        scratch.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('rom_root', type=Path, help='NES directory with ROMs and CATALOG.IDX')
    parser.add_argument('--catalog', type=Path, help='catalog input if stored outside the NES directory')
    parser.add_argument('--compat-out', type=Path, help='optional output COMPAT.IDX')
    parser.add_argument('--pinyin-out', type=Path, help='optional copy of CATALOG.IDX with pinyin aliases')
    parser.add_argument('--report', type=Path, help='optional JSON report with a result per catalog entry')
    args = parser.parse_args()
    try:
        data = (args.catalog or args.rom_root / 'CATALOG.IDX').read_bytes()
        snapshot, results, compat = inspect_catalog(args.rom_root, data)
        if args.pinyin_out:
            from make_pinyin import fill_catalog
            updated, _ = fill_catalog(data)
            write_atomic(args.pinyin_out, updated)
        if args.compat_out:
            write_atomic(args.compat_out, compat)
        counts = dict(Counter(row['reason'] for row in results))
        summary = {'catalog_snapshot': f'{snapshot:08X}', 'entries': len(results),
                   'mode': 'Static ROM checks only', 'counts': counts}
        if args.report:
            report = {**summary, 'roms': results}
            write_atomic(args.report, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode('utf-8'))
    except (OSError, ValueError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
