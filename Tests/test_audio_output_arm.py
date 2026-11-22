"""Actual ARM audio routing with mocked WM8978 I2C transport; no board."""
import json,hashlib,struct
from unicorn import UC_HOOK_CODE,UC_HOOK_MEM_READ
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R2,UC_ARM_REG_PC,UC_ARM_REG_LR
from test_mmc3_arm import NesArm,ROOT

a=NesArm();a.u.mem_map(0x40000000,0x30000);writes=[];fail_next=[False]
def ret(uc,v=0):uc.reg_write(UC_ARM_REG_R0,v);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
def transmit(uc,address,size,data):
    wire=bytes(uc.mem_read(uc.reg_read(UC_ARM_REG_R2),2))
    reg=wire[0]>>1;value=((wire[0]&1)<<8)|wire[1];writes.append((reg,value))
    fail=fail_next[0];fail_next[0]=False;ret(uc,int(fail))
a.u.hook_add(UC_HOOK_CODE,transmit,begin=a.addr('HAL_I2C_Master_Transmit')&~1,end=a.addr('HAL_I2C_Master_Transmit')&~1)
a.u.hook_add(UC_HOOK_CODE,lambda uc,*args:ret(uc),begin=a.addr('HAL_Delay')&~1,end=a.addr('HAL_Delay')&~1)
def reg(n):return struct.unpack('<H',a.u.mem_read(a.addr('nes_audio_codec_regs')+2*n,2))[0]
def ready(v):a.u.mem_write(a.addr('nes_audio_ready'),struct.pack('<I',v))
assert a.call('NesAudio_GetOutput')==1
assert a.call('NesAudio_SetOutput',1)==1 and not writes
def pll_ready(uc,access,address,size,value,data):
    cr=struct.unpack('<I',uc.mem_read(0x40023800,4))[0]
    cr=(cr|(1<<27)) if cr&(1<<26) else (cr&~(1<<27))
    uc.mem_write(0x40023800,struct.pack('<I',cr))
a.u.hook_add(UC_HOOK_MEM_READ,pll_ready,begin=0x40023800,end=0x40023803)
for name in ['HAL_I2C_Init','HAL_GPIO_Init']:
    a.u.hook_add(UC_HOOK_CODE,lambda uc,*args:ret(uc),begin=a.addr(name)&~1,end=a.addr(name)&~1)
assert a.call('NesAudio_Init')==0
assert a.call('NesAudio_GetOutput')==1 and a.r32(a.addr('nes_audio_ready'))==1
assert a.read8(a.addr('nes_audio_suspended'))==1
assert reg(2)==0 and reg(3)==0x6f and reg(43)==0x10 and reg(49)==2
assert reg(52)&64 and reg(53)&64 and not reg(54)&64 and not reg(55)&64
assert reg(54)&63==reg(55)&63==36,'Default speaker gain changed'
writes.clear()
assert a.call('NesAudio_SetOutput',3)==1 and not writes
assert a.call('NesAudio_SetOutput',0)==0
a.call('NesAudio_Mute',1);writes.clear()
assert a.call('NesAudio_SetOutput',1)==0
assert a.call('NesAudio_GetOutput')==1 and a.read8(a.addr('nes_audio_suspended'))==1
assert reg(2)==0 and reg(3)==0x6f and reg(43)==0x10 and reg(49)==2
assert reg(52)&64 and reg(53)&64 and not reg(54)&64 and not reg(55)&64
assert reg(54)&63==reg(55)&63==36 and reg(55)&256
assert writes[0]==(10,64) and reg(10)==64,'Menu route change unmuted codec'
before=len(writes);assert a.call('NesAudio_SetOutput',1)==0 and len(writes)==before
a.call('NesAudio_Mute',0);assert reg(10)==0
assert a.call('NesAudio_SetOutput',0)==0
assert reg(2)==0x180 and reg(3)==15 and reg(43)==0
assert not reg(52)&64 and not reg(53)&64 and reg(54)&64 and reg(55)&64
assert reg(52)&63==reg(53)&63==40 and reg(53)&256
assert a.call('NesAudio_SetOutput',2)==0
assert reg(2)==0 and reg(3)==15 and reg(10)==64
a.call('NesAudio_Mute',1);a.call('NesAudio_Mute',0);assert reg(10)==64
# Silent gameplay drains APU work, but submits zero PCM; loading/menu mute
# continues to bypass the APU entirely (separate DMA regression covers this).
processed=[]
def apu(uc,address,size,data):processed.append(1);ret(uc)
a.u.hook_add(UC_HOOK_CODE,apu,begin=a.addr('apu_process')&~1,end=a.addr('apu_process')&~1)
dest=a.addr('dma_pcm');a.u.mem_write(dest,b'\x55'*1024)
a.u.mem_write(0x40026004,struct.pack('<I',0x10))
a.call('DMA1_Stream4_IRQHandler')
assert len(processed)==1 and bytes(a.u.mem_read(dest,1024))==bytes(1024)
a.call('NesAudio_Mute',1);a.call('DMA1_Stream4_IRQHandler');assert len(processed)==1
assert a.call('NesAudio_SetOutput',1)==0
fail_next[0]=True
assert a.call('NesAudio_SetOutput',0)==1
assert a.call('NesAudio_GetOutput')==2 and a.r32(a.addr('nes_audio_codec_error'))==1
assert reg(2)==0 and reg(3)==15 and reg(10)==64
assert reg(52)&64 and reg(53)&64 and reg(54)&64 and reg(55)&64
assert a.call('NesAudio_SetOutput',1)==0,'Failed switch could not recover'
assert a.call('NesAudio_SetOutput',0)==0
assert a.call('NesAudio_Init')==0 and a.call('NesAudio_GetOutput')==1,'Reinitialisation did not restore speaker default'
assert reg(2)==0 and reg(3)==0x6f and reg(43)==0x10
assert reg(52)&64 and reg(53)&64 and not reg(54)&64 and not reg(55)&64
report={'result':'PASS','hardware_tested':False,'scope':'real ARM route logic, mocked I2C writes',
        'checks':['cold init selects speaker and disables headphones','reinitialisation restores speaker default','exclusive headphones/speaker/off paths','BTL inversion and equal paired volume',
                  'mute before route change','menu/loading mute preserved','silent gameplay drains APU',
                  'invalid/uninitialised selection rejected','failed I2C change mutes both outputs','retry recovers'],
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/audio_output_results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
