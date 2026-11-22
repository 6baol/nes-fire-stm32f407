"""Dump the 6502 register file and memory map right after Nes_LoadFds."""
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
                               UC_ARM_REG_LR)

root = Path(__file__).resolve().parents[1]
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


def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


def call(n, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, v in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
        u.reg_write(reg, v)
    u.emu_start(addr(n) | 1, stop, count=400000000)
    return u.reg_read(UC_ARM_REG_R0)


rom = (root / 'Roms/Super Mario Bros. 2 (J) (FDS Conversion).nes').read_bytes()
prg = rom[16:16 + rom[4] * 16384]
bios = (root / 'Roms/fds_bios.bin').read_bytes()
u.mem_write(0x6c080000, rom)
u.mem_write(0x6c090000, bios)
print('rc', call('Nes_LoadFds', 0x6c080000, len(rom), 0x6c090000, len(bios)))
cd = addr('cpu_data')
names = ['nz', 'rmem', 'a', 'x', 'y', 'cycles', 'pc']
for i, nm in enumerate(names):
    print('  cpuregs[%s] = 0x%08x' % (nm, struct.unpack('<I', u.mem_read(cd + 0x64 + 4 * i, 4))[0]))
print('  S(m6502_s) = 0x%08x' % struct.unpack('<I', u.mem_read(cd + 0x80, 4))[0])
print('  lastbank   = 0x%08x' % struct.unpack('<I', u.mem_read(cd + 0x84, 4))[0])

pr = 0x20002820
print('prgram[0x7FFA:0x8000] =', u.mem_read(pr+0x7FFA,6).hex())
print('prgram[0x0000:0x0010] =', u.mem_read(pr,16).hex())
print('bios $FFFA..$FFFF =, bios[0x1ffa:].hex())
print('map tbl:')
for i in range(8):
    print('  map[%d] = 0x%08x' % (i, struct.unpack('<I', u.mem_read(cd + 68 + 4 * i, 4))[0]))
print('read tbl:')
for i in range(8):
    print('  read[%d] = 0x%08x' % (i, struct.unpack('<I', u.mem_read(cd + 4 + 4 * i, 4))[0]))
