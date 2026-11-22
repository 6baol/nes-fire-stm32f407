"""Disasm Vec6502 in context for both builds."""
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS

ROOT = Path(__file__).resolve().parents[1]

def disasm(path, start, size, label):
    sections = {}
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        symbols = {s.name: s['st_value'] for s in symtab.iter_symbols() if s.name}
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                sections[sec['sh_addr']] = bytes(sec.data())
    
    for b, data in sections.items():
        if b <= start < b + len(data):
            off = start - b
            code = data[off:off+size]
            break
    
    md = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_MCLASS)
    print(f'\n{label} (0x{start:08X}):')
    for i in md.disasm(code, start):
        sym = ''
        for sname, saddr in symbols.items():
            if saddr == i.address:
                sym = f' <{sname}>'
                break
        print(f'  0x{i.address:08X}: {i.mnemonic:10} {i.op_str}{sym}')

# OLD: disasm 0x08017700 - 0x08017900
disasm(ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf', 0x08017700, 0x200, 'OLD @0x08017700')
disasm(ROOT / 'Project/Output/Fire_F407ZG.axf', 0x08017700, 0x200, 'NEW @0x08017700')
