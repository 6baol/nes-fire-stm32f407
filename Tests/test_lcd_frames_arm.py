"""Compare actual ARM LCD writes with the original 256x240 -> 480x450 scaling."""
import argparse
from array import array
import hashlib
import json
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_MCLASS, UC_MODE_THUMB, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3
from test_mmc3_arm import NesArm, ROOT

WIDTH, HEIGHT, TOP = 480, 450, 112
OPEN_WINDOW = 0x080FE000
SOURCE, PALETTE = 0x6C0FC000, 0x6C0FC200
CAPTURE = 0x6C040000
LCD_DATA = 0x68000002


class Panel(NesArm):
    def __init__(self, axf):
        # NesArm's default constructor stubs NesPort_Line. Here its ARM body
        # must run and the only mock is the display controller itself.
        self.u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        for base, length in [(0x08000000, 0x100000), (0x10000000, 0x10000),
                             (0x20000000, 0x20000), (0x6C000000, 0x100000),
                             (0x68000000, 0x1000), (0xE0000000, 0x100000)]:
            self.u.mem_map(base, length)
        with axf.open('rb') as stream:
            elf = ELFFile(stream)
            for section in elf.iter_sections():
                if section['sh_flags'] & 2 and section['sh_type'] != 'SHT_NOBITS' and section['sh_size']:
                    self.u.mem_write(section['sh_addr'], section.data())
            self.symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
        if 'xmap' in self.symbols:  # v0.42 initializes this table in NesApp_Init.
            self.u.mem_write(self.addr('xmap'), struct.pack('<480H', *(x * 256 // WIDTH for x in range(WIDTH))))
        self.set_word('SystemCoreClock', 168000000)
        self.u.mem_write(OPEN_WINDOW, bytes.fromhex('7047'))  # bx lr
        self.set_word('lcd_open_window', OPEN_WINDOW | 1)
        self.u.hook_add(UC_HOOK_CODE, self.open_window, begin=OPEN_WINDOW, end=OPEN_WINDOW)
        self.u.hook_add(UC_HOOK_MEM_WRITE, self.pixel_write, begin=LCD_DATA, end=LCD_DATA + 1)
        self.surface = array('H', [0xBAD0]) * (WIDTH * HEIGHT)
        self.region = None
        self.offset = 0
        self.writes = 0

    def set_word(self, symbol, value):
        self.u.mem_write(self.addr(symbol), struct.pack('<I', value))

    def completed_window(self):
        if self.region:
            assert self.offset == self.region[2] * self.region[3], ('incomplete LCD window', self.region, self.offset)

    def open_window(self, uc, address, size, data):
        self.completed_window()
        x, y, width, height = (uc.reg_read(reg) for reg in (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3))
        assert 0 < width <= WIDTH - x and TOP <= y < TOP + HEIGHT and 0 < height <= TOP + HEIGHT - y
        self.region = x, y - TOP, width, height
        self.offset = 0

    def pixel_write(self, uc, access, address, size, value, data):
        assert self.region and address == LCD_DATA and size == 2
        x, y, width, height = self.region
        assert self.offset < width * height, ('LCD window overflow', self.region, self.offset)
        row, column = divmod(self.offset, width)
        self.surface[(y + row) * WIDTH + x + column] = value
        self.offset += 1
        self.writes += 1

    def present(self, name, rows, palette, pointer):
        before = self.writes
        expected = array('H')
        for y, row in enumerate(rows):
            self.u.mem_write(SOURCE, bytes(row))
            self.call('NesPort_Line', y, SOURCE, pointer)
            expanded = array('H', (palette[row[x * 256 // WIDTH] & 63] for x in range(WIDTH)))
            expected.extend(expanded * ((y + 1) * HEIGHT // 240 - y * HEIGHT // 240))
        self.completed_window()
        if self.surface != expected:
            position = next(i for i, (actual, ref) in enumerate(zip(self.surface, expected)) if actual != ref)
            raise AssertionError((name, 'RGB565 mismatch at LCD x,y', position % WIDTH, TOP + position // WIDTH,
                                  hex(self.surface[position]), hex(expected[position])))
        return self.writes - before


def run(axf):
    panel = Panel(axf)
    cached = 'nes_lcd_pixels' in panel.symbols
    # Two distinct immutable palette tables exercise the supplied pointer.
    palette = tuple((i * 997) & 0xFFFF for i in range(64))
    alternate = tuple(p ^ 0xFFFF for p in palette)
    panel.u.mem_write(PALETTE, struct.pack('<64H', *palette))
    panel.u.mem_write(PALETTE + 128, struct.pack('<64H', *alternate))
    rows = [bytearray((x + y * 19) & 255 for x in range(256)) for y in range(240)]
    writes = {}
    writes['first'] = panel.present('first', rows, palette, PALETTE)
    assert writes['first'] == WIDTH * HEIGHT
    writes['unchanged'] = panel.present('unchanged', rows, palette, PALETTE)
    if cached:
        assert writes['unchanged'] == 0

    # Exercise the extreme pixels, all eight horizontal scale phases, a
    # single changed pixel and widely separated changed groups on one row.
    for x, y in [(0, 0), (255, 239), (1, 150), (207, 150), (101, 38)]:
        rows[y][x] ^= 11
    for phase in range(8):
        rows[11 + phase][64 + phase] ^= 7
    writes['isolated'] = panel.present('isolated', rows, palette, PALETTE)
    if cached:
        assert 0 < writes['isolated'] < WIDTH * HEIGHT

    rows = [row[3:] + row[:3] for row in rows]
    writes['scroll'] = panel.present('scroll', rows, palette, PALETTE)
    writes['palette_changed'] = panel.present('palette_changed', rows, alternate, PALETTE + 128)
    alternate = tuple(p ^ 0x00FF for p in alternate)
    panel.u.mem_write(PALETTE + 128, struct.pack('<64H', *alternate))
    writes['palette_edited_in_place'] = panel.present('palette_edited_in_place', rows, alternate, PALETTE + 128)

    # A capture during an unchanged frame must still return all 61,440
    # native RGB565 values, irrespective of which pixels go to the LCD.
    panel.set_word('nes_capture_request', 1)
    writes['capture'] = panel.present('capture', rows, alternate, PALETTE + 128)
    assert panel.r32(panel.addr('nes_capture_ready')) == 1
    expected_capture = b''.join(struct.pack('<256H', *(alternate[p & 63] for p in row)) for row in rows)
    assert bytes(panel.u.mem_read(CAPTURE, len(expected_capture))) == expected_capture
    if cached:
        assert writes['capture'] == 0

    # A menu or error overlay has replaced the LCD contents. Resume with
    # the same source frame and confirm that every pixel is restored.
    panel.surface = array('H', [0xBAD0]) * (WIDTH * HEIGHT)
    # The real transition also draws text outside the game rectangle.
    text_address = panel.addr('PixelFont_Text') & ~1
    hook = panel.u.hook_add(UC_HOOK_CODE, panel._skip, begin=text_address, end=text_address)
    panel.call('game_chrome')
    panel.u.hook_del(hook)
    writes['after_overlay'] = panel.present('after_overlay', rows, alternate, PALETTE + 128)
    assert writes['after_overlay'] == WIDTH * HEIGHT
    return {'result': 'PASS', 'hardware_tested': False, 'axf_sha256': hashlib.sha256(axf.read_bytes()).hexdigest(),
            'reference_pixels_per_case': WIDTH * HEIGHT, 'lcd_pixel_writes': writes}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--axf', type=Path, default=ROOT / 'Project/Output/Fire_F407ZG.axf')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = json.dumps(run(args.axf), indent=2)
    if args.output:
        args.output.write_text(report + '\n', encoding='utf-8')
    print(report)
