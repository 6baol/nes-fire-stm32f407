"""Validate APU waveform, stereo transport, and Mario PCM using the built ARM core."""
from pathlib import Path
import math,json,struct,hashlib,wave
source=Path(__file__).with_name('test_nes_arm.py')
exec(compile(source.read_text(encoding='utf-8').split("rom=(root/'Roms/controller_test.nes')")[0],str(source),'exec'))
rom=(root/'Roms/controller_test.nes').read_bytes();test_addr=0x080d0000;u.mem_write(test_addr,rom)
assert call('Nes_Load',test_addr,len(rom))==0
scratch=0x6c080000
call('Apu_Write4015',1,0x4015)
for value,address in [(0xbf,0x4000),(8,0x4001),(253,0x4002),(8,0x4003)]:call('Apu_Write',value,address)
pcm=bytearray()
for _ in range(16):call('apu_process',scratch,256);pcm.extend(u.mem_read(scratch,256))
centred=[v-128 for v in pcm]
cross=sum(a<=0<b for a,b in zip(centred,centred[1:]));hz=cross*11025/len(pcm)
assert 420<hz<460,(hz,min(pcm),max(pcm))
u.mem_map(0x40000000,0x30000)
w32(0x40026004,0x10) # DMA1 half-transfer interrupt
call('DMA1_Stream4_IRQHandler')
stereo=struct.unpack('<512h',u.mem_read(addr('dma_pcm'),1024))
assert stereo[::2]==stereo[1::2] and max(stereo)-min(stereo)>1000
assert max(map(abs,stereo))<=16384
assert r32(0x08000000+(16+15)*4)==addr('DMA1_Stream4_IRQHandler')
call('apu_reset');before=r32(addr('nes_apu_queue_drops'))
for _ in range(300):call('Apu_Write',0x3f,0x4000)
assert r32(addr('nes_apu_queue_drops'))-before==45
# Consume the actual embedded Mario ROM and start via the emulated controller.
if 'nes_rom_images' in symbols:
 mario=r32(addr('nes_rom_images')+8);size=r32(addr('nes_rom_images')+12)
else:
 mario=addr('nes_rom');size=r32(addr('nes_rom_size'))
assert call('Nes_Load',mario,size)==0
music=bytearray()
for frame_no in range(260):
 u.mem_write(addr('PADdata'),bytes([8 if 90<=frame_no<94 else 0]))
 call('Nes_Frame',0)
 samples=(frame_no+1)*11025//60-frame_no*11025//60
 call('apu_process',scratch,samples)
 music.extend(u.mem_read(scratch,samples))
assert r32(addr('nes_faults'))==0
assert r32(addr('nes_apu_queue_drops'))==0
assert len(set(music))>16 and max(music)-min(music)>32
with wave.open(str(out/'mario_apu_arm.wav'),'wb') as f:
 f.setnchannels(1);f.setsampwidth(1);f.setframerate(11025);f.writeframes(music)
report={'result':'PASS','tone_hz':hz,'stereo_identical':True,'pcm_range':[min(music),max(music)],'mario_frames':260,'apu_queue_drops':0,'cpu_faults':0,'scope':'actual ARM APU and CPU under Unicorn; codec audibility needs board test','bin_sha256':hashlib.sha256((root/'Release'/(json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))['firmware_prefix']+'.bin')).read_bytes()).hexdigest()}
(out/'audio_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
