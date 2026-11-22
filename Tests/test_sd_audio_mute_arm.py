"""DMA rendering must not touch the APU/ROM while the library reloads SRAM."""
from test_mmc3_arm import NesArm
from unicorn import UC_HOOK_CODE
a=NesArm();calls=[]
def process(uc,address,size,data):
    assert a.read8(a.addr('nes_audio_suspended'))==0,'APU used a menu/loading ROM'
    calls.append(1)
a.u.hook_add(UC_HOOK_CODE,process,begin=a.addr('apu_process')&~1,end=a.addr('apu_process')&~1)
a.call('apu_init');a.u.mem_write(a.addr('nes_audio_ready'),bytes(4))
a.u.mem_map(0x40000000,0x30000)
a.u.mem_write(0x40026004,(0x10).to_bytes(4,'little')) # actual DMA half-transfer path
a.u.mem_write(a.addr('dma_pcm'),b'\x55'*1024)
a.call('NesAudio_Mute',1);a.call('DMA1_Stream4_IRQHandler')
assert bytes(a.u.mem_read(a.addr('dma_pcm'),1024))==bytes(1024) and not calls
a.call('NesAudio_Mute',0);a.call('DMA1_Stream4_IRQHandler')
assert len(calls)==1
print('PASS: muted DMA outputs zero without processing APU/ROM; unmute resumes APU')
