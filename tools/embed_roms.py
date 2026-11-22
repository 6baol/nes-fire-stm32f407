"""Build the multi-game ROM table embedded in the firmware.

Usage:
    python tools/embed_roms.py                 # rebuild from Roms/roms.json
    python tools/embed_roms.py list            # show the current game list
    python tools/embed_roms.py add FILE.nes [--label "SHORT NAME"]
    python tools/embed_roms.py remove FILE.nes

The generated table is User/nes/nes_roms.c. It keeps nes_rom/nes_rom_size as
aliases of the first game so single-ROM tooling and tests keep working.
"""
import argparse, hashlib, json, re, sys
from pathlib import Path

root = Path(__file__).resolve().parents[1]
roms_dir = root / 'Roms'
manifest_path = roms_dir / 'roms.json'
out_c = root / 'User/nes/nes_roms.c'
out_h = root / 'User/nes/nes_roms.h'

SUPPORTED = (0, 1, 2, 3, 4, 5, 7, 11, 20, 33, 40, 66, 71, 74, 117)
LABEL_MAX = 46  # Two 23-character menu lines; preserve complete game names.


def normalize(d):
    """Lossless payload conversion for plain NES2.0 cartridges.
    NESdev NES_2.0: byte12=0/2 is NTSC, byte15=1 is standard pads, submapper 0.
    Only the 16-byte header is rewritten; PRG/CHR bytes are untouched and the
    user's original file is never modified.
    """
    if len(d) >= 16 and d[:4] == b'NES\x1a' and d[7] & 12 == 8:
        mapper=(d[6]>>4)|(d[7]&0xf0)
        ram_ok=d[10]==0 or (mapper==5 and d[10] in (7,0x70))
        if not (d[7] & 3 == 0 and d[8] == 0 and d[9] == 0 and ram_ok
                and d[11] == 0 and d[12] in (0, 2) and d[13] == 0 and d[14] == 0
                and d[15] in (0, 1) and not (d[6] & 12)):
            raise ValueError('NES2 conversion supports plain NTSC cartridges only '
                             '(submapper 0, no extra RAM/devices/trainer/battery/four-screen)')
        header = bytearray(d[:16]); header[7] &= 0xf3; header[8:16] = bytes(8)
        if mapper==5 and d[10]:header[8]=1
        return bytes(header) + d[16:]
    return d


