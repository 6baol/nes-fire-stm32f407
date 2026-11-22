"""Confirm cpu6502_init str opz is reached in Nes_LoadFds."""
from pathlib import Path
import struct, sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

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

# 反汇编确认 cpu6502_init 里 str r0, opz 的地址
cd = syms['cpu_data']
opz_store_pc = None

# 从反汇编知道 cpu6502_init 在 0x0801806c 附近，str opz 在 PC=0x0801808a
# 让我从 cpu6502_init 开始反汇编找 str r0, opz
cpu6502_init_addr = syms['cpu6502_init'] & ~1
print(f'cpu6502_init at 0x{cpu6502_init_addr:08x}')

# 读 32 字节，找 str r0, [r10, #0] (opz = r10+0)
code_bytes = u.mem_read(cpu6502_init_addr, 64)
print(f'Code at cpu6502_init: {code_bytes.hex()}')

# 手动 trace cpu6502_init 里关键地址
# 从反汇编 _fds_trace2.py 里看到 str opz at PC=0x0801808a
str_opz_pc = 0x0801808a

# Hook: 只在 cpu6502_init 和 cpu_reset_now 区域打印
step = [0]
def hook_code(uc, addr, size, data):
    step[0] += 1
    if step[0] < 5 or 0x08018060 <= addr <= 0x08018100 or 0x08017700 <= addr <= 0x08017800:
        opz = struct.unpack('<I', uc.mem_read(cd, 4))[0]
        print(f'  PC=0x{addr:08x} opz=0x{opz:08x}')

u.hook_add(UC_HOOK_CODE, hook_code)

stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')

image, bios_at = 0x6c080000, 0x6c090000
prg = bytearray(b'\xea' * 32768)
code = bytearray()
addresses = (0x6100, 0x8100, 0xa100, 0xc100)
for i, a in enumerate(addresses):
    code += bytes((0xa9, 0x31 + i, 0x8d, a & 255, a >> 8))
for i, a in enumerate(addresses):
    code += bytes((0xad, a & 255, a >> 8, 0x85, 0x10 + i))
code += bytes.fromhex('a9 55 8d 10 e0 20 00 80 4c 00 c0')
prg[:len(code)] = code
prg[0x2000:0x2003] = bytes.fromhex('e6 20 60')
prg[0x6000:0x6003] = bytes.fromhex('4c 00 c0')
prg[0x7ffa:0x8000] = struct.pack('<HHH', 0x6000, 0x6000, 0x6000)
rom = b'NES\x1a\x02\x00' + bytes(10) + prg
bios = bytearray(b'\xea' * 8192)
bios[0:1] = b'\x40'
bios[0x100:0x103] = bytes.fromhex('4c 00 e1')
bios[-6:] = struct.pack('<HHH', 0xe000, 0xe100, 0xe000)
u.mem_write(image, bytes(rom))
u.mem_write(bios_at, bytes(bios))

def call(name, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for i, v in enumerate(args):
        u.reg_write(i, v)
    u.emu_start(syms[name] | 1, stop, count=30000000)

def skip(uc, a, size, data):
    u.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))
p = syms['NesPort_Input'] & ~1
u.hook_add(UC_HOOK_CODE, skip, begin=p, end=p)

step[0] = 0
print('=== Nes_LoadFds ===')
try:
    call('Nes_LoadFds', image, len(rom), bios_at, 8192)
except Exception as e:
    print(f'Error: {e}')
opz = struct.unpack('<I', u.mem_read(cd, 4))[0]
print(f'Final opz = 0x{opz:08x} (expected 0x{syms.get("op_table",0):08x})')
