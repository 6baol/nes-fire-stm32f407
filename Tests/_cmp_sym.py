from pathlib import Path
from elftools.elf.elffile import ELFFile

ROOT = Path(__file__).resolve().parents[1]

def show_symbols(path, label):
    print(f'\n=== {label} ===')
    with open(path, 'rb') as f:
        elf = ELFFile(f)
        symtab = elf.get_section_by_name('.symtab')
        targets = {'NES_RAM', 'NES_SRAM', 'spr_ram', 'cpu_data', 'cpu_reset_now',
                   'CPU_reset', 'cpu_start_fds', 'prgram_R', 'prgram_W',
                   'cpuregs', 'm6502_s', 'lastbank'}
        if symtab:
            for s in symtab.iter_symbols():
                if s.name in targets:
                    print(f'  {s.name}: 0x{s["st_value"]:08X} size={s["st_size"]}')
        print('  Sections:')
        for sec in elf.iter_sections():
            addr = sec['sh_addr']
            size = sec['sh_size']
            nobits = sec['sh_type'] == 'SHT_NOBITS'
            flags = sec['sh_flags']
            alloc = bool(flags & 2)
            if size and (nobits or alloc):
                print(f'    {sec.name}: addr=0x{addr:08X} size=0x{size:X} nobits={nobits}')

show_symbols(ROOT / 'Project/Output/Fire_F407ZG.axf', 'OUR BUILD')
show_symbols(ROOT / 'Release/NesFire_v0.19.1-controls-preview.axf', 'OLD BUILD')
