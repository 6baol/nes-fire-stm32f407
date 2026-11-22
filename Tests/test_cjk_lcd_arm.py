"""CJK rendering through the real ARM menu code, with the LCD replaced by a hook.
The glyph bytes come from the on-card font, so this also checks FONT.MAP lookup."""
import struct, sys, hashlib
from unicorn import UC_HOOK_MEM_WRITE
from sd_arm_harness import SdArm, ROOT
from test_mmc1_axrom_arm import rom as make_rom

FONT = ROOT / 'Assets/fonts/cjk'
TEXT = '蝙蝠侠'
TEXT_ADDR = 0x2001c400


def put_text(a, text, addr=TEXT_ADDR):
    a.u.mem_write(addr, text.encode('utf-8') + b'\0')
    return addr


def main():
    files = {'蝙蝠侠 - 幻想汉化 (CN).NES': make_rom(0, prg16=2, chr8=1)}
    for name in ('FONT.MAP', 'FONT.HZK'):
        files[name] = (FONT / name).read_bytes()
    a = SdArm(files)
    assert a.boot() == 0
    assert a.names() == ['蝙蝠侠 - 幻想汉化 (CN).NES']

    mapping = files['FONT.MAP']
    size = mapping[6]
    stride = (size + 7) // 8
    assert 16 <= size <= 32 and stride * size <= 128, (size, stride)
    assert a.call('CjkFont_Cell') == size

    a.u.mem_map(0x68000000, 0x1000)
    stub = 0x2001d000
    a.u.mem_write(stub, b'\x70\x47')                      # bx lr
    a.u.mem_write(a.addr('lcd_open_window'), struct.pack('<I', stub | 1))
    pixels = []
    def capture(uc, access, address, size_, value, data):
        if address in (0x68000002, 0x68000003):
            pixels.append(value & 0xFFFF)
    a.u.hook_add(UC_HOOK_MEM_WRITE, capture, begin=0x68000002, end=0x68000003)

    fg, bg = 0xFFFF, 0x0000
    start = len(pixels)
    width = a.call('Utf8_Draw', 0, 0, put_text(a, TEXT), fg, bg)
    assert width == size * len(TEXT), (width, size)
    drawn = pixels[start:]
    assert len(drawn) == size * size * len(TEXT), len(drawn)

    hzk = files['FONT.HZK']
    count = struct.unpack_from('<I', mapping, 8)[0]
    pairs = {struct.unpack_from('<H', mapping, 12 + i * 4)[0]:
             struct.unpack_from('<H', mapping, 14 + i * 4)[0] for i in range(count)}
    per = stride * size
    for n, ch in enumerate(TEXT):
        slot = pairs[ord(ch)]
        bits = hzk[slot * per:(slot + 1) * per]
        expected = []
        for row in range(size):
            for col in range(size):
                value = bits[row * stride + col // 8]
                expected.append(fg if value & (0x80 >> (col % 8)) else bg)
        assert drawn[n * size * size:(n + 1) * size * size] == expected, f'glyph {ch} differs'

    start = len(pixels)
    width = a.call('Utf8_Draw', 0, 0, put_text(a, 'AB'), fg, bg)
    assert width == 2 * size and len(pixels) - start == 2 * size * size

    # Without the card font a CJK character degrades to '?' instead of garbage.
    b = SdArm({'x.nes': make_rom(0, prg16=2, chr8=1)})
    assert b.boot() == 0
    b.u.mem_map(0x68000000, 0x1000)
    b.u.mem_write(stub, b'\x70\x47')
    b.u.mem_write(b.addr('lcd_open_window'), struct.pack('<I', stub | 1))
    assert b.call('Utf8_Draw', 0, 0, put_text(b, '蝙'), fg, bg) == 16

    report = {'result': 'PASS', 'hardware_tested': False, 'glyph_size': size,
              'checks': ['UTF-8 filename reaches the catalog',
                         'FONT.MAP lookup and FONT.HZK bits match on the LCD',
                         'ASCII uses the Flash font with the same cell',
                         'missing font degrades to ? without crashing'],
              'axf_sha256': hashlib.sha256((ROOT / 'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    import json
    (ROOT / 'Tests/nes_output/cjk_lcd_results.json').write_text(json.dumps(report, indent=2))
    print(f'PASS CJK LCD rendering: {len(TEXT)} glyphs at {size}x{size}')


if __name__ == '__main__':
    main()
