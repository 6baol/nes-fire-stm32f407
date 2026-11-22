"""Check BSS initialization in Unicorn for both AXFs."""
import struct
from pathlib import Path
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS

ROOT = Path(__file__).resolve().parents[1]

def check_axf(path, label):
    print(f'\n=== {label} ===')
    u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
    for base, size in [(0x08000000, 0x100000), (0x20000000, 0x20000),
                       (0x10000000, 0x10000), (0x6C000000, 0x100000),
                       (0xE0000000, 0x100000)]:
        u.mem_map(base, size)
    u.mem_write(0xE000ED88, struct.pack('<I', 0x00F00000))

    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        symbols = {s.name: s['st_value'] for s in symtab.iter_symbols() if s.name}
        for sec in elf.iter_sections():
            if (sec['sh_flags'] & 2 and sec['sh_type'] != 'SHT_NOBITS'
                    and sec['sh_size']):
                u.mem_write(sec['sh_addr'], sec.data())

    # Read NES_RAM pointer
    nes_ram_ptr = symbols.get('NES_RAM', 0)
    print(f'  NES_RAM symbol at 0x{nes_ram_ptr:08X}')
    ptr_val = struct.unpack('<I', u.mem_read(nes_ram_ptr, 4))[0]
    print(f'  *NES_RAM = 0x{ptr_val:08X}')
    
    # Try to read first 16 bytes of cpu_ram
    if ptr_val:
        try:
            data = u.mem_read(ptr_val, 16)
            print(f'  cpu_ram[0:16] = {data.hex()}')
            nonzero = any(b != 0 for b in data)
            print(f'  cpu_ram has nonzero bytes: {nonzero}')
        except Exception as e:
            print(f'  Error reading cpu_ram: {e}')
    
    # Also check m6502_s (offset 0x80 from cpu_data=globalptr)
    cpu_data = symbols.get('cpu_data', 0x2000006C)
    print(f'  cpu_data (globalptr) at 0x{cpu_data:08X}')
    m6502_s_off = 0x80
    m6502_s_val = struct.unpack('<I', u.mem_read(cpu_data + m6502_s_off, 4))[0]
    print(f'  m6502_s ([globalptr+0x80]) = 0x{m6502_s_val:08X}')
    
    # Check RW_IRAM1 BSS area (0x20000400)
    try:
        bss = u.mem_read(0x20000400, 32)
        print(f'  BSS area (0x20000400) first 32 bytes: {bss.hex()}')
    except Exception as e:
        print(f'  Error reading BSS: {e}')

check_axf(ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf', 'OLD GOOD')
check_axf(ROOT / 'Project/Output/Fire_F407ZG.axf', 'NEW BROKEN')
