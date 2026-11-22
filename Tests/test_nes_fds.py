"""Boot the 32 KiB FDS PRG-RAM snapshot with the FDS BIOS and dump a frame.

    python Tests/test_nes_fds.py 'Roms/Super Mario Bros. 2 (J) (FDS Conversion).nes'
"""
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
                               UC_ARM_REG_LR)

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root / 'tools'))

u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
for a, n in [(0x08000000, 0x100000), (0x20000000, 0x20000), (0x10000000, 0x10000),
             (0x6c000000, 0x100000), (0xe0000000, 0x100000)]:
    u.mem_map(a, n)
u.mem_write(0xe000ed88, struct.pack('<I', 0x00f00000))
with (root / 'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    e = ELFFile(f)
    for s in e.iter_sections():
        if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS' and s['sh_size']:
            u.mem_write(s['sh_addr'], s.data())
    symbols = {s.name: s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name}
addr = lambda n: symbols[n]
stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')


def r32(a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


frame = bytearray(256 * 240)


def line(uc, a, size, data):
    y = uc.reg_read(UC_ARM_REG_R0)
    p = uc.reg_read(UC_ARM_REG_R1)
    frame[y * 256:(y + 1) * 256] = uc.mem_read(p, 256)
    skip(uc, a, size, data)


u.hook_add(UC_HOOK_CODE, skip, begin=addr('NesPort_Input') & ~1, end=addr('NesPort_Input') & ~1)
u.hook_add(UC_HOOK_CODE, line, begin=addr('NesPort_Line') & ~1, end=addr('NesPort_Line') & ~1)


def call(n, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, v in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
        u.reg_write(reg, v)
    u.emu_start(addr(n) | 1, stop, count=400000000)
    if u.reg_read(UC_ARM_REG_PC) != stop:
        raise RuntimeError('instruction budget exhausted in ' + n)
    return u.reg_read(UC_ARM_REG_R0)


rom_path = Path(sys.argv[1] if len(sys.argv) > 1
                else 'Roms/Super Mario Bros. 2 (J) (FDS Conversion).nes')
raw = (root / rom_path).read_bytes()
bios = (root / 'Roms/fds_bios.bin').read_bytes()
print(f'image {len(raw)} bytes, bios {len(bios)} bytes')

image_at, bios_at = 0x6c080000, 0x6c090000
u.mem_write(image_at, raw)
u.mem_write(bios_at, bios)

rc = call('Nes_LoadFds', image_at, len(raw), bios_at, len(bios))
print('Nes_LoadFds rc =', rc)
if rc:
    raise SystemExit(1)

frames = int(sys.argv[2]) if len(sys.argv) > 2 else 120
for _ in range(frames):
    call('Nes_Frame', 1)

faults = r32(addr('nes_faults'))
colors = len(set(frame))
print(f'frames={frames} faults={faults} colours={colors}')
out = root / 'Tests/nes_output/fds_smb2.ppm'
out.parent.mkdir(exist_ok=True)
out.write_bytes(b'P5\n256 240\n255\n' + bytes(frame))
print('wrote', out)
if faults or colors < 3:
    raise SystemExit('FAIL: snapshot did not produce a running game; this is not an FDS drive test')
print('PASS: snapshot smoke test only; no disk read/write or board validation')
