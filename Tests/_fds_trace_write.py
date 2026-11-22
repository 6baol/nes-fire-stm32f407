"""Trace who writes to cpu_data[0] (opz) during Nes_LoadFds."""
from pathlib import Path
import struct, sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

root = Path(__file__).resolve().parents[1]
u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
for a, n in [(0x08000000, 0x100000), (0x20000000, 0x20000),
             (0x10000000, 0x10000), (0x6c000000, 0x100000), (0xe0000000, 0x100000)]:
    u.mem_map(a, n)
u.mem_write(0xe000ed88, struct.pack('<I', 0x00f00000))
with (root / 'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    elf = ELFFile(f)
    for s in elf.iter_sections():
        if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS' and s['sh_size']:
            u.mem_write(s['sh_addr'], s.data())
    syms = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}

cd = syms['cpu_data']
print(f'cpu_data at 0x{cd:08x}')

# Track writes to cpu_data[0..1]
def hook_write(uc, access, addr, size, value, user_data):
    if addr >= cd and addr < cd + 8:
        pc = uc.reg_read(UC_ARM_REG_PC)
        print(f'  WRITE cpu_data[{addr-cd}] = 0x{value:08x} (size={size}) at PC=0x{pc:08x}')

u.hook_add(UC_HOOK_MEM_WRITE, hook_write)

stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')

image, bios_at = 0x6c080000, 0x6c090000
prg = bytearray(b'\xea' * 32768)
code = bytearray()
addresses = (0x6100, 0x8100, 0xa100, 0xc100)
for i, a in enumerate(addresses):
    code += bytes((0xa9, 0x31 + i, 0x8d, a & 255, a >> 8))
for i, a in enumerate(addresses):
    code += bytes((0xad, a & 255, a >> 8, 0x85, 0x10 + i))
code += bytes.fromhex('a9 55 8d 10 e0 20 00 80 4c 00 c0')
prg[:len(code)] = code
prg[0x2000:0x2003] = bytes.fromhex('e6 20 60')
prg[0x6000:0x6003] = bytes.fromhex('4c 00 c0')
prg[0x7ffa:0x8000] = struct.pack('<HHH', 0x6000, 0x6000, 0x6000)
rom = b'NES\x1a\x02\x00' + bytes(10) + prg
bios = bytearray(b'\xea' * 8192)
bios[0:1] = b'\x40'
bios[0x100:0x103] = bytes.fromhex('4c 00 e1')
bios[-6:] = struct.pack('<HHH', 0xe000, 0xe100, 0xe000)
u.mem_write(image, bytes(rom))
u.mem_write(bios_at, bytes(bios))

def call(name, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for i, v in enumerate(args):
        u.reg_write(i, v)
    u.emu_start(syms[name] | 1, stop, count=30000000)

print('=== Calling Nes_LoadFds ===')
call('Nes_LoadFds', image, len(rom), bios_at, 8192)
print(f'=== Done. cpu_data[0] = 0x{struct.unpack("<I", u.mem_read(cd, 4))[0]:08x}')
