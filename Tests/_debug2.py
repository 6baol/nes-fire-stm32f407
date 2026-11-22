"""Deep debug: watch every register change around crash."""
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = 0x6C080000
STOP = 0x080FF000

u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
for base, size in [(0x08000000, 0x100000), (0x20000000, 0x20000),
                   (0x10000000, 0x10000), (0x6C000000, 0x100000),
                   (0xE0000000, 0x100000)]:
    u.mem_map(base, size)
u.mem_write(0xE000ED88, struct.pack('<I', 0x00F00000))

with open(ROOT / 'Project/Output/Fire_F407ZG.axf', 'rb') as f:
    elf = ELFFile(f)
    for sec in elf.iter_sections():
        if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                and sec['sh_size']):
            u.mem_write(sec['sh_addr'], sec.data())
    syms = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}

# Watch from CPU_reset start through Vec6502
# CPU_reset starts at 0x0801787E, Vec6502 code goes from 0x0801780C
# Let's catch everything from 0x0801787E to 0x08017900

regs = [UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3,
        UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_R6, UC_ARM_REG_R7,
        UC_ARM_REG_R8, UC_ARM_REG_R9, UC_ARM_REG_R10, UC_ARM_REG_R11,
        UC_ARM_REG_IP, UC_ARM_REG_SP, UC_ARM_REG_LR]

def dump(uc, addr, size, data):
    vals = {r: uc.reg_read(r) for r in regs}
    line = f'0x{addr:08X}: '
    for r, v in vals.items():
        line += f'r{r-UC_ARM_REG_R0}={v:08X} '
    # Also check memory at [sl+0x80]
    sl = vals[UC_ARM_REG_R10]
    try:
        m6502_s = struct.unpack('<I', uc.mem_read(sl + 0x80, 4))[0] if sl else 0
        line += f' [sl+0x80]=0x{m6502_s:08X}'
    except:
        line += f' [sl+0x80]=ERR'
    print(line)
    if addr == 0x0801781C:  # crash instruction
        uc.reg_write(UC_ARM_REG_PC, STOP)  # stop

u.hook_add(UC_HOOK_CODE, dump, begin=0x0801787E, end=0x0801781C + 2)

import sys
prg = bytearray([0xEA]) * (8 * 0x2000)
prg[-0x2000:-0x2000 + 13] = bytes.fromhex('a9 00 8d 00 80 a9 00 8d 01 80 4c 00 80')
prg[0:10] = bytes.fromhex('a9 06 8d 00 80 a9 02 8d 01 80')
prg[2 * 0x2000 + 0x0A:2 * 0x2000 + 0x11] = bytes.fromhex('a9 42 85 10 4c 0e 80')
prg[-6:] = struct.pack('<HHH', 0xE000, 0xE000, 0xE000)
chr_data = bytes(16 * 0x400)
header = b'NES\x1a' + bytes([4, 2, 0x40, 0]) + bytes(8)
rom = bytes(header + prg + chr_data)

u.mem_write(SCRATCH, rom)
u.reg_write(UC_ARM_REG_SP, 0x2001FFF0)
u.reg_write(UC_ARM_REG_LR, STOP | 1)
u.reg_write(UC_ARM_REG_R0, SCRATCH)
u.reg_write(UC_ARM_REG_R1, len(rom))

Nes_Load = syms['Nes_Load']
print(f'=== Tracing CPU_reset -> Vec6502 ===')
try:
    u.emu_start(Nes_Load | 1, STOP, count=30000000)
except Exception as e:
    print(f'Stopped: {e}')
