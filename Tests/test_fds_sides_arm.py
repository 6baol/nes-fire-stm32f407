"""Two-sided FDS: observable eject/insert, unchanged CPU/RAM, real input chord."""
import struct,json,hashlib
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_PC,UC_ARM_REG_LR
from test_mmc3_arm import NesArm,ROOT
a=NesArm();raw=(ROOT/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes()
side_b=bytearray(raw);side_b[21]^=0x55;disk=raw+side_b
source=0x6c060000;bios=0x6c0d0000;image=bytearray(b'\xea'*8192)
image[:3]=bytes.fromhex('4c 00 e0');image[-6:]=struct.pack('<HHH',0xe000,0xe000,0xe000)
a.u.mem_write(source,bytes(disk));a.u.mem_write(bios,bytes(image))
assert a.call('Nes_LoadDisk',source,len(disk),bios,8192)==0
read=lambda n:a.call('FdsIo_Read',n)
write=lambda n,v:a.call('FdsIo_Write',n,v)
tick=lambda n:a.call('FdsIo_Tick',n)
assert a.call('FdsDrive_Sides')==2 and a.call('FdsDrive_Side')==0
assert a.call('FdsDrive_RequestSide',2)==1 and read(0x4032)==6
assert a.call('FdsDrive_RequestSide',0)==0 and read(0x4032)==6
ram=a.r32(a.addr('NES_RAM'));a.u.mem_write(ram+32,b'RETAINED')
before=bytes(a.u.mem_read(a.addr('cpu_data'),140));memory=bytes(a.u.mem_read(ram,2048))
assert a.call('FdsDrive_RequestSide',1)==0
assert a.call('FdsDrive_Changing')==1 and read(0x4032)==7
assert a.call('FdsDrive_RequestSide',0)==1,'Pending insertion was replaced'
tick(894886);assert read(0x4032)==7
tick(1);assert read(0x4032)==6 and a.call('FdsDrive_Changing')==0
assert bytes(a.u.mem_read(ram,2048))==memory and bytes(a.u.mem_read(a.addr('cpu_data'),140))==before
write(0x4023,3);write(0x4025,0xc5);tick(50000+3537*150)
assert read(0x4031)==0x80
for i in range(22):tick(150);assert read(0x4031)==side_b[i],('Side B byte differs',i)
assert bytes(a.u.mem_read(source,len(disk)))==bytes(disk),'Source FDS was modified'
# Use actual NesPort_Input; replace only board joystick/touch polling.
a.u.hook_del(a.input_hook);a.u.mem_map(0x40000000,0x30000)
a.u.mem_write(0x40020410,struct.pack('<I',128))
a.u.mem_write(0x2001a000,struct.pack('<HHHHffBB2xIII',2048,2048,2048,2048,0,0,1,1,0,0,0))
a.u.mem_write(0x2001a100,bytes(40))
def stub(uc,address,size,data):uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
def joy(uc,address,size,data):uc.reg_write(UC_ARM_REG_R0,0x2001a000);stub(uc,address,size,data)
def cap(uc,address,size,data):uc.reg_write(UC_ARM_REG_R0,0x2001a100);stub(uc,address,size,data)
for name,hook in [('Joystick_Poll',stub),('Touchpad_Poll',stub),('Joystick_Get',joy),('Touchpad_Get',cap)]:
    a.u.hook_add(UC_HOOK_CODE,hook,begin=a.addr(name)&~1,end=a.addr(name)&~1)
a.u.mem_write(a.addr('app_state'),b'\x01');a.u.mem_write(a.addr('nes_test_pad'),b'\x84')
a.call('NesPort_Input');assert a.call('FdsDrive_Side')==0 and read(0x4032)==7
assert a.read8(a.addr('PADdata'))==0,'Disk chord leaked into game controls'
for _ in range(5):a.call('NesPort_Input')
assert a.call('FdsDrive_Side')==0
a.u.mem_write(a.addr('nes_test_pad'),b'\0');a.call('NesPort_Input');tick(894887)
assert a.call('FdsDrive_Side')==0 and read(0x4032)&1==0
a.u.mem_write(a.addr('nes_test_pad'),b'\x44');a.call('NesPort_Input')
assert a.call('FdsDrive_Side')==1,'Left chord did not wrap to final side'
a.call('FdsDrive_Unmount');tick(1000000)
assert a.call('FdsDrive_Sides')==0 and read(0x4032)==7
report={'result':'PASS','hardware_tested':False,'checks':['side B stream contents','half-second eject visible to BIOS',
        'no CPU/RAM reset','no source mutation','invalid/pending requests rejected','real Select+left/right chord',
        'held chord does not repeat','chord filtered from game','wrap and unmount cancel'],
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/fds_sides_results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
