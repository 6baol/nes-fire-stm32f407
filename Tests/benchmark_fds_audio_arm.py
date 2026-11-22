"""Offline instruction-count/PCM benchmark; does not measure a physical board."""
import json,hashlib,struct,sys
from unicorn import UC_HOOK_CODE
from test_mmc3_arm import NesArm,ROOT

a=NesArm();a.u.mem_write(a.addr('MapperNo'),struct.pack('<I',20));a.call('apu_init')
def w(n,v):a.call('FdsAudio_Apply',n,v)
w(0x4023,3);w(0x4083,128);w(0x4089,128)
for i in range(64):w(0x4040+i,0 if i<32 else 63)
w(0x408a,232);w(0x4080,144);w(0x4080,64|3)
w(0x4084,136);w(0x4084,64|5);w(0x4087,128)
for i in range(32):w(0x4088,1 if i<16 else 7)
w(0x4086,255);w(0x4087,15);w(0x4082,7);w(0x4083,4);w(0x4089,0)
count=[0]
def instruction(uc,address,size,data):count[0]+=1
hook=a.u.hook_add(UC_HOOK_CODE,instruction);pcm=bytearray()
for _ in range(256):pcm.extend(struct.pack('<I',a.call('FdsAudio_Sample',10639131)))
a.u.hook_del(hook)
m=json.loads((ROOT/'Release/manifest.json').read_text(encoding='utf-8-sig'))
report={'version':m['version'],'hardware_tested':False,'scope':'Unicorn ARM instruction count for 256 FDS samples with both envelopes and modulation active; excludes DMA/LCD',
        'samples':256,'arm_instructions':count[0],'instructions_per_sample':count[0]/256,
        'output_sha256':hashlib.sha256(pcm).hexdigest(),
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output'/('fds_audio_bench_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
