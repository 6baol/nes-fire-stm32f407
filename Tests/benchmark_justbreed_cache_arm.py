"""Old/new ARM core frame cost and exact gameplay/render equivalence; excludes physical LCD waits."""
import sys,json,hashlib
from pathlib import Path
from unittest.mock import patch
from unicorn import UC_HOOK_CODE
from test_smb3_arm import Smb3Arm,ROOT
sys.path.insert(0,str(ROOT/'tools'));import embed_roms
raw=embed_roms.normalize((ROOT/'Roms/Just Breed (Japan).nes').read_bytes());original_open=Path.open

def execute(axf,label):
 def redirected(path,*args,**kwargs):
  if path.resolve()==(ROOT/'Project/Output/Fire_F407ZG.axf').resolve():return original_open(axf,*args,**kwargs)
  return original_open(path,*args,**kwargs)
 with patch.object(Path,'open',redirected):a=Smb3Arm()
 a.u.mem_write(0x6c020000,raw);assert a.call('Nes_Load',0x6c020000,len(raw))==0
 frames=0
 def run(n,pad=0,draw=False):
  nonlocal frames
  a.u.mem_write(a.addr('PADdata'),bytes([pad]))
  for i in range(n):a.call('Nes_Frame',int(draw and i==n-1));a.call('apu_process',0x6c010000,184);frames+=1
 run(600);run(2,1);run(60)
 for i in range(8):run(2,1);run(10)
 run(30);run(2,8);run(60);run(2,1);run(600);run(2,1);run(600)
 for i in range(4):run(2,8);run(2,1);run(300,draw=True)
 count=[0,0]
 def instruction(u,ad,size,data):
  count[0]+=1
  if ad==(a.addr('compile')&~1):count[1]+=1
 hook=a.u.hook_add(UC_HOOK_CODE,instruction,begin=0x08000000,end=0x080fffff)
 run(1,draw=True);a.u.hook_del(hook)
 assert a.r32(a.addr('nes_faults'))==0
 a.save_frame('justbreed_cache_'+label)
 result={'label':label,'frames':frames,'arm_instructions':count[0],'tile_compiles':count[1],
 'frame_sha256':hashlib.sha256(a.frame).hexdigest(),'ram_sha256':hashlib.sha256(bytes(a.u.mem_read(a.r32(a.addr('NES_RAM')),2048))).hexdigest(),
 'sram_sha256':hashlib.sha256(bytes(a.u.mem_read(a.r32(a.addr('NES_SRAM')),8192))).hexdigest(),'cpu_pc':a.pc(),
 'axf_sha256':hashlib.sha256(axf.read_bytes()).hexdigest()}
 print(json.dumps(result),flush=True);return result
old=execute(ROOT/'Release/NesFire_v0.19-mmc5-preview.axf','v019')
new=execute(ROOT/'Project/Output/Fire_F407ZG.axf','v0191')
for key in ['frame_sha256','ram_sha256','sram_sha256','cpu_pc']:assert old[key]==new[key],key
assert new['arm_instructions']<old['arm_instructions'] and new['tile_compiles']<old['tile_compiles']
report={'result':'PASS','scope':'Actual ARM core for one rendered Just Breed town frame; excludes physical LCD wait and input adaptation',
 'old':old,'new':new,'instruction_reduction_percent':100*(1-new['arm_instructions']/old['arm_instructions']),
 'frame_ram_sram_pc_identical':True,'hardware_tested':False}
(ROOT/'Tests/nes_output/justbreed_cache_benchmark.json').write_text(json.dumps(report,indent=2))
