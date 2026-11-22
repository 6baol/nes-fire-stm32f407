"""Trace where the FDS boot goes: log every illegal opcode handed to
debug_6502(pc, op) and the first N distinct 6502 PCs.

    python Tests/trace_fds.py [frames]
"""
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
                               UC_ARM_REG_LR, UC_ARM_REG_R9, UC_ARM_REG_R10)

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

cpu_data = addr('cpu_data')


def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


faults = []


def on_fault(uc, a, size, data):
    pc = uc.reg_read(UC_ARM_REG_R0)
    op = uc.reg_read(UC_ARM_REG_R1)
    if len(faults) < 40:
        faults.append((pc & 0xffff, op & 0xff))
    skip(uc, a, size, data)


for name in ('NesPort_Input', 'NesPort_Line'):
    u.hook_add(UC_HOOK_CODE, skip, begin=addr(name) & ~1, end=addr(name) & ~1)
u.hook_add(UC_HOOK_CODE, on_fault, begin=addr('debug_6502') & ~1, end=addr('debug_6502') & ~1)


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
u.mem_write(0x6c080000, prg)
u.mem_write(0x6c090000, bios)
print('rc', call('Nes_LoadFds', 0x6c080000, len(prg), 0x6c090000, len(bios)))

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 3
for i in range(frames):
    call('Nes_Frame', 1)
    print(f'frame {i}: faults={struct.unpack("<I", u.mem_read(addr("nes_faults"), 4))[0]} '
          f'pc=${struct.unpack("<H", u.mem_read(cpu_data + 4 * 0 + 0, 2))[0]:04X}')

print('first illegal opcodes (pc, op):')
for pc, op in faults:
    print(f'  ${pc:04X}  op=${op:02X}')
