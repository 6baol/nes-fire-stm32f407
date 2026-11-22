"""Trace every instruction that writes to sl (r10) to find who corrupts it."""
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE, UC_HOOK_MEM_WRITE_UNMAPPED
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

last_sl = [0x2000006C]
def watch_sl(uc, addr, size, data):
    sl = uc.reg_read(UC_ARM_REG_R10)
    if sl != last_sl[0]:
        print(f'sl changed: 0x{last_sl[0]:08X} -> 0x{sl:08X} at PC=0x{addr:08X}')
        # Try to decode the instruction
        try:
            code = uc.mem_read(addr & ~1, 4)
            # Print instruction bytes
            print(f'  instr bytes: {" ".join(f"{b:02X}" for b in code[:size])}')
        except:
            pass
        # Show function context
        for sname, saddr in sorted(syms.items(), key=lambda x: abs(x[1] - addr))[:5]:
            print(f'  near: {sname} at 0x{saddr:08X} (delta={addr - saddr:+d})')
        last_sl[0] = sl

def hook_crash(uc, access, addr, size, value, data):
    pc = uc.reg_read(UC_ARM_REG_PC)
    sl = uc.reg_read(UC_ARM_REG_R10)
    print(f'CRASH: write 0x{value:X} to 0x{addr:08X} size={size} PC=0x{pc:08X} sl=0x{sl:08X}')
    return False

# Watch from Nes_Load (0x0800C9A5) to crash area (0x08017800)
u.hook_add(UC_HOOK_CODE, watch_sl, begin=0x0800C000, end=0x08019000)
u.hook_add(UC_HOOK_MEM_WRITE_UNMAPPED, hook_crash)

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

print(f'Initial sl=0x{last_sl[0]:08X} cpu_data=0x{syms.get("cpu_data", 0):08X}')
try:
    u.emu_start(syms['Nes_Load'] | 1, STOP, count=30000000)
except Exception as e:
    print(f'Stopped: {e}')
