"""Compare two AXFs section by section and CPU_reset disasm."""
import subprocess, re, struct
from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]
OLD = ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf'
NEW = ROOT / 'Project/Output/Fire_F407ZG.axf'

def get_section_bytes(path):
    result = {}
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                result[sec['sh_addr']] = bytes(sec.data())
    return result

old_sections = get_section_bytes(OLD)
new_sections = get_section_bytes(NEW)

# Find common address ranges and compare
print('Code section comparison (first 0x25000 bytes of Flash):')
for addr in sorted(set(list(old_sections.keys()) + list(new_sections.keys()))):
    old_data = old_sections.get(addr, b'')
    new_data = new_sections.get(addr, b'')
    maxlen = max(len(old_data), len(new_data))
    # Compare first 0x25DBC bytes (old flash code size)
    compare_len = min(maxlen, 0x25DBC - addr)
    if compare_len > 0:
        diffs = [(i, old_data[i], new_data[i]) 
                 for i in range(compare_len) 
                 if i < len(old_data) and i < len(new_data) and old_data[i] != new_data[i]]
        if diffs:
            print(f'\nSection at 0x{addr:08X}: {len(diffs)} byte differences (first 10):')
            for i, o, n in diffs[:10]:
                print(f'  +0x{i:04X}: old=0x{o:02X} new=0x{n:02X}')
        # Also check if one has data where other doesn't
        elif len(old_data) != len(new_data) and len(old_data) < 0x25DBC and addr < 0x08026000:
            print(f'\nSection at 0x{addr:08X}: size differs old={len(old_data)} new={len(new_data)}')
