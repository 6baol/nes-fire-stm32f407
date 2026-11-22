"""Build NES/TITLES.DB: a fingerprint -> official title dictionary for the card.

The firmware fingerprints each ROM as
    crc32(size_le32 || first 4 KiB || last 4 KiB)
and looks the result up when it rebuilds NES/CATALOG.IDX. Fingerprints are taken
from the same bytes you put on the card, so generate this from the very files
you copy (or from the prepared pack).

Usage:
    make_titles.py --manifest --output Release/SD_ROOT/NES/TITLES.DB
    make_titles.py --roms D:\\roms --dat No-Intro.dat --output TITLES.DB
"""
import argparse, json, struct, sys, zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import embed_roms

LABEL_MAX = 46
CHUNK = 4096


def fingerprint(data):
    size = len(data)
    crc = zlib.crc32(struct.pack('<I', size))
    crc = zlib.crc32(data[:CHUNK] if size >= CHUNK else data, crc)
    if size >= CHUNK:
        crc = zlib.crc32(data[size - CHUNK:], crc)
    return crc & 0xFFFFFFFF


def clean_title(text):
    text = text.strip()
    out = []
    for c in text:
        if ord(c) < 32:
            continue
        if ord(c) < 127:
            out.append(c)
        else:
            # Keep UTF-8 titles (Chinese translations have no ASCII name).
            out.append(c)
    title = ''.join(out).strip()
    return title[:LABEL_MAX].rstrip()


def entries_from_manifest():
    out = []
    for game in embed_roms.load_manifest():
        source = ROOT / 'Roms' / game['file']
        data = embed_roms.normalize(source.read_bytes())
        out.append((fingerprint(data), clean_title(game['label']), source.name))
    return out


def parse_dat(path):
    """name -> official title from a No-Intro style DAT."""
    import xml.etree.ElementTree as ET
    root = ET.parse(path).getroot()
    titles = {}
    for game in root.iter('game'):
        title = clean_title(game.get('name') or '')
        for rom in game.findall('rom'):
            file_name = rom.get('name')
            if file_name and title:
                titles[file_name.lower()] = title
    return titles


def entries_from_roms(folder, dat):
    titles = parse_dat(dat) if dat else {}
    out = []
    for path in sorted(Path(folder).iterdir()):
        if path.suffix.lower() not in ('.nes', '.fds') or not path.is_file():
            continue
        title = titles.get(path.name.lower())
        if not title:
            title = clean_title(path.stem.replace('_', ' '))
        out.append((fingerprint(path.read_bytes()), title, path.name))
    return out


def write(entries, output):
    seen = set()
    lines = ['NESDB1']
    for digest, title, name in entries:
        if not title:
            raise SystemExit(f'empty title for {name}')
        if digest in seen:
            raise SystemExit(f'duplicate fingerprint for {name}')
        seen.add(digest)
        lines.append(f'{digest:08X}\t{title}')
    Path(output).parent.mkdir(parents=True, exist_ok=True)
    Path(output).write_text('\n'.join(lines) + '\n', encoding='ascii')
    print(f'wrote {len(entries)} titles to {output}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', action='store_true',
                        help='use Roms/roms.json (labels become the titles)')
    parser.add_argument('--roms', type=Path, help='folder of .nes/.fds files')
    parser.add_argument('--dat', type=Path, help='No-Intro DAT for --roms')
    parser.add_argument('--output', type=Path, default=ROOT / 'Release/SD_ROOT/NES/TITLES.DB')
    args = parser.parse_args()
    if args.manifest:
        entries = entries_from_manifest()
    elif args.roms:
        entries = entries_from_roms(args.roms, args.dat)
    else:
        parser.error('choose --manifest or --roms')
    write(entries, args.output)


if __name__ == '__main__':
    main()
