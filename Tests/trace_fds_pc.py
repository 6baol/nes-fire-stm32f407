"""Log the 6502 program counter for every instruction by hooking each handler
in op_table (r9 holds m6502_pc on entry).

    python Tests/trace_fds_pc.py [frames]
"""
from collections import Counter
from pathlib import Path
import struct
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import (UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1,
                               UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_SP,
                               UC_ARM_REG_LR, UC_ARM_REG_R9)

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
    symbols = {s.name: s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name}
addr = lambda n: symbols[n]
stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')


def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


def call(n, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, v in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
        u.reg_write(reg, v)
    u.emu_start(addr(n) | 1, stop, count=400000000)
    return u.reg_read(UC_ARM_REG_R0)


rom = (root / 'Roms/Super Mario Bros. 2 (J) (FDS Conversion).nes').read_bytes()
prg = rom[16:16 + rom[4] * 16384]
bios = (root / 'Roms/fds_bios.bin').read_bytes()
u.mem_write(0x6c080000, rom)
u.mem_write(0x6c090000, bios)
print('rc', call('Nes_LoadFds', 0x6c080000, len(rom), 0x6c090000, len(bios)))

tbl = addr('op_table')
handlers = sorted({struct.unpack('<I', u.mem_read(tbl + 4 * i, 4))[0] & ~1 for i in range(256)})
print(f'{len(handlers)} distinct handlers')

for name in ('NesPort_Input', 'NesPort_Line'):
    u.hook_add(UC_HOOK_CODE, skip, begin=addr(name) & ~1, end=addr(name) & ~1)

cpu_data = addr('cpu_data')
lastbank_at = cpu_data + 0x84


def pc6502(uc):
    """m6502_pc is a host pointer: pc6502 = pointer - lastbank."""
    ptr = uc.reg_read(UC_ARM_REG_R9)
    base = struct.unpack('<I', u.mem_read(lastbank_at, 4))[0]
    return (ptr - base) & 0xffff

trace = []
limit = 200000


def on_op(uc, a, size, data):
    if len(trace) < limit:
        trace.append(pc6502(uc))


for h in handlers:
    u.hook_add(UC_HOOK_CODE, on_op, begin=h, end=h)

frames = int(sys.argv[1]) if len(sys.argv) > 1 else 1
for i in range(frames):
    trace.clear()
    call('Nes_Frame', 1)
    print(f'--- frame {i}: {len(trace)} instructions')
    zones = Counter()
    for pc in trace:
        zones['6000-7FFF' if pc < 0x8000 else '8000-DFFF' if pc < 0xE000 else 'E000-FFFF'] += 1
    print('   zones', dict(zones))
    for pc in trace[:1] + trace[-1:]:
        print(f'   ${pc:04X}')

print('first 60 PCs of the last frame:')
print(' '.join(f'{pc:04X}' for pc in trace[:60]))
print('last 60 PCs:')
print(' '.join(f'{pc:04X}' for pc in trace[-60:]))
print('top 12 PCs:', Counter(trace).most_common(12))
