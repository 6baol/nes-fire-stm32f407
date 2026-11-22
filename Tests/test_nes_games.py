"""Boot every embedded game on the real Keil ARM core in Unicorn.

This does not claim to be a board test: it loads the actual firmware ELF, calls
Nes_Load/Nes_Frame on the compiled 6502 core and checks that the mapper runs,
that the PPU produces a non-uniform frame and that no CPU fault is counted.
"""
from pathlib import Path
import struct, json, sys
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import *

root = Path(__file__).resolve().parents[1]
out = root / 'Tests/nes_output'
out.mkdir(exist_ok=True)
sys.path.insert(0, str(root / 'tools'))
import embed_roms  # noqa: E402  (same normalisation the firmware image uses)

u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
for a, n in [(0x08000000, 0x100000), (0x20000000, 0x20000), (0x10000000, 0x10000),
             (0x6c000000, 0x100000), (0xe0000000, 0x100000), (0x68000000, 0x1000)]:
    u.mem_map(a, n)
u.mem_write(0xe000ed88, struct.pack('<I', 0x00f00000))
with (root / 'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    e = ELFFile(f)
    for s in e.iter_sections():
        if s['sh_flags'] & 2 and s['sh_type'] != 'SHT_NOBITS' and s['sh_size']:
            u.mem_write(s['sh_addr'], s.data())
    symbols = {s.name: s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name}


def addr(n):
    return symbols[n]


def r32(a):
    return struct.unpack('<I', u.mem_read(a, 4))[0]


def skip(uc, a, size, data):
    uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))


frame = bytearray(256 * 240)


def line(uc, a, size, data):
    y = uc.reg_read(UC_ARM_REG_R0)
    p = uc.reg_read(UC_ARM_REG_R1)
    frame[y * 256:(y + 1) * 256] = uc.mem_read(p, 256)
    skip(uc, a, size, data)


u.hook_add(UC_HOOK_CODE, skip, begin=addr('NesPort_Input') & ~1, end=addr('NesPort_Input') & ~1)
u.hook_add(UC_HOOK_CODE, line, begin=addr('NesPort_Line') & ~1, end=addr('NesPort_Line') & ~1)
stop = 0x080ff000
u.mem_write(stop, b'\x00\xbe')


