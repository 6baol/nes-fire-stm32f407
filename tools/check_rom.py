"""Static sanity check for a .nes file, before it goes into the firmware.

    python tools/check_rom.py 'D:\\下载\\游戏.nes'

Reports the iNES header, mapper, PRG/CHR size and the three CPU vectors, and
flags the two failure modes we have actually hit:

  * a mapper the firmware does not implement;
  * a reset vector outside $8000-$FFFF, which is what raw FDS (disk system)
    data wrapped in an iNES header looks like - it just runs zeros and shows a
    black screen.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import embed_roms

MIRROR = {0: 'horizontal', 1: 'vertical', 2: 'four-screen', 3: 'single-screen'}


def check(path):
    raw = Path(path).read_bytes()
    print(f'file      {Path(path).name}')
    print(f'size      {len(raw)} bytes')
    if len(raw) < 16 or raw[:4] != b'NES\x1a':
        print('header    MISSING "NES\\x1a" magic')
        return False
    d = raw
    mapper = (d[6] >> 4) | (d[7] & 0xf0)
    print(f'header    PRG {d[4]}x16K  CHR {d[5]}x8K  mapper {mapper}  '
          f'mirroring {MIRROR.get(d[6] & 1, "?")}')
    flags = []
    if d[6] & 0x02:
        flags.append('battery')
    if d[6] & 0x04:
        flags.append('trainer')
    if d[6] & 0x08:
        flags.append('four-screen')
    if d[7] & 0x0c == 0x08:
        flags.append('NES2.0')
    if d[9] & 1:
        flags.append('PAL')
    if flags:
        print(f'flags     {", ".join(flags)}')

    try:
        data = embed_roms.normalize(raw)
        embed_roms.validate(data)
    except ValueError as exc:
        print(f'VERDICT   rejected: {exc}')
        return False

    prg = data[4] * 16384
    vectors = data[16 + prg - 6:16 + prg]
    nmi, reset, irq = (vectors[0] | vectors[1] << 8, vectors[2] | vectors[3] << 8,
                       vectors[4] | vectors[5] << 8)
    print(f'vectors   NMI ${nmi:04X}  RESET ${reset:04X}  IRQ ${irq:04X}')

    if reset < 0x8000:
        print(f'VERDICT   NOT BOOTABLE: RESET ${reset:04X} is outside $8000-$FFFF.')
        if 0x6000 <= reset <= 0x7FFF:
            print('          $6000-$7FFF is the disk-system RAM window, so this looks like')
            print('          raw FDS data with an iNES header glued on, not a cartridge.')
        return False

    handler = data[16 + prg - (0x10000 - reset)]
    print(f'entry     ${reset:04X} starts {handler:02X} '
          f'{"(SEI/CLD style init)" if handler in (0x78, 0xD8) else ""}')
    print('VERDICT   header and vectors look bootable; run Tests/test_nes_games.py '
          'for a 90-frame smoke test')
    return True


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print(__doc__)
        raise SystemExit(2)
    ok = True
    for arg in sys.argv[1:]:
        ok = check(arg) and ok
        print()
    raise SystemExit(0 if ok else 1)