def validate(d):
    if d[:4] == b'FDS\x1a' or d[:15] == b'\x01*NINTENDO-HVC*':
        validate_fds(d)
        return 20
    if len(d) < 16 or d[:4] != b'NES\x1a':
        raise ValueError('Not an iNES ROM')
    if d[7] & 15 or d[6] & 12 or d[9] & 1:
        raise ValueError('Only NTSC iNES, no trainer/four-screen/NES2/VS')
    mapper = (d[6] >> 4) | (d[7] & 0xf0); prg, chr = d[4], d[5]
    if mapper not in SUPPORTED or mapper == 20:
        raise ValueError(f'Unsupported mapper {mapper}; supported: {", ".join(map(str, SUPPORTED))}')
    if not prg or prg & (prg - 1):
        raise ValueError('PRG count must be power of two')
    if mapper == 2 and (prg > 32 or chr):
        raise ValueError('UxROM requires CHR RAM, PRG <=512 KiB')
    if mapper == 5 and (prg>32 or not chr or chr&(chr-1) or chr>32 or d[8]>1):
        raise ValueError('MMC5 preview: PRG <=512 KiB, power-of-two CHR ROM <=256 KiB, WRAM <=8 KiB')
    if mapper == 1 and (prg > 16 or d[8] > 1 or (chr and (chr & (chr-1) or chr > 16))):
        raise ValueError('Basic MMC1B: PRG <=256 KiB, CHR power-of-two <=128 KiB, WRAM <=8 KiB')
    if mapper == 7 and (not 2 <= prg <= 16 or chr or d[8] or d[6]&2):
        raise ValueError('AxROM requires 32-256 KiB PRG, 8 KiB CHR RAM, no WRAM/battery')
    if mapper in (11,66) and (not 2 <= prg <= 8 or not chr or chr & (chr-1)
                             or chr > (16 if mapper==11 else 4) or d[8] or d[6]&2):
        raise ValueError(f'Mapper {mapper}: PRG 32-128 KiB, power-of-two CHR ROM '
                         f'8-{128 if mapper==11 else 32} KiB, no WRAM/battery')
    if mapper == 71 and (not 2 <= prg <= 16 or chr or d[8] or d[6]&2):
        raise ValueError('Camerica requires 32-256 KiB PRG, 8 KiB CHR RAM, no WRAM/battery')
    if mapper in (0, 3) and prg > 2:
        raise ValueError('NROM/CNROM PRG <=32 KiB')
    if mapper == 0 and chr > 1:
        raise ValueError('NROM CHR <=8 KiB')
    if mapper == 3 and (not chr or chr & (chr - 1) or chr > 16):
        raise ValueError('CNROM CHR must be power of two <=128 KiB')
    if mapper == 4 and (not 2 <= prg <= 32 or chr > 32 or (chr and chr & (chr - 1))):
        raise ValueError('MMC3 requires 32-512 KiB PRG and power-of-two CHR <=256 KiB')
    if mapper == 40 and (prg > 4 or not chr or chr & (chr - 1) or chr > 8):
        raise ValueError('MMC PRG <=64 KiB, CHR power of two <=64 KiB')
    if mapper in (74, 117) and (not 2 <= prg <= 32 or not chr or chr & (chr - 1)
                                or chr > 32 or d[8]):
        raise ValueError('Mapper 74/117 requires 32-512 KiB PRG, power-of-two '
                         'CHR 8-256 KiB and no WRAM')
    if mapper == 33 and (not 2 <= prg <= 32 or not chr or chr & (chr - 1)
                         or chr > 32 or d[8]):
        raise ValueError('TC0190 requires 32-512 KiB PRG, power-of-two '
                         'CHR 8-256 KiB and no WRAM')
    if mapper == 16 and (not 2 <= prg <= 16 or not chr or chr & (chr - 1)
                         or chr > 32 or d[8] > 1):
        raise ValueError('Bandai FCG requires 32-256 KiB PRG, power-of-two '
                         'CHR 8-256 KiB and no EEPROM/WRAM image')
    size = 16 + prg * 16384 + chr * 8192
    if len(d) != size:
        raise ValueError(f'Expected {size} bytes, received {len(d)}')
    boot_bytes=32768 if mapper in (7,11,66) else prg*16384
    reset=int.from_bytes(d[16+boot_bytes-4:16+boot_bytes-2],'little')
    if reset<0x8000:
        raise ValueError('Cartridge reset vector is outside ROM; use a complete .fds image for FDS games')
    cap = 896 if mapper == 5 else (888 if chr > 16 else 640)
    if size > cap * 1024:
        raise ValueError('Single ROM exceeds its SD preload arena (MMC5 896 KiB, '
                         'large CHR 888 KiB, others 640 KiB)')
    return mapper


def validate_fds(data):
    """Validate block boundaries before embedding; firmware validates again."""
    offset = 16 if data[:4] == b'FDS\x1a' else 0
    sides = data[4] if offset and len(data) >= 16 else len(data)//65500
    if not 1 <= sides <= 8 or len(data) != offset+sides*65500:
        raise ValueError('Invalid FDS side count or file size')
    if sides!=1:
        raise ValueError('Only single-side FDS is currently playable; automatic disk-side switching is not implemented')
    for side in range(sides):
        start = offset+side*65500
        end = start+65500
        if data[start:start+15] != b'\x01*NINTENDO-HVC*' or data[start+56] != 2:
            raise ValueError('Invalid FDS disk header or file count block')
        p = start+58
        for _ in range(data[start+57]):
            if p+17 > end or data[p] != 3 or data[p+16] != 4:
                raise ValueError('Invalid FDS file header/data block')
            address = int.from_bytes(data[p+11:p+13], 'little')
            size = int.from_bytes(data[p+13:p+15], 'little')
            kind = data[p+15]
            if (kind > 2 or p+17+size > end or
                (kind == 0 and not 0x6000 <= address <= address+size <= 0xe000) or
                (kind == 1 and address+size > 0x2000) or
                (kind == 2 and not 0x2000 <= address <= address+size <= 0x4000)):
                raise ValueError('FDS file length or destination out of bounds')
            p += 17+size


