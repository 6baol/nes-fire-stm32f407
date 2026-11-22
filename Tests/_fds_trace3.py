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

def call(name, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, value in zip((UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3), args):
        u.reg_write(reg, value)
    u.emu_start(syms[name] | 1, stop, count=30000000)
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

cd = syms['cpu_data']
call('Nes_LoadFds', image, len(rom), bios_at, 8192)
call('cpu_start_fds', 0x6000)

# Hook prgram_R/W to trace
prgram_R_pc = syms['prgram_R'] & ~1
prgram_W_pc = syms['prgram_W'] & ~1

trace_count = [0]
max_trace = 20

def hook_code(uc, addr, size, data):
    if trace_count[0] < max_trace:
        # Check if we're in run6502 core loop area
        if 0x080177b4 <= addr <= 0x08017830:
            r0 = uc.reg_read(UC_ARM_REG_R0)
            r1 = uc.reg_read(UC_ARM_REG_R1)
            r9 = uc.reg_read(getattr(__import__('unicorn.arm_const', fromlist=['UC_ARM_REG_R9']), 'UC_ARM_REG_R9'))
            r12 = uc.reg_read(getattr(__import__('unicorn.arm_const', fromlist=['UC_ARM_REG_R12']), 'UC_ARM_REG_R12'))
            pc_byte = uc.mem_read(r9, 1)[0] if r9 >= 0x60000000 and r9 < 0x80000000 else 0
            print(f'  [0x{addr:08x}] r0={r0} r1=0x{r1:08x} r9=0x{r9:08x} r12=0x{r12:04x} next_byte=0x{pc_byte:02x}')
            trace_count[0] += 1

print('Running Nes_Frame with trace...')
try:
    call('Nes_Frame', 0)
    print('PASS!')
except Exception as e:
    pc = u.reg_read(UC_ARM_REG_PC)
    print(f'\nCRASH: {e}')
    print(f'PC=0x{pc:08x} (thumb bit stripped: 0x{pc & ~1:08x})')
    
    # 检查 PC 处的指令
    try:
        instr_bytes = u.mem_read(pc & ~1, 4)
        print(f'Memory at PC: {instr_bytes.hex()}')
    except:
        print('Cannot read memory at PC')
    
    # dump 所有寄存器
    regs = ['R0','R1','R2','R3','R4','R5','R6','R7','R8','R9','R10','R11','R12','SP','LR']
    for name in regs:
        try:
            v = u.reg_read(getattr(__import__('unicorn.arm_const', fromlist=['UC_ARM_REG_' + name]), 'UC_ARM_REG_' + name))
            print(f'  {name}=0x{v:08x}')
        except:
            pass
    
    # dump cpu_data 关键区域
    print(f'\ncpu_data[0x00] opz = 0x{struct.unpack("<I", u.mem_read(cd, 4))[0]:08x}')
    print(f'cpu_data[0x44] memmap_tbl[0..7]:')
    for i in range(8):
        v = struct.unpack('<I', u.mem_read(cd + 0x44 + i*4, 4))[0]
        print(f'  [{i}] = 0x{v:08x}')
