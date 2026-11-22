from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

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

stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')

def call(name, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        u.reg_write(reg, value)
    u.emu_start(syms[name] | 1, stop, count=30000000)
    return u.reg_read(UC_ARM_REG_R0)

def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

p = syms['NesPort_Input'] & ~1
u.hook_add(UC_HOOK_CODE, skip, begin=p, end=p)

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

cd = syms['cpu_data']
ret = call('Nes_LoadFds', image, len(rom), bios_at, 8192)
print(f'Nes_LoadFds returned {ret}')

# Dump cpu_data 内存布局
print(f'\ncpu_data = 0x{cd:08x}')
print()
print('=== cpu_data dump (0x80 bytes) ===')
for i in range(0, 0x88, 4):
    v = struct.unpack('<I', u.mem_read(cd + i, 4))[0]
    label = ''
    if i == 0x00: label = 'opz'
    elif 0x04 <= i <= 0x23: label = f'readmem_tbl[{(i-4)//4}]'
    elif 0x24 <= i <= 0x43: label = f'writemem_tbl[{(i-0x24)//4}]'
    elif 0x44 <= i <= 0x63: label = f'memmap_tbl[{(i-0x44)//4}]'
    elif 0x64 <= i <= 0x7b: label = f'cpuregs[{(i-0x64)//4}]'
    elif i == 0x7c: label = 'pc_lo'
    elif i == 0x80: label = 'pc_hi'
    elif i == 0x84: label = 'lastbank'
    elif i == 0x88: label = 'nexttimeout'
    # 检查值是否看起来像指针（在 0x08000000 或 0x20000000 或 0x6c000000 范围）
    pointer_hint = ''
    if v >= 0x08000000 and v <= 0x08100000: pointer_hint = ' ← CODE'
    elif v >= 0x20000000 and v <= 0x20020000: pointer_hint = ' ← SRAM'
    elif v >= 0x6c000000 and v <= 0x6c100000: pointer_hint = ' ← ROM/PRG'
    elif v == 0: pointer_hint = ' (NULL)'
    print(f'  [0x{i:02x}] = 0x{v:08x}  {label}{pointer_hint}')

# 找 fds_prgram 全局变量
print('\n=== Searching for prgram/fds symbols ===')
for s in elf.get_section_by_name('.symtab').iter_symbols():
    if 'prgram' in s.name.lower() or 'prg' in s.name.lower() or 'fds' in s.name.lower():
        sv = s['st_value']
        print(f'  sym: {s.name:20s} = 0x{sv:08x}')
