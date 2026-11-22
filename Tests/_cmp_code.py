"""Compare code bytes around CPU_reset between old and new AXFs."""
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf'
NEW = ROOT / 'Project/Output/Fire_F407ZG.axf'

def get_code_bytes(path, start, size):
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                if sec['sh_addr'] <= start < sec['sh_addr'] + sec['sh_size']:
                    offset = start - sec['sh_addr']
                    return bytes(sec.data())[offset:offset+size]
    return b''

# CPU_reset in old: 0x0801784D, new: 0x0801787F
old_base = 0x08017800
new_base = 0x08017800  # Same start address in our build

for label, base in [('OLD', old_base), ('NEW', new_base)]:
    code = get_code_bytes(OLD if label == 'OLD' else NEW, base, 0x100)
    print(f'\n=== {label} code at 0x{base:08X} (0x100 bytes) ===')
    for i in range(0, len(code), 16):
        hex_str = ' '.join(f'{b:02X}' for b in code[i:i+16])
        print(f'  0x{base+i:08X}: {hex_str}')

# Also find cpu6502_init - this is called before CPU_reset
print('\n\n=== Searching for cpu6502_init ===')
def find_symbol(path, name):
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        for s in symtab.iter_symbols():
            if s.name == name:
                return s['st_value']
    return None

for label, path in [('OLD', OLD), ('NEW', NEW)]:
    addr = find_symbol(path, 'cpu6502_init')
    if addr:
        code = get_code_bytes(path, addr & ~1, 0x60)
        print(f'\n{label} cpu6502_init at 0x{addr:08X}:')
        for i in range(0, len(code), 16):
            hex_str = ' '.join(f'{b:02X}' for b in code[i:i+16])
            print(f'  0x{(addr & ~1)+i:08X}: {hex_str}')
