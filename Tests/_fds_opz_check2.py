"""Find where cpu6502_init crashes."""
from pathlib import Path
import struct, sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_MEM_READ_UNMAPPED, UC_HOOK_MEM_WRITE_UNMAPPED
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

def hook_unmapped(uc, access, addr, size, value, user):
    pc = uc.reg_read(UC_ARM_REG_PC)
    print(f'UNMAPPED! access={access} addr=0x{addr:08x} size={size}')
    print(f'  PC=0x{pc:08x} LR=0x{uc.reg_read(UC_ARM_REG_LR):08x}')
    sys.exit(1)

u.hook_add(UC_HOOK_MEM_READ_UNMAPPED | UC_HOOK_MEM_WRITE_UNMAPPED, hook_unmapped)

# 现在模拟 FDS 场景：设置 romfile 指向 FDS 镜像
# Nes_LoadFds 会设置 romfile = image (0x6c080000)
image = 0x6c080000
romfile_addr = syms.get('romfile', 0)
print(f'romfile symbol = 0x{romfile_addr:08x}')
if romfile_addr:
    u.mem_write(romfile_addr, struct.pack('<I', image))
    val = struct.unpack('<I', u.mem_read(romfile_addr, 4))[0]
    print(f'romfile = 0x{val:08x}')

stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')
u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
u.reg_write(UC_ARM_REG_LR, stop | 1)

print('Calling cpu6502_init with romfile set...')
try:
    u.emu_start(syms['cpu6502_init'] | 1, stop, count=30000000)
    print(f'After cpu6502_init: PC=0x{u.reg_read(UC_ARM_REG_PC):08x}')
except Exception as e:
    print(f'Error: {e}')