def auto_label(name):
    stem = Path(name).stem
    stem = re.sub(r'^\([^)]*\)\s*', '', stem)
    stem = re.sub(r'\s*\([^)]*\)\s*', ' ', stem)
    stem = stem.replace(';', ' ').replace('_', ' ').replace('-', ' ')
    stem = ''.join(c for c in stem.upper() if 32 <= ord(c) < 127)
    stem = re.sub(r'\s+', ' ', stem).strip()
    return stem or 'UNTITLED'


def load_manifest():
    if manifest_path.exists():
        data = json.loads(manifest_path.read_text(encoding='utf-8'))
        return data.get('games', [])
    return []


def save_manifest(games):
    manifest_path.write_text(json.dumps({'games': games}, indent=2, ensure_ascii=False), encoding='utf-8')


def prepare(entry):
    """Read, normalize and validate one manifest entry."""
    path = roms_dir / entry['file']
    if not path.exists():
        raise FileNotFoundError(f'missing ROM: {path}')
    original = path.read_bytes()
    data = normalize(original)
    mapper = validate(data)
    label = checked_label(entry.get('label') or auto_label(path.name))
    return dict(file=path.name, label=label, data=data, mapper=mapper,
                source_sha256=hashlib.sha256(original).hexdigest(),
                sha256=hashlib.sha256(data).hexdigest(), normalized=data != original)


def checked_label(label):
    label=label.strip().upper()
    if not label or len(label)>LABEL_MAX or any(not 32<=ord(c)<127 for c in label):
        raise ValueError(f'Game name must be 1-{LABEL_MAX} printable ASCII characters')
    return label


def check_budget(game_list):
    if not game_list or len(game_list)>64:
        raise ValueError('SD library must contain 1-64 entries')
    if any(len(g['data'])>(896 if g.get('mapper')==5 else 640)*1024 for g in game_list):
        raise ValueError('Single ROM exceeds its SD preload arena')

def check_embedded_budget(game_list):
    check_budget(game_list)
    if sum(len(g['data']) for g in game_list)>768*1024:
        raise ValueError('Embedded ROM payload exceeds 768 KiB; use the SD build')


def add_game(src,label=None):
    """Validate the whole proposed list before modifying sources or metadata."""
    src=Path(src)
    original=src.read_bytes();data=normalize(original);mapper=validate(data)
    entry={'file':src.name,'label':checked_label(label or auto_label(src.name))}
    candidate=dict(entry,data=data,mapper=mapper,source_sha256=hashlib.sha256(original).hexdigest(),
                   sha256=hashlib.sha256(data).hexdigest(),normalized=data!=original)
    games=load_manifest();index=next((i for i,g in enumerate(games) if g['file'].casefold()==src.name.casefold()),None)
    if index is None:games.append(entry);index=len(games)-1
    else:entry['file']=games[index]['file'];candidate['file']=entry['file'];games[index]=entry
    prepared=[candidate if i==index else prepare(g) for i,g in enumerate(games)]
    check_budget(prepared)
    dst=roms_dir/entry['file']
    paths=[dst,manifest_path,out_c,out_h,roms_dir/'current.json']
    backup={p:p.read_bytes() if p.exists() else None for p in paths}
    try:
        if src.resolve()!=dst.resolve():dst.write_bytes(original)
        emit(prepared);save_manifest(games)
    except Exception:
        for p,previous in backup.items():
            if previous is None:
                if p.exists():p.unlink()
            else:p.write_bytes(previous)
        raise
    report(prepared)
    return entry


