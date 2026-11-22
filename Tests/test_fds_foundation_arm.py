"""Exercise FDS image validation and timer I/O in the actual Keil ARM build.
All disk contents below are synthetic. Import also runs the mapping regression.
"""
import struct
from test_fds_snapshot_arm import call, u, syms, r32, cd, bios_at, bios

scratch, descriptor, file_at = 0x6c080000, 0x2001d000, 0x2001d100

def side(payload=b'\xea\xea\x60', address=0x6000, kind=0):
    data = bytearray(65500)
    data[:15] = b'\x01*NINTENDO-HVC*'
    data[56:58] = b'\x02\x01'
    data[58:74] = b'\x03\x00\x05TESTFILE' + struct.pack('<HHB', address, len(payload), kind)
    data[74] = 4
    data[75:75+len(payload)] = payload
    return bytes(data)

def open_disk(data):
    u.mem_write(scratch, data)
    return call('FdsImage_Open', descriptor, scratch, len(data))

raw = side()
assert open_disk(raw) == 0
assert bytes(u.mem_read(descriptor + 8, 2)) == b'\x01\0'
assert call('FdsImage_File', descriptor, 0, 0, file_at) == 0
ptr, address, size = struct.unpack('<IHH', u.mem_read(file_at, 8))
assert address == 0x6000 and size == 3
assert bytes(u.mem_read(ptr, size)) == b'\xea\xea\x60'
assert bytes(u.mem_read(file_at + 11, 9)) == b'TESTFILE\0'
assert call('FdsImage_File', descriptor, 0, 1, file_at) != 0
header = b'FDS\x1a\x02' + bytes(11)
double = header + raw + side(b'\x01\x02', 0x0760, 1)
assert open_disk(double) == 0
assert call('FdsImage_File', descriptor, 1, 0, file_at) == 0
assert struct.unpack('<HH', u.mem_read(file_at + 4, 4)) == (0x0760, 2)
saved = bytes(u.mem_read(descriptor, 12))
invalid = []
invalid += [raw[:-1], b'NES\x1a' + raw[4:], b'FDS\x1a\0' + bytes(11) + raw]
bad = bytearray(double);bad[16+65500+1] = 0
invalid.append(bytes(bad))  # malformed second side, no partial publication
bad = bytearray(raw);bad[74] = 3;invalid.append(bytes(bad))
bad = bytearray(raw);bad[71:73] = b'\xff\xff';invalid.append(bytes(bad))
invalid += [side(b'12', 0xdfff), side(b'12', 0x1fff, 1), side(b'12', 0x3fff, 2), side(kind=3)]
for data in invalid:
    assert open_disk(data) != 0
    assert bytes(u.mem_read(descriptor, 12)) == saved, 'invalid disk published partial state'
assert open_disk(raw) == 0
bad_bios=(__import__('pathlib').Path(__file__).resolve().parents[1]/'Roms/fds_bios.bin').read_bytes()
u.mem_write(bios_at,bad_bios)
assert call('Nes_LoadDisk', scratch, len(raw),bios_at,len(bad_bios)) == 9, 'known corrupt BIOS must be rejected'
bad = bytearray(raw);bad[74] = 0;u.mem_write(scratch, bytes(bad))
assert call('Nes_Load', scratch, len(bad)) == 8
print('PASS: headered/headerless, multi-side, PRG/CHR, bounds, corruption and loader status')

write = lambda a, v: call('FdsIo_Write', a, v)
read = lambda a: call('FdsIo_Read', a)
tick = lambda cycles: call('FdsIo_Tick', cycles)
call('FdsIo_Reset')
write(0x4020, 2);write(0x4021, 0);write(0x4022, 2);tick(100)
assert read(0x4030) == 0, 'disk I/O disabled must block timer start'
write(0x4023, 1);write(0x4022, 2)
tick(2);assert read(0x4030) == 0
tick(1);assert u.mem_read(syms['cpuirq'], 1)[0] == 1
assert read(0x4030) == 1 and read(0x4030) == 0
tick(100);assert read(0x4030) == 0, 'one-shot timer repeated'
write(0x4022, 3);tick(9);assert read(0x4030) == 1
tick(2);assert read(0x4030) == 0
tick(1);assert read(0x4030) == 1
write(0x4020, 0);write(0x4022, 3);tick(1);assert read(0x4030) == 1
tick(1000000);assert read(0x4030) == 1, 'large delta or zero reload failed'
write(0x4022, 0);assert read(0x4030) == 0
write(0x4022, 3);tick(1);write(0x4023, 0);assert read(0x4030) == 0
assert read(0x4032) == 7, 'unfinished drive must report no disk'
write(0x4023, 1)
vram = r32(syms['ppu']) + 4160  # ppu_data: fixed ARM layout, after 4 KiB nametables
write(0x4025, 0)
assert r32(vram+32) == r32(vram+40) and r32(vram+32) != r32(vram+36)
write(0x4025, 8)
assert r32(vram+32) == r32(vram+36) and r32(vram+32) != r32(vram+40)
print('PASS: I/O enable, one-shot/repeat/zero reload, IRQ acknowledge, mirroring')

# The 6502 must reach the registers through its assembly dispatch and vector
# through the BIOS map, rather than only passing direct C calls above.
call('FdsIo_Reset')
code = bytes.fromhex('a9 01 8d 23 40 a9 14 8d 20 40 a9 00 8d 21 40 a9 02 8d 22 40 58 4c 00 c0')
ram_base = r32(cd+68+3*4)
u.mem_write(ram_base + 0x6000, code)
u.mem_write(bios_at, bytes(bios))  # multi-side parser fixture reused the external SRAM scratch
u.mem_write(bios_at, bytes.fromhex('ad 30 40 e6 21 40'))  # read IRQ status / INC $21 / RTI
call('cpu_start_fds', 0x6000)
call('Nes_Frame', 0)
ram = r32(syms['NES_RAM'])
assert u.mem_read(ram + 0x21, 1)[0] == 1, 'timer did not reach 6502 IRQ handler exactly once'
assert r32(syms['nes_faults']) == 0
print('PASS: real 6502 register writes, frame scheduler, BIOS IRQ vector and acknowledgement')

# Returning to a cartridge must restore the original $6000 SRAM dispatch;
# otherwise the snapshot's rebased handler will access beyond save RAM.
cart = bytearray(b'NES\x1a\x02\0' + bytes(10) + b'\xea'*32768)
cart[16:29] = bytes.fromhex('a9 66 8d 23 61 ad 23 61 85 25 4c 0a 80')
cart[-6:] = struct.pack('<HHH', 0x8000, 0x8000, 0x8000)
u.mem_write(scratch, bytes(cart))
assert call('Nes_Load', scratch, len(cart)) == 0
call('run6502', 1000*256)
ram = r32(syms['NES_RAM']);sram = r32(syms['NES_SRAM'])
assert u.mem_read(ram+0x25, 1)[0] == 0x66
assert u.mem_read(sram+0x123, 1)[0] == 0x66
assert r32(syms['nes_faults']) == 0
print('PASS: switching from FDS RAM back to cartridge SRAM restores dispatch')
print('No game image, disk transfer, physical board or audio validation claimed.')