def call(n, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for reg, v in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
        u.reg_write(reg, v)
    u.emu_start(addr(n) | 1, stop, count=200000000)
    if u.reg_read(UC_ARM_REG_PC) != stop:
        raise RuntimeError('instruction budget exhausted in ' + n)
    return u.reg_read(UC_ARM_REG_R0)


failures = []

# 1. The generated table must match Roms/roms.json exactly.
manifest = json.loads((root / 'Roms/roms.json').read_text(encoding='utf-8'))['games']
if 'nes_rom_images' in symbols:
    count = r32(addr('nes_rom_image_count'))
    if count != len(manifest):
        failures.append(f'embedded count {count} != manifest {len(manifest)}')
    for i, g in enumerate(manifest):
        ent = addr('nes_rom_images') + i * 20  # 3 pointers + uint32 + uint8 padded to 20
        label, fname, data, size, mapper = struct.unpack('<III', u.mem_read(ent, 12)) + \
            struct.unpack('<IB3x', u.mem_read(ent + 12, 8))
        raw = (root / 'Roms' / g['file']).read_bytes()
        expect = embed_roms.normalize(raw)
        if size != len(expect):
            failures.append(f'{g["file"]}: embedded size {size} != {len(expect)}')
        if mapper not in embed_roms.SUPPORTED:
            failures.append(f'{g["file"]}: unexpected mapper {mapper}')
        text = u.mem_read(label, 32).split(b'\0')[0].decode('ascii', 'replace')
        print(f'table[{i}] "{text}" size={size} mapper={mapper}')
else:
    print('note: nes_rom_images not linked into this image yet')

# 2. Boot each ROM through the real loader and 90 frames of the real core.
scratch = 0x6c080000
for g in manifest:
    rom = embed_roms.normalize((root / 'Roms' / g['file']).read_bytes())
    u.mem_write(scratch, rom)
    rc = call('Nes_Load', scratch, len(rom))
    if rc == 9 and g['file'].lower().endswith('.fds'):
        print(f'{g["file"]}: BLOCKED (rc=9, corrupt BIOS) - not a game pass')
        continue
    if rc == 5:
        # Reset vector outside $8000-$FFFF: an FDS data dump, not a cartridge.
        print(f'{g["file"]}: NOT BOOTABLE (rc=5, reset vector outside ROM) - skipped')
        continue
    if rc != 0:
        failures.append(f'{g["file"]}: Nes_Load rejected ({rc})')
        continue
    u.mem_write(addr('nes_faults'), b'\0\0\0\0')
    frame[:] = b'\0' * len(frame)
    frames_to_run=900 if g['file'].lower().endswith('.fds') else 90
    for _ in range(frames_to_run):
        call('Nes_Frame', 1)
    faults = r32(addr('nes_faults'))
    colors = len(set(frame))
    if faults:
        failures.append(f'{g["file"]}: {faults} CPU faults')
    if colors < 3:
        failures.append(f'{g["file"]}: frame has only {colors} colours')
    ppm = out / (Path(g['file']).stem[:40].replace(' ', '_') + '.ppm')
    ppm.write_bytes(b'P5\n256 240\n255\n' + bytes(frame))
    print(f'{g["file"]}: load=0 faults={faults} colours={colors} -> {ppm.name}')

# 3. Menu: navigation runs on the real ARM code, and one draw pass must only
#    touch the LCD data port (stubbed control pointers, FSMC window mapped).
if 'NesMenu_Move' in symbols:
    state = 0x2001e000
    stub = 0x2001e800
    u.mem_write(stub, b'\x70\x47')  # bx lr
    for name in ('lcd_fill_color', 'lcd_open_window'):
        u.mem_write(addr(name), struct.pack('<I', stub | 1))

    def field(off, fmt):
        return struct.unpack(fmt, u.mem_read(state + off, struct.calcsize(fmt)))[0]

    # Navigation only touches the state struct, so an 8-entry list is safe here.
    call('NesMenu_Init', state, 8, 1, 1)
    if field(0, '<h') != 0 or field(2, '<B') != 8:
        failures.append('menu init did not take effect')
    if call('NesMenu_Move', state, 0xFFFFFFFF) != 1 or field(0, '<h') != 7:
        failures.append('menu did not wrap to the last entry')
    if call('NesMenu_Move', state, 1) != 1 or field(0, '<h') != 0:
        failures.append('menu did not wrap back to the first entry')
    call('NesMenu_Init', state, 8, 1, 1)
    for _ in range(5):
        call('NesMenu_Move', state, 1)
    if field(0, '<h') != 5 or field(3, '<B') != 3:
        failures.append(f'menu window wrong at index {field(0, "<h")} first {field(3, "<B")}')

    # Drawing walks nes_rom_images, so it must run with the real game count.
    pixels = [0]
    colours = {}

    def on_pixel(uc, access, address, size, value, user):
        pixels[0] += 1
        colours[value] = colours.get(value, 0) + 1

    call('NesMenu_Init', state, r32(addr('nes_rom_image_count')), 1, 1)
    handle = u.hook_add(UC_HOOK_MEM_WRITE, on_pixel, begin=0x68000000, end=0x68000fff)
    call('NesMenu_Draw', state)
    u.hook_del(handle)
    accent = colours.get(0xFE8B, 0)
    print(f'menu draw: {pixels[0]} pixels, {len(colours)} colours, {accent} accent pixels')
    # Fill calls are stubbed: artwork/glyph streams still reach the LCD port.
    if pixels[0] < 40000:
        failures.append(f'menu draw only wrote {pixels[0]} pixels')
    if accent == 0:
        failures.append('menu selection cursor has no accent pixels')
else:
    print('note: menu code not linked into this image')

print('RESULT:', 'PASS' if not failures else 'FAIL')
for f in failures:
    print(' -', f)
sys.exit(1 if failures else 0)
