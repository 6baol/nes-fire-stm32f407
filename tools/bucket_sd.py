"""Reorganize a flat ROM directory into buckets to shorten FatFs path scans.

The firmware opens a ROM or its .COV by scanning the directory from the first
entry.  A 1550-entry directory is O(1550) per open; bucketing into ~100-entry
subdirectories makes every lookup two orders of magnitude cheaper.

    python tools/bucket_sd.py F:/NES/famicom --bucket-size 100 --apply

Dry-run is the default.  The tool moves each ROM with its same-stem .COV,
remaps the path-keyed favorites/recent records in PREFS0/1.DAT, and renames
CATALOG.IDX/.NEW/.BAK to .OLD so the firmware rebuilds the catalog on boot.

Pinyin is stored in CATALOG.IDX by tools/make_pinyin.py; after the rebuild the
catalog's pinyin field is empty until that tool is run again on the card (labels
still come from the filenames).  COMPAT.IDX is bound to the old snapshot and is
rechecked on demand.
"""
import argparse
import os
import re
import shutil
import struct
import zlib
from pathlib import Path

PREF_MAGIC = 0x3152504E          # "NPR1"
PREF_SIZE = 792
PREF_FAV_MAX = 64
PREF_RECENT_MAX = 32
PREF_FAV_OFFSET = 16
PREF_RECENT_OFFSET = 528
PREF_CRC_OFFSET = 784
PREF_RESERVED_OFFSET = 788


