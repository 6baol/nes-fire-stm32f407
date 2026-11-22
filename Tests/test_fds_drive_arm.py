"""Verify all SMB2 disk blocks through compiled read-only drive registers.
Uses a synthetic BIOS; does not claim to boot the game or the supplied BIOS.
"""
from pathlib import Path
import struct, zlib
source=Path(__file__).with_name('test_nes_fds.py')
exec(compile(source.read_text(encoding='utf-8').split('rom_path =')[0],str(source),'exec'))
raw=(root/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes()
assert len(raw)==65500 and zlib.crc32(raw)==0xf04cd4cd
disk_at,bios_at=0x6c0a0000,0x6c090000
bios=bytearray(b'\xea'*8192)
bios[:3]=bytes.fromhex('4c 00 e0')
bios[-6:]=struct.pack('<HHH',0xe000,0xe000,0xe000)
u.mem_write(disk_at,raw);u.mem_write(bios_at,bytes(bios))
assert call('Nes_LoadDisk',disk_at,len(raw),bios_at,8192)==0
write=lambda a,v:call('FdsIo_Write',a,v)
read=lambda a:call('FdsIo_Read',a)
tick=lambda n:call('FdsIo_Tick',n)
assert read(0x4032)==6
write(0x4023,1);write(0x4025,0xc5)
tick(50000+3537*150)
assert read(0x4032)==4 and read(0x4031)==0x80
blocks=[raw[:56],raw[56:58]]
p=58
for i in range(raw[57]):
 size=int.from_bytes(raw[p+13:p+15],'little')
 blocks.extend((raw[p:p+16],raw[p+16:p+17+size]))
 p+=17+size
count=0
for bi,block in enumerate(blocks):
 if bi:
  write(0x4025,0x85)  # disable sync/transfer detection while traversing gap
  tick(122*150)
  write(0x4025,0xc5);tick(150)
  assert read(0x4031)==0x80,('sync',bi)
 for expected in block:
  tick(150)
  assert read(0x4030)&2
  actual=read(0x4031)
  assert actual==expected,(bi,count,actual,expected)
  count+=1
 tick(150);read(0x4031)  # CRC byte 1
 tick(150);read(0x4031)  # CRC byte 2
print('PASS: sync, gaps, all',len(blocks),'blocks,',count,'disk bytes via actual ARM registers')
write(0x4025,0);tick(16)
assert read(0x4032)==6
write(0x4025,0xc5);tick(50000+3537*150)
assert read(0x4031)==0x80
tick(150);assert read(0x4031)==1
call('FdsDrive_Unmount');assert read(0x4032)==7
print('PASS: motor stop, rewind, restart, read-only status and unmount')
bad=(root/'Roms/fds_bios.bin').read_bytes();u.mem_write(bios_at,bad)
cd=addr('cpu_data');saved=bytes(u.mem_read(cd,160))
assert call('Nes_LoadDisk',disk_at,len(raw),bios_at,len(bad))==9
assert bytes(u.mem_read(cd,160))==saved
print('PASS: known damaged BIOS rejected without changing CPU state')
print('No real BIOS/game/physical-board boot is claimed.')
