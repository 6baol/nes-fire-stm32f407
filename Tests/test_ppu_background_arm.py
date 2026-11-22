"""Render deterministic MMC3/MMC5 rows on the compiled ARM background renderer."""
import argparse
import hashlib
from pathlib import Path
import random
import struct

from test_mmc3_arm import NesArm, ROOT, make_mmc3_rom
from test_mmc5_arm import rom as make_mmc5_rom, wr

# Captured with the v0.42 Arm 6.7 build before optimizing render_bg.
REFERENCE_DIGEST = {
    4: 'da15048e42a04ab87499fcfca30a4f4994ec2b893ce1dad05dc05e4684605ae5',
    5: 'e6ec869d5ea1ec2a72f4af5b164057da841975790a0723028f6e7d029735f404',
}


def row_digest(axf, mapper):
    arm = NesArm(axf)
    rng = random.Random(12345 + mapper)
    rom = bytearray((make_mmc5_rom if mapper == 5 else make_mmc3_rom)())
    chr_start = 16 + rom[4] * 16384
    rom[chr_start:] = rng.randbytes(len(rom) - chr_start)
    address = 0x6C020000 if mapper == 5 else 0x6C080000
    arm.u.mem_write(address, bytes(rom))
    assert arm.call('Nes_Load', address, len(rom)) == 0

    # Fixed ARM ppu_data layout from nes_ppu.h, offsets include native padding.
    ppu = arm.r32(arm.addr('ppu'))
    solid = ppu + 4244
    arm.u.mem_write(ppu + 62, rng.randbytes(4096))  # four nametables and their attributes
    exram = rng.randbytes(1024)
    if mapper == 5:
        arm.u.mem_write(arm.addr('m5_exram'), exram)
        wr(arm, 0x5104, 1)  # extended attribute mode

    result = hashlib.sha256()
    for case in range(256):
        fine_x = case % 8
        loopy_v = rng.randrange(32) | rng.randrange(30) << 5 | rng.randrange(4) << 10 | rng.randrange(8) << 12
        buf = 0x6C0F5000 + case % 4
        guard = rng.randbytes(288)
        if case % 15 == 0:
            palette = bytes(rng.randrange(64) for _ in range(16)) if case else bytes(16)
        arm.u.mem_write(ppu + 4, struct.pack('<I', case % 240))  # current_frame_line
        arm.u.mem_write(ppu + 8, struct.pack('<H', 0x1000 if case & 1 else 0))
        arm.u.mem_write(ppu + 14, struct.pack('<H', loopy_v))
        arm.u.mem_write(ppu + 18, bytes([fine_x]))
        arm.u.mem_write(ppu + 30, palette)
        if mapper == 5:
            wr(arm, 0x5200, (0xC0 if case & 16 else 0x80) | case % 32)
            wr(arm, 0x5201, case % 240)  # split screen overrides palette and tile row
        arm.u.mem_write(buf - 8, guard)
        arm.u.mem_write(solid, guard[:272])
        arm.call('render_bg', buf)
        pixels = bytes(arm.u.mem_read(buf - 8, 288))
        coverage = bytes(arm.u.mem_read(solid, 272))
        first = 8 - fine_x
        end = first + 33 * 8
        assert pixels[:8 + first] == guard[:8 + first] and pixels[8 + end:] == guard[8 + end:]
        assert coverage[:first] == guard[:first] and coverage[end:] == guard[end:272]
        assert set(coverage[first:end]) <= {0, 1}
        result.update(pixels)
        result.update(coverage)
    return result.hexdigest()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--axf', type=Path, default=ROOT / 'Project/Output/Fire_F407ZG.axf')
    parser.add_argument('--reference', type=Path, help='compare a second compiled ARM renderer')
    args = parser.parse_args()
    for board in (4, 5):
        digest = row_digest(args.axf, board)
        assert digest == REFERENCE_DIGEST[board], ('v0.42 output differs', board, digest)
        if args.reference:
            assert digest == row_digest(args.reference, board), ('reference differs', board, digest)
        print(f'PASS mapper {board}: 256 scanlines, palette indices and solidity SHA-256 {digest}')
