"""Trace cpu6502_init -> CPU_reset call chain for both AXFs."""
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]

def disasm_block(data, base_addr, label=''):
    """Simple Thumb disassembler using Unicorn's capstone if available."""
    try:
        from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB
        md = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        print(f'\n  {label} (0x{base_addr:08X}):')
        for i in md.disasm(data, base_addr):
            print(f'    0x{i.address:08X}: {i.mnemonic:8} {i.op_str}')
    except ImportError:
        print(f'  {label}: no capstone')

def get_section_bytes(path):
    result = {}
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        symbols = {s.name: s['st_value'] for s in symtab.iter_symbols() if s.name}
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                result[sec['sh_addr']] = bytes(sec.data())
    return result, symbols

def read_code(sections, addr, size):
    for base, data in sections.items():
        if base <= addr < base + len(data):
            off = addr - base
            return data[off:off+size]
    return b''

for label, path in [('OLD GOOD', ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf'),
                     ('NEW BROKEN', ROOT / 'Project/Output/Fire_F407ZG.axf')]:
    sections, symbols = get_section_bytes(path)
    
    cpu6502_init = symbols.get('cpu6502_init', 0)
    CPU_reset = symbols.get('CPU_reset', 0)
    cpu_reset_now = symbols.get('cpu_reset_now', 0)
    cpu_data = symbols.get('cpu_data', 0)
    
    print(f'\n{"="*60}')
    print(f'{label}:')
    print(f'  cpu6502_init: 0x{cpu6502_init:08X}')
    print(f'  CPU_reset:    0x{CPU_reset:08X}')
    print(f'  cpu_reset_now:0x{cpu_reset_now:08X}')
    print(f'  cpu_data:     0x{cpu_data:08X}')
    
    # Disassemble cpu6502_init (C function, sets up r10=globalptr)
    if cpu6502_init:
        code = read_code(sections, cpu6502_init & ~1, 0x120)
        disasm_block(code, cpu6502_init & ~1, 'cpu6502_init')
    
    # Disassemble CPU_reset (ASM)
    if CPU_reset:
        code = read_code(sections, CPU_reset & ~1, 0x80)
        disasm_block(code, CPU_reset & ~1, 'CPU_reset')
