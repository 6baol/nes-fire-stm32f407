"""Quick check: does cpu6502_init set opz?"""
from pathlib import Path
import struct, sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS
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

def r32(a): return struct.unpack('<I', u.mem_read(a, 4))[0]

# Before any init
print(f'Before init: opz = 0x{r32(cd):08x}')

stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')
u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
u.reg_write(UC_ARM_REG_LR, stop | 1)

print('Calling cpu6502_init...')
try:
    u.emu_start(syms['cpu6502_init'] | 1, stop, count=30000000)
except Exception as e:
    print(f'cpu6502_init crashed: {e}')

print(f'After cpu6502_init: opz = 0x{r32(cd):08x}')
op_table = syms.get('op_table', 0)
print(f'op_table symbol = 0x{op_table:08x}')
