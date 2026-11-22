"""Actual FDS BIOS/disk boot regression on Keil ARM instructions (not a board test)."""
from pathlib import Path
import struct,sys
source=Path(__file__).with_name('test_nes_fds.py')
exec(compile(source.read_text(encoding='utf-8').split('rom_path =')[0],str(source),'exec'))
from unicorn.arm_const import UC_ARM_REG_R2
palette=[0]*64

def capture(uc,a,size,data):
    pp=uc.reg_read(UC_ARM_REG_R2)
    palette[:]=struct.unpack('<64H',uc.mem_read(pp,128))

u.hook_add(UC_HOOK_CODE,capture,begin=addr('NesPort_Line')&~1,end=addr('NesPort_Line')&~1)
raw=(root/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes()
bios=(root/'Roms/disksys.rom').read_bytes()
u.mem_write(0x6c080000,raw);u.mem_write(0x6c090000,bios)
rc=call('Nes_LoadDisk',0x6c080000,len(raw),0x6c090000,len(bios))
if rc==9:
 print('BLOCKED: supplied BIOS is known corrupt; game boot not validated')
 raise SystemExit(2)
assert rc==0,rc
cd=addr('cpu_data');ram=r32(addr('NES_RAM'))
game_seen=False
pcm=bytearray()
def advance(draw=0):
    call('Nes_Frame',draw)
    call('apu_process',0x6c0b8000,184)
    pcm.extend(u.mem_read(0x6c0b8000,184))
for i in range(int(sys.argv[1]) if len(sys.argv)>1 else 900):
    advance(1 if i%30==29 else 0)
    game_seen |= 0x6000 <= ((r32(cd+124)-r32(cd+132))&65535) < 0xe000
    if i%60==59:
        pc=(r32(cd+124)-r32(cd+132))&65535
        print(i+1,hex(pc),'faults',r32(addr('nes_faults')),'bytes',r32(addr('nes_fds_bytes')),'reads',r32(addr('nes_fds_reads')),'mode',u.mem_read(ram+0x770,4).hex(),'colours',len(set(frame)),flush=True)
rgb=bytearray()
for v in frame:
 c=palette[v&63];rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
out=root/'Tests/nes_output/smb2_disk.ppm';out.parent.mkdir(exist_ok=True)
out.write_bytes(b'P6\n256 240\n255\n'+rgb)
print(out)
assert r32(addr('nes_faults'))==0 and game_seen and len(set(frame))>=3
print('PASS: disk/BIOS smoke boot only; gameplay and board still require validation')

u.mem_write(addr('PADdata'),b'\x08')
for _ in range(4):advance()
u.mem_write(addr('PADdata'),b'\0')
for i in range(900):
    advance(1 if i%30==29 else 0)
    state=bytes(u.mem_read(ram+0x770,4))
    if i%60==59:print('start',i+1,state.hex(),'sub',u.mem_read(ram+0xe,1).hex(),flush=True)
    if state[0]==1 and state[2]==4:
        break
else:raise AssertionError('Start did not enter game mode/task 4')
for _ in range(30):advance()
assert u.mem_read(ram+0xe,1)[0]==8, 'player controller is not ready'
def position():
    return (u.mem_read(ram+0x86,1)[0]+256*u.mem_read(ram+0x6d,1)[0],u.mem_read(ram+0xce,1)[0])
before=position();u.mem_write(addr('PADdata'),b'\x80')
for _ in range(12):advance()
after=position();assert after[0]>before[0],('right did not move player',before,after)
ground=after[1];u.mem_write(addr('PADdata'),b'\x83');jump=[]
for _ in range(8):advance();jump.append(position()[1])
assert min(jump)<ground-8,('A+B jump did not lift player',ground,jump)
u.mem_write(addr('PADdata'),b'\x82')
for _ in range(30):advance()
run_after=position()
assert run_after[0]>after[0]+20,('sustained B+right movement failed',after,run_after)
u.mem_write(addr('PADdata'),b'\0');advance(1)
assert r32(addr('nes_faults'))==0
assert r32(addr('nes_apu_queue_drops'))==0
assert max(pcm)-min(pcm)>32
rgb=bytearray()
for v in frame:
 c=palette[v&63];rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
(root/'Tests/nes_output/smb2_gameplay.ppm').write_bytes(b'P6\n256 240\n255\n'+rgb)
print('PASS: Start enters 1-1; right',before,'->',after,'->',run_after,'B+A jump Y',jump,'audio range',min(pcm),max(pcm))
import json,hashlib
report={'result':'PASS','scope':'actual Keil ARM instructions under Unicorn; not board/audio recording',
 'disk_sha1':hashlib.sha1(raw).hexdigest(),'bios_sha1':hashlib.sha1(bios).hexdigest(),
 'axf_sha256':hashlib.sha256((root/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest(),
 'title_boot':True,'start_enters_1_1':True,'player_before':before,'player_right':run_after,
 'b_a_jump_y':jump,'pcm_range':[min(pcm),max(pcm)],'cpu_faults':r32(addr('nes_faults')),
 'apu_queue_drops':r32(addr('nes_apu_queue_drops')),'hardware_tested':False}
(root/'Tests/nes_output/smb2_boot_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
