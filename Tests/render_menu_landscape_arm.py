"""Render the menu at 800x480 through its real LCD calls (offline, no board).

Same technique as render_menu_arm.py: lcd_fill_color and lcd_open_window are
stubbed, the FSMC data write is hooked, and the pixels land in a host surface.
"""
from pathlib import Path
import struct, sys
from array import array
from PIL import Image
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3, UC_ARM_REG_PC, UC_ARM_REG_SP, UC_ARM_REG_LR

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root/'Tests'))
from sd_arm_harness import SdArm, pack_files

W, H = 800, 480
sd = SdArm({k: v for k, v in pack_files().items() if k != 'TITLES.DB'})
assert sd.boot() == 0
u, sy = sd.u, sd.symbols
u.mem_map(0x68000000, 0x1000)

def r32(p): return struct.unpack('<I', u.mem_read(p, 4))[0]
def w32(p, v): u.mem_write(p, struct.pack('<I', v))

stop = 0x080ff000
u.mem_write(stop, b'\0\xbe')
fill_stub, open_stub = 0x2001d000, 0x2001d004
u.mem_write(fill_stub, b'\x70\x47'); u.mem_write(open_stub, b'\x70\x47')
w32(sy['lcd_fill_color'], fill_stub | 1); w32(sy['lcd_open_window'], open_stub | 1)
u.mem_write(sy['LCD_X_LENGTH'], struct.pack('<H', W))
u.mem_write(sy['LCD_Y_LENGTH'], struct.pack('<H', H))
u.mem_write(sy['nes_screen_landscape'], b'\x01')

surface = array('H', [0]) * (W * H)
window = [0, 0, 0, 0, 0]
regs = (UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3)

def rect():
    x, y, w, h = (u.reg_read(r) for r in regs)
    assert 0 < w <= W and 0 < h <= H and x + w <= W and y + h <= H, ('out of bounds', x, y, w, h)
    return x, y, w, h

def fill(uc, a, size, data):
    x, y, w, h = rect()
    c = r32(u.reg_read(UC_ARM_REG_SP)) & 65535
    for row in range(y, y + h):
        surface[row * W + x:row * W + x + w] = array('H', [c]) * w
    u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))

def opened(uc, a, size, data):
    window[:] = [*rect(), 0]
    u.reg_write(UC_ARM_REG_PC, u.reg_read(UC_ARM_REG_LR))

def pixel(uc, access, a, size, value, data):
    x, y, w, h, off = window
    assert off < w * h, ('window overflow', window)
    surface[(y + off // w) * W + x + off % w] = value & 65535
    window[4] += 1

u.hook_add(UC_HOOK_CODE, fill, begin=fill_stub, end=fill_stub)
u.hook_add(UC_HOOK_CODE, opened, begin=open_stub, end=open_stub)
u.hook_add(UC_HOOK_MEM_WRITE, pixel, begin=0x68000002, end=0x68000003)

def call(name, *args):
    u.reg_write(UC_ARM_REG_SP, 0x2001fff0)
    u.reg_write(UC_ARM_REG_LR, stop | 1)
    for r, v in zip(regs, args):
        u.reg_write(r, v)
    u.emu_start(sy[name] | 1, stop, count=100000000)
    assert u.reg_read(UC_ARM_REG_PC) == stop, 'budget exhausted: ' + name
    return u.reg_read(UC_ARM_REG_R0)

def save(name):
    rgb = bytearray()
    for c in surface:
        rgb.extend((((c >> 11) & 31) * 255 // 31, ((c >> 5) & 63) * 255 // 63, (c & 31) * 255 // 31))
    out = root / 'Tests/nes_output'
    out.mkdir(exist_ok=True)
    Image.frombytes('RGB', (W, H), bytes(rgb)).save(out / name)

state = 0x2001c000
count = call('NesLibrary_Count')
call('NesMenu_Init', state, count, 1, 1)
call('NesMenu_Draw', state)
save('menu_landscape.png')
print('landscape menu rendered, games:', count)
