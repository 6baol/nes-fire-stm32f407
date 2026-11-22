"""Synthetic PRG-RAM mapping regression, not an FDS disk or SMB2 test."""
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3

root = Path(__file__).resolve().parents[1]
u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
for a, n in [(0x08000000, 0x100000), (0x20000000, 0x20000),
             (0x10000000, 0x10000), (0x6c000000, 0x100000), (0xe0000000, 0x100000)]:
    u.mem_map(a, n)
u.mem_write(0xe000ed88, struct.pack('<I', 0x00f00000))
with (root / 'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    elf = ELFFile(f)
    for s in elf.iter_sections():
        if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS' and s['sh_size']:
            u.mem_write(s['sh_addr'], s.data())
    syms = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')

def r32(a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]

def call(name, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        u.reg_write(reg, value)
    u.emu_start(syms[name] | 1, stop, count=30000000)
    assert u.reg_read(UC_ARM_REG_PC) == stop, 'instruction budget exhausted: ' + name
    return u.reg_read(UC_ARM_REG_R0)

def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

p = syms['NesPort_Input'] & ~1
u.hook_add(UC_HOOK_CODE, skip, begin=p, end=p)
image, bios_at = 0x6c080000, 0x6c090000
prg = bytearray(b'\xea' * 32768)
code = bytearray()
addresses = (0x6100, 0x8100, 0xa100, 0xc100)
for i, a in enumerate(addresses):
    code += bytes((0xa9, 0x31 + i, 0x8d, a & 255, a >> 8))  # LDA/STA absolute
for i, a in enumerate(addresses):
    code += bytes((0xad, a & 255, a >> 8, 0x85, 0x10 + i))  # read each bank back
code += bytes.fromhex('a9 55 8d 10 e0 20 00 80 4c 00 c0')  # BIOS write, JSR, JMP
prg[:len(code)] = code
prg[0x2000:0x2003] = bytes.fromhex('e6 20 60')  # $8000: INC $20 / RTS
prg[0x6000:0x6003] = bytes.fromhex('4c 00 c0')  # $c000: JMP $c000
prg[0x7ffa:0x8000] = struct.pack('<HHH', 0x6000, 0x6000, 0x6000)
rom = b'NES\x1a\x02\x00' + bytes(10) + prg
bios = bytearray(b'\xea' * 8192)
bios[0:1] = b'\x40'  # RTI
bios[0x100:0x103] = bytes.fromhex('4c 00 e1')
bios[-6:] = struct.pack('<HHH', 0xe000, 0xe100, 0xe000)
u.mem_write(image, bytes(rom))
u.mem_write(bios_at, bytes(bios))
assert call('Nes_LoadFds', image, len(rom), bios_at, 8192) == 0
cd = syms['cpu_data']
assert r32(cd + 104) == cd + 4, 'CPU read-dispatch register corrupted during entry'
maps = [r32(cd + 68 + 4*i) for i in range(8)]
assert len(set(maps[3:7])) == 1, '32 KiB map is not contiguous'
assert call('Nes_ApuReadDmc', 0xe010) == 0xea
saved = bytes(u.mem_read(cd + 100, 24))
call('cpu_start_fds', 0x6000)
assert bytes(u.mem_read(cd + 100, 24)) == saved, 'entry changed reset registers'
call('Nes_Frame', 0)
ram = r32(syms['NES_RAM'])
assert bytes(u.mem_read(ram + 0x10, 4)) == bytes(range(0x31, 0x35)), 'bank reads alias'
assert u.mem_read(ram + 0x20, 1)[0] == 1, 'JSR/RTS across PRG-RAM banks failed'
assert r32(syms['nes_faults']) == 0
for i, a in enumerate(addresses):
    assert call('Nes_ApuReadDmc', a) == 0x31 + i, 'DMC does not read PRG RAM'
assert call('Nes_ApuReadDmc', 0xe010) == 0xea, 'BIOS was writable'
saved = bytes(u.mem_read(cd, 160))
assert call('Nes_LoadFds', image, len(rom), bios_at, 8191) == 6
u.mem_write(image + 6, b'\x04')  # reject trainer instead of interpreting it as PRG
assert call('Nes_LoadFds', image, len(rom), bios_at, 8192) == 6
assert bytes(u.mem_read(cd, 160)) == saved, 'rejected snapshot changed CPU state'
u.mem_write(image + 6, b'\0')
u.mem_write(image + 16 + 0x7ffc, b'\0\0')
assert call('Nes_LoadFds', image, len(rom), bios_at, 8192) == 6
print('PASS: synthetic PRG-RAM banks, CPU entry, JSR/RTS, DMC, BIOS protection, rejection')
print('Not a game, disk-drive, audio, or physical-board validation.')
