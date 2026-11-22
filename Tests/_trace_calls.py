"""Precise debug: trace from cpu6502_init call to crash."""
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_WRITE_UNMAPPED, UC_HOOK_CODE, UC_HOOK_INSN
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

# Track every call/bl from Nes_Load onwards
call_depth = [0]
def hook_trace(uc, addr, size, data):
    depth = call_depth[0]
    sl = uc.reg_read(UC_ARM_REG_R10)
    pc = addr
    
    # Check if this is a BL/BX (branch with link)
    # For Thumb, BL has bits [31:25] = 11110
    try:
        code = uc.mem_read(addr & ~1, 4)
        is_bl = (code[3] & 0xF8) == 0xF0  # BL instruction high byte
    except:
        is_bl = False
    
    if is_bl and addr >= syms.get('cpu6502_init', 0) - 0x500:
        r0 = uc.reg_read(UC_ARM_REG_R0)
        target = r0  # Best guess
        # Decode BL properly
        imm11 = code[1] & 0x7FF
        imm10 = code[2]
        sign = imm11 & 0x400
        imm = ((imm11 & 0x3FF) << 11) | imm10
        if sign: imm |= 0xFFFFF000
        imm <<= 1
        target = (addr & ~1) + imm + 4
        # Find symbol
        for sname, saddr in syms.items():
            if saddr == target or saddr == target | 1:
                print(f'{"  " * depth}BL 0x{target:08X} ({sname}) sl=0x{sl:08X}')
                break
        else:
            print(f'{"  " * depth}BL 0x{target:08X} sl=0x{sl:08X} r0=0x{r0:08X}')
        call_depth[0] += 1
        if depth > 10:
            u.reg_write(UC_ARM_REG_PC, STOP)

def hook_ret(uc, addr, size, data):
    call_depth[0] = max(0, call_depth[0] - 1)

def hook_crash(uc, access, addr, size, value, data):
    pc = uc.reg_read(UC_ARM_REG_PC)
    sl = uc.reg_read(UC_ARM_REG_R10)
    print(f'CRASH: write 0x{value:X} to 0x{addr:08X} size={size}')
    print(f'  PC=0x{pc:08X} sl=0x{sl:08X}')
    # Dump cpuregs area
    try:
        mem = u.mem_read(sl, 0x100)
        for i in range(0, 0x100, 16):
            print(f'  [sl+0x{i:02X}] = {" ".join(f"{b:02X}" for b in mem[i:i+16])}')
    except:
        pass
    return False

u.hook_add(UC_HOOK_CODE, hook_trace, begin=0x0800C000, end=0x08019000)
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

print('=== Tracing Nes_Load -> crash ===')
print(f'Nes_Load=0x{syms["Nes_Load"]:08X} cpu6502_init=0x{syms["cpu6502_init"]:08X}')
try:
    u.emu_start(syms['Nes_Load'] | 1, STOP, count=30000000)
except Exception as e:
    print(f'Stopped: {e}')
