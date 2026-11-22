"""Debug: check sl (globalptr) value at crash time for NEW build."""
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_CODE
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

def hook_step(uc, addr, size, data):
    if addr >= 0x08017808 and addr <= 0x08017820:
        sl = uc.reg_read(UC_ARM_REG_R10)
        print(f'  PC=0x{addr:08X} sl=0x{sl:08X} m6502_s=[sl+0x80]={uc.reg_read(UC_ARM_REG_R0):08X}')
        if addr == 0x08017818:  # right before crash - print [sl+0x80] directly
            val = struct.unpack('<I', uc.mem_read(sl + 0x80, 4))[0] if sl else 0
            print(f'    [sl+0x80] = 0x{val:08X}')
            print(f'    R0(m6502_pc) on entry: sb={uc.reg_read(UC_ARM_REG_R9):08X}')
            # Check cpu_data symbol
            cpu_data = syms.get('cpu_data', 0)
            print(f'    cpu_data symbol at 0x{cpu_data:08X}')
            # Dump from cpu_data + 0x64 (cpuregs)
            try:
                cpuregs = u.mem_read(sl + 0x64, 28)
                print(f'    cpuregs [sl+0x64] = {cpuregs.hex()}')
            except:
                print(f'    [sl+0x64] unreadable')
            u.reg_write(UC_ARM_REG_PC, STOP)  # stop here

u.hook_add(UC_HOOK_CODE, hook_step, begin=0x08017808, end=0x08017820)

# Simple MMC3 ROM
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
print(f'Calling Nes_Load at 0x{Nes_Load:08X}')
print(f'cpu6502_init at 0x{syms.get("cpu6502_init",0):08X}')
print(f'CPU_reset at 0x{syms.get("CPU_reset",0):08X}')

try:
    u.emu_start(Nes_Load | 1, STOP, count=30000000)
except Exception as e:
    print(f'Stopped: {e}')
    pc = u.reg_read(UC_ARM_REG_PC)
    sl = u.reg_read(UC_ARM_REG_R10)
    print(f'Final PC=0x{pc:08X} sl=0x{sl:08X}')
