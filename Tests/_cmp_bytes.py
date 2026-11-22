"""Find exact diff between OLD AXF asm and what Reference 原版 assembles to."""
import struct, hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_MCLASS

ROOT = Path(__file__).resolve().parents[1]
OLD_AXF = ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf'
NEW_AXF = ROOT / 'Project/Output/Fire_F407ZG.axf'

def get_code(axf_path, start, size):
    with open(axf_path, 'rb') as f:
        elf = ELFFile(f)
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                base = sec['sh_addr']
                if base <= start < base + len(sec.data()):
                    off = start - base
                    return bytes(sec.data())[off:off+size]
    return None

# Compare code from 0x08017700 to 0x08017900 (cpu_code -> cpu_run transition)
old_code = get_code(OLD_AXF, 0x08017700, 0x200)
new_code = get_code(NEW_AXF, 0x08017700, 0x200)

if old_code != new_code:
    print('Byte differences from 0x08017700:')
    for i in range(len(old_code)):
        if i >= len(new_code) or old_code[i] != new_code[i]:
            print(f'  +0x{i:02X}: OLD=0x{old_code[i]:02X} NEW={new_code[i] if i < len(new_code) else "N/A"}')
else:
    print('Codes are identical!')
