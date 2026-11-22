"""Check what Nes_LoadFds actually left in fds_prgram and in cpuregs."""
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
                               UC_ARM_REG_LR)

root = Path(__file__).resolve().parents[1]
u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
for a, n in [(0x08000000, 0x100000), (0x20000000, 0x20000), (0x10000000, 0x10000),
             (0x6c000000, 0x100000), (0xe0000000, 0x100000)]:
    u.mem_map(a, n)
u.mem_write(0xe000ed88, struct.pack('<I', 0x00f00000))
with (root / 'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    e = ELFFile(f)
    for s in e.iter_sections():
        if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS' and s['sh_size']:
            u.mem_write(s['sh_addr'], s.data())
    sym = {s.name: s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name}
stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')
cd = sym['cpu_data']


def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


def call(n, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, v in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
        u.reg_write(reg, v)
    u.emu_start(sym[n] | 1, stop, count=400000000)
    return u.reg_read(UC_ARM_REG_R0)



from unicorn.arm_const import UC_ARM_REG_R4
def watch(uc,a,size,data):
    r4=uc.reg_read(UC_ARM_REG_R4)
    print('  @0x%08x r4=0x%08x  [r4+0x7ffd]=0x%02x  [r4+0x7ffc]=0x%02x' % (a,r4,uc.mem_read(r4+0x7ffd,1)[0],uc.mem_read(r4+0x7ffc,1)[0]))
u.hook_add(UC_HOOK_CODE, watch, begin=0x08006bfa, end=0x08006bfa)
u.hook_add(UC_HOOK_CODE, watch, begin=0x08006c0a, end=0x08006c0a)
u.hook_add(UC_HOOK_CODE, watch, begin=0x08006c14, end=0x08006c14)
for name in ('NesPort_Input', 'NesPort_Line'):
    u.hook_add(UC_HOOK_CODE, skip, begin=sym[name] & ~1, end=sym[name] & ~1)

rom = (root / 'Roms/Super Mario Bros. 2 (J) (FDS Conversion).nes').read_bytes()
bios = (root / 'Roms/fds_bios.bin').read_bytes()
u.mem_write(0x6c080000, rom)
u.mem_write(0x6c090000, bios)
print('Nes_LoadFds rc =', call('Nes_LoadFds', 0x6c080000, len(rom), 0x6c090000, len(bios)))

pr = 0x20002820
print('fds_prgram[0x7FFA:0x8000] =', u.mem_read(pr + 0x7FFA, 6).hex())
print('fds_prgram[0:16]         =', u.mem_read(pr, 16).hex())
print('cpuregs[pc] = 0x%08x  lastbank = 0x%08x' % (
    struct.unpack('<I', u.mem_read(cd + 0x7C, 4))[0],
    struct.unpack('<I', u.mem_read(cd + 0x84, 4))[0]))

print('--- after one frame ---')
call('Nes_Frame', 1)
print('cpuregs[pc] = 0x%08x  lastbank = 0x%08x' % (
    struct.unpack('<I', u.mem_read(cd + 0x7C, 4))[0],
    struct.unpack('<I', u.mem_read(cd + 0x84, 4))[0]))
print('LowRegs[0..2] =', u.mem_read(sym['ppu'] + 0, 1).hex())
