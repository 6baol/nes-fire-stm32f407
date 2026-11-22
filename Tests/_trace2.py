"""Trace cpu6502_init -> CPU_reset with capstone, for BOTH AXFs."""
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS

ROOT = Path(__file__).resolve().parents[1]

def disasm_range(sections, base, size, label, start_addr=None):
    if start_addr is None:
        start_addr = base & ~1
    for b, data in sections.items():
        if b <= start_addr < b + len(data):
            off = start_addr - b
            code = data[off:off+size]
            break
    else:
        print(f'  {label}: no code at 0x{start_addr:08X}')
        return
    
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    print(f'\n  {label} (0x{start_addr:08X}):')
    for i in md.disasm(code, start_addr):
        marker = ''
        if i.mnemonic.startswith('bx') or i.mnemonic.startswith('bl') or i.mnemonic.startswith('b'):
            marker = ' ← branch'
        print(f'    0x{i.address:08X}: {i.mnemonic:10} {i.op_str}{marker}')
        if i.mnemonic == 'pop' and 'pc' in i.op_str:
            print('    (returns)')
            break

def load(path):
    sections = {}
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        symbols = {s.name: s['st_value'] for s in symtab.iter_symbols() if s.name}
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                sections[sec['sh_addr']] = bytes(sec.data())
    return sections, symbols

for label, path in [('OLD GOOD', ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf'),
                     ('NEW BROKEN', ROOT / 'Project/Output/Fire_F407ZG.axf')]:
    print(f'\n{"="*60}')
    print(f'{label}')
    sections, syms = load(path)
    
    disasm_range(sections, syms['cpu6502_init'], 0x150, 'cpu6502_init')
    disasm_range(sections, syms['CPU_reset'], 0x100, 'CPU_reset')
    if 'cpu_reset_now' in syms:
        disasm_range(sections, syms['cpu_reset_now'], 0x80, 'cpu_reset_now')
    if 'Vec6502' in syms:
        disasm_range(sections, syms['Vec6502'], 0x80, 'Vec6502')