def path_key(relative):
    """FNV-1a 64-bit over the UTF-8 path, ASCII lower-cased, as prefs_key()."""
    key = 14695981039346656037
    for byte in relative.encode('utf-8'):
        if 65 <= byte <= 90:
            byte += 32
        key = ((key ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return key


def read_prefs(path):
    data = path.read_bytes()
    if len(data) != PREF_SIZE:
        return None
    magic, generation, favorite_count, recent_count = struct.unpack_from('<IIII', data, 0)
    if magic != PREF_MAGIC or favorite_count > PREF_FAV_MAX or recent_count > PREF_RECENT_MAX:
        return None
    if struct.unpack_from('<I', data, PREF_RESERVED_OFFSET)[0] != 0:
        return None
    if struct.unpack_from('<I', data, PREF_CRC_OFFSET)[0] != (zlib.crc32(data[:PREF_CRC_OFFSET]) & 0xFFFFFFFF):
        return None
    favorites = list(struct.unpack_from('<%dQ' % PREF_FAV_MAX, data, PREF_FAV_OFFSET))
    recent = list(struct.unpack_from('<%dQ' % PREF_RECENT_MAX, data, PREF_RECENT_OFFSET))
    return data, generation, favorite_count, recent_count, favorites, recent


def count_pref_changes(path, mapping):
    parsed = read_prefs(path)
    if parsed is None:
        return None
    _, _, favorite_count, recent_count, favorites, recent = parsed
    changed = sum(1 for key in favorites[:favorite_count] if key in mapping)
    changed += sum(1 for key in recent[:recent_count] if key in mapping)
    return changed


def remap_prefs(path, mapping):
    parsed = read_prefs(path)
    if parsed is None:
        return None
    data, generation, favorite_count, recent_count, favorites, recent = parsed
    changed = 0
    for i in range(favorite_count):
        new = mapping.get(favorites[i])
        if new is not None:
            favorites[i] = new
            changed += 1
    for i in range(recent_count):
        new = mapping.get(recent[i])
        if new is not None:
            recent[i] = new
            changed += 1
    out = bytearray(data)
    struct.pack_into('<I', out, 4, generation + 1)
    struct.pack_into('<%dQ' % PREF_FAV_MAX, out, PREF_FAV_OFFSET, *favorites)
    struct.pack_into('<%dQ' % PREF_RECENT_MAX, out, PREF_RECENT_OFFSET, *recent)
    struct.pack_into('<I', out, PREF_CRC_OFFSET, zlib.crc32(out[:PREF_CRC_OFFSET]) & 0xFFFFFFFF)
    path.write_bytes(out)
    return changed


def move_file(source, destination):
    if destination.exists():
        raise FileExistsError(destination)
    try:
        os.replace(source, destination)
    except OSError:
        shutil.move(str(source), str(destination))


def main():
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('source', type=Path,
                        help='flat directory to bucket, e.g. F:/NES/famicom')
    parser.add_argument('--bucket-size', type=int, default=100)
    parser.add_argument('--apply', action='store_true', help='move files; default is dry-run')
    parser.add_argument('--keep-catalog', action='store_true',
                        help='do not reset CATALOG.IDX/.NEW/.BAK')
    parser.add_argument('--keep-prefs', action='store_true',
                        help='do not remap favorites/recent keys')
    args = parser.parse_args()

    source = args.source.resolve()
    if not source.is_dir():
        raise SystemExit(f'Not a directory: {source}')
    if args.bucket_size < 1:
        raise SystemExit('--bucket-size must be positive')

    entries = [p for p in source.iterdir() if p.is_dir() and re.fullmatch(r'\d{2,3}', p.name)]
    if entries:
        raise SystemExit('Source already contains numeric bucket directories; refusing to mix.')

    files = [p for p in source.iterdir() if p.is_file()]
    roms = sorted((p for p in files if p.suffix.lower() in ('.nes', '.fds')),
                  key=lambda p: p.name.lower())
    covers = {p.stem.lower(): p for p in files if p.suffix.upper() == '.COV'}
    if not roms:
        raise SystemExit('No .nes/.fds files at the top level of the source directory.')

    bucket_count = (len(roms) + args.bucket_size - 1) // args.bucket_size
    plan = []
    missing_covers = []
    key_map = {}
    width = max(2, len(str(bucket_count - 1)))
    for index, rom in enumerate(roms):
        bucket = source / f'{index // args.bucket_size:0{width}d}'
        cover = covers.get(rom.stem.lower())
        if cover is None:
            missing_covers.append(rom.name)
        old_rel = f'{source.name}/{rom.name}'
        new_rel = f'{source.name}/{bucket.name}/{rom.name}'
        key_map[path_key(old_rel)] = path_key(new_rel)
        plan.append((rom, cover, bucket))

    root = source.parent
    prefs = [root / 'PREFS0.DAT', root / 'PREFS1.DAT']
    pref_changes = {}
    if not args.keep_prefs:
        for path in prefs:
            if path.exists():
                count = count_pref_changes(path, key_map)
                if count is not None:
                    pref_changes[path.name] = count

    catalogs = [root / name for name in ('CATALOG.IDX', 'CATALOG.NEW', 'CATALOG.BAK')]
    catalog_reset = [p for p in catalogs if p.exists()]

    print(f'source: {source}')
    print(f'roms: {len(roms)}  covers matched: {len(roms) - len(missing_covers)}  '
          f'buckets: {bucket_count} x <= {args.bucket_size}')
    for bucket in sorted({item[2] for item in plan}):
        count = sum(1 for item in plan if item[2] == bucket)
        print(f'  {bucket.relative_to(root)}: {count} pairs')
    if missing_covers:
        print(f'  missing covers: {len(missing_covers)}')
        for name in missing_covers[:8]:
            print(f'    {name}')
    if pref_changes:
        print('favorites/recent keys to remap:')
        for name, count in pref_changes.items():
            print(f'  {name}: {count}')
    elif not args.keep_prefs:
        print('favorites/recent keys to remap: none (no valid PREFS file)')
    if catalog_reset:
        print('catalog reset:', ', '.join(p.name + ' -> ' + p.name + '.OLD' for p in catalog_reset))
    else:
        print('catalog reset: no catalog file present')

    # Check every destination before moving anything.
    targets = []
    for rom, cover, bucket in plan:
        targets.append((rom, bucket / rom.name))
        if cover is not None:
            targets.append((cover, bucket / cover.name))
    conflicts = [str(dst) for _, dst in targets if dst.exists()]
    if conflicts:
        raise SystemExit('Destination already exists; nothing moved:\n  ' + '\n  '.join(conflicts[:10]))

    if not args.apply:
        print('dry-run only; pass --apply to move the files.')
        return

    for count, (rom, cover, bucket) in enumerate(plan, 1):
        bucket.mkdir(exist_ok=True)
        move_file(rom, bucket / rom.name)
        if cover is not None:
            move_file(cover, bucket / cover.name)
        if count % 100 == 0 or count == len(plan):
            print(f'moved {count}/{len(plan)} pairs')

    if not args.keep_prefs:
        for path in prefs:
            if path.exists():
                changed = remap_prefs(path, key_map)
                if changed:
                    print(f'remapped {changed} keys in {path.name}')

    if not args.keep_catalog:
        for path in catalog_reset:
            target = path.with_name(path.name + '.OLD')
            if target.exists():
                target.unlink()
            path.replace(target)

    print('done. Insert the card into the board and power on once to rebuild the catalog.')
    print('If pinyin search is used, put the card back in the PC and run '
          'tools/make_pinyin.py on the new CATALOG.IDX.')


if __name__ == '__main__':
    main()