def emit(game_list):
    if not game_list:
        raise SystemExit('no games in Roms/roms.json; run "embed_roms.py add FILE.nes" first')
    lines = ['/* Generated by tools/embed_roms.py. Do not edit by hand. */',
             '#include "nes_roms.h"', '']
    for i, g in enumerate(game_list):
        symbol = 'nes_rom' if i == 0 else f'rom_{i}'
        if i:lines.append('#ifndef NES_SD_LIBRARY')
        body = ''.join(','.join(f'0x{b:02x}' for b in g['data'][j:j + 24]) + ',\n'
                       for j in range(0, len(g['data']), 24))
        lines.append(f'/* {i}: {g["file"]} */')
        lines.append(f'{"const" if i == 0 else "static const"} uint8_t {symbol}[] = {{')
        lines.append(body + '};')
        if i:lines.append('#endif')
    lines.append('const uint32_t nes_rom_size = sizeof(nes_rom);')
    lines.append('const NesRomImage nes_rom_images[] = {')
    for i, g in enumerate(game_list):
        symbol = 'nes_rom' if i == 0 else f'rom_{i}'
        if i:lines.append('#ifndef NES_SD_LIBRARY')
        lines.append(f'  {{{json.dumps(g["label"])},{json.dumps(g["file"])},{symbol},sizeof({symbol}),{g["mapper"]}}},')
        if i:lines.append('#endif')
    lines.append('};')
    lines.append('const uint32_t nes_rom_image_count = '
                 'sizeof(nes_rom_images)/sizeof(nes_rom_images[0]);')
    lines.append('')
    out_c.write_text('\n'.join(lines), encoding='utf-8')

    header = '''#ifndef NES_ROMS_H
#define NES_ROMS_H
#include <stdint.h>
/* One embedded game. label is short ASCII for the 480x800 menu. */
typedef struct {
    const char *label;
    const char *file;
    const uint8_t *data;
    uint32_t size;
    uint8_t mapper;
} NesRomImage;
extern const NesRomImage nes_rom_images[];
extern const uint32_t nes_rom_image_count;
/* Default game, kept for single-ROM tools and tests. */
extern const uint8_t nes_rom[];
extern const uint32_t nes_rom_size;
#endif
'''
    out_h.write_text(header, encoding='utf-8')

    default = game_list[0]
    (roms_dir / 'current.json').write_text(json.dumps(dict(
        name=default['file'], mapper=default['mapper'], size=len(default['data']),
        sha256=default['sha256'], source_sha256=default['source_sha256'],
        header_normalized=default['normalized'],
        games=[dict(name=g['file'], label=g['label'], mapper=g['mapper'],
                    size=len(g['data']), sha256=g['sha256']) for g in game_list],
    ), indent=2, ensure_ascii=False), encoding='utf-8')


def report(game_list):
    total = sum(len(g['data']) for g in game_list)
    print(f'{"#":<3}{"label":<28}{"file":<46}{"map":>4}{"bytes":>8}')
    for i, g in enumerate(game_list):
        print(f'{i:<3}{g["label"]:<28}{g["file"]:<46}{g["mapper"]:>4}{len(g["data"]):>8}')
    print(f'total SD ROM payload: {total} bytes ({total/1024:.1f} KiB); '
          f'library <=64 games, each <=640 KiB (MMC5 <=896 KiB); embedded build <=768 KiB total')


def build():
    entries = load_manifest()
    game_list = [prepare(e) for e in entries]
    check_budget(game_list)
    emit(game_list)
    report(game_list)
    print(f'wrote {out_c.relative_to(root)} and {out_h.relative_to(root)}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest='cmd')
    a = sub.add_parser('add', help='add or replace a game')
    a.add_argument('rom', type=Path)
    a.add_argument('--label')
    r = sub.add_parser('remove', help='remove a game')
    r.add_argument('rom', type=Path)
    sub.add_parser('list', help='show the game list')
    sub.add_parser('build', help='regenerate from Roms/roms.json')
    sub.add_parser('check-embedded',help='validate the optional all-in-Flash build budget')
    check=sub.add_parser('check',help='read-only format/mapper check; no menu changes')
    check.add_argument('rom',type=Path)
    args = p.parse_args()

    if args.cmd == 'check-embedded':
        check_embedded_budget([prepare(e) for e in load_manifest()])
    elif args.cmd == 'add':
        add_game(args.rom,args.label)
    elif args.cmd == 'check':
        raw=args.rom.read_bytes();data=normalize(raw);mapper=validate(data)
        print(f'Format accepted: mapper={mapper}, bytes={len(data)}, normalized={data!=raw}')
        print('This checks format and implemented mapper only; game compatibility still needs testing.')
    elif args.cmd == 'remove':
        name = args.rom.name
        games = [g for g in load_manifest() if g['file'] != name]
        if len(games) == len(load_manifest()):
            raise SystemExit(f'not in manifest: {name}')
        prepared=[prepare(g) for g in games];check_budget(prepared)
        emit(prepared);save_manifest(games);report(prepared)
    elif args.cmd == 'list':
        report([prepare(e) for e in load_manifest()])
    else:
        build()


if __name__ == '__main__':
    try:main()
    except (ValueError,OSError) as exc:raise SystemExit(str(exc))
