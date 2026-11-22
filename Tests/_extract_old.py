"""Extract cpu_code/cpu_run/rwram_code from OLD AXF and generate a patched 6502.s."""
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS
import re

ROOT = Path(__file__).resolve().parents[1]
OLD_AXF = ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf'
CURRENT_S = ROOT / 'User/nes/6502.s'

# Step 1: Find sections in OLD AXF
print('=== Step 1: Extract sections from OLD AXF ===')
sections_data = {}
with open(OLD_AXF, 'rb') as f:
    elf = ELFFile(f)
    for sec in elf.iter_sections():
        flags = sec['sh_flags']
        if flags & 2 and sec['sh_type'] != 'SHT_NOBITS' and sec['sh_size']:
            name = sec.name
            if 'ER_IROM1' in name or 'cpu_' in name or 'rwram' in name or 'cpu' in name.lower():
                addr = sec['sh_addr']
                size = sec['sh_size']
                data = bytes(sec.data())
                print(f'  Section {name}: addr=0x{addr:08X} size=0x{size:X}')
                sections_data[name] = (addr, data)

# Also get symbol table
symbols = {}
with open(OLD_AXF, 'rb') as f:
    elf = ELFFile(f)
    symtab = elf.get_section_by_name('.symtab')
    if symtab:
        for s in symtab.iter_symbols():
            if s.name and s['st_info']['type'] in ('STT_FUNC', 'STT_OBJECT', 'STT_NOTYPE'):
                symbols[s.name] = s['st_value']

# Step 2: Find boundaries
# From OLD AXF disasm we know:
# cpu_code starts at flash base, ends around 0x08017700 (before run6502 / cpu_run)
# cpu_run starts around 0x08017700, contains Vec6502, NMI6502, CPU_reset, run6502
# rwram_code starts at 0x08018218

# Let's find exact boundaries from symbols
cpu6502_init = symbols.get('cpu6502_init', 0)
cpu_reset = symbols.get('CPU_reset', 0)
run6502 = symbols.get('run6502', 0)

# Find section that contains CPU_reset (it should be in cpu_run)
cpu_run_sec_name = None
cpu_run_addr = cpu_reset & ~1
for name, (addr, data) in sections_data.items():
    if addr <= cpu_reset < addr + len(data):
        cpu_run_sec_name = name
        print(f'  CPU_reset (0x{cpu_reset:08X}) is in section {name}')

# Find the section that contains opcode handlers (cpu_code)
# It should be earlier
for name, (addr, data) in sections_data.items():
    if addr < cpu_reset and len(data) > 0x1000:
        cpu_code_sec_name = name
        print(f'  Potential cpu_code section: {name} at 0x{addr:08X}')
        break

print(f'\nSymbol summary:')
for name in ['CPU_reset', 'cpu_reset_now', 'cpu_start_fds', 'prgram_R', 'prgram_W',
             'run6502', 'op_table', 'Vec6502', 'VecCont', 'NMI6502']:
    if name in symbols:
        print(f'  {name}: 0x{symbols[name]:08X}')
