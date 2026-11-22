"""User games through actual ARM FatFs/CRC/preload. No physical SD I/O."""
import sys,json,hashlib,wave
from sd_arm_harness import SdArm,ROOT,pack_files
sys.path.insert(0,str(ROOT/'tools'));import embed_roms
files=pack_files();names=["Castlevania III - Dracula's Curse (USA).nes",'Just Breed (Japan).nes']
for i,name in enumerate(names):
 raw=embed_roms.normalize((ROOT/'Roms'/name).read_bytes());files[f'MMC5{i}.NES']=raw
results=[]
for index,name in enumerate(names):
 if len(sys.argv)>1 and index!=int(sys.argv[1]):continue
 a=SdArm(files);assert a.boot()==0 and a.call('NesLibrary_Load',a.game_index(f'MMC5{index}.NES'))==0
 slug='cv3' if index==0 else 'justbreed';frames=0;pcm=bytearray();snapshots=[]
 initial_reads=a.blocks_read;raw=files[f'MMC5{index}.NES'];assert bytes(a.u.mem_read(0x6c020000,len(raw)))==raw
 def run(n,pad=0,label=None):
  global frames
  a.u.mem_write(a.addr('PADdata'),bytes([pad]))
  for j in range(n):
   a.frame_no=frames;a.call('Nes_Frame',int(j==n-1 and bool(label)))
   samples=(frames+1)*11025//60-frames*11025//60;frames+=1
   a.call('apu_process',0x6c010000,samples);pcm.extend(a.u.mem_read(0x6c010000,samples))
  assert a.r32(a.addr('nes_faults'))==0 and a.r32(a.addr('nes_apu_queue_drops'))==0
  assert a.blocks_read==initial_reads and a.blocks_written==0
  if label:
   a.save_frame('mmc5_'+slug+'_'+label);snapshots.append(label)
   print(slug,label,frames,'colors',len(set(a.frame)),flush=True)
 def oam():
  p=a.r32(a.addr('spr_ram'));d=bytes(a.u.mem_read(p,256));return [[i,*d[i*4:i*4+4]] for i in range(64) if 24<d[i*4]<230]
 if index==0:
  run(360);run(4,8);run(120,label='title');assert len(set(a.frame))>=10
  run(4,8);run(180,label='nameentry');run(4,8);run(1000,label='stage1');assert len(set(a.frame))>=10
  def hero():return [r for r in oam() if (r[3]&3)==0 and r[4]<128 and r[1]>64]
  before=hero();run(30,128,'move');after=hero()
  x0=sum(r[4] for r in before)/len(before);x1=sum(r[4] for r in after)/len(after)
  assert x1>x0+15,('CV3 did not move',x0,x1)
  ground=min(r[1] for r in after);run(1);run(16,1,'jump')
  assert min(r[1] for r in hero())<ground-12,'CV3 A did not lift the player'
 else:
  run(600,label='filemenu');run(2,1);run(60,label='nameentry')
  for j in range(8):run(2,1);run(10)
  run(30);run(2,8);run(60);run(2,1);run(600,label='introtext');run(2,1);run(600)
  for j in range(12):run(2,8);run(2,1);run(300,label='intro'+str(j))
  assert len(set(a.frame))>=7,'intro did not reach the town scene'
  before=oam();run(24,128,'move');after=oam();print('JB OAM',before,after,flush=True)
  run(2,1);run(60,label='town')
 with wave.open(str(ROOT/'Tests/nes_output'/('mmc5_'+slug+'_audio.wav')),'wb') as w:
  w.setnchannels(1);w.setsampwidth(1);w.setframerate(11025);w.writeframes(pcm)
 assert max(pcm)-min(pcm)>20
 # Rendering / tile decoding / diagnostics must never change the ROM payload.
 assert bytes(a.u.mem_read(0x6c020000,len(raw)))==raw
 if index==1:
  sram=a.r32(a.addr('NES_SRAM'));saved=bytes(a.u.mem_read(sram,8192))
  assert a.call('NesLibrary_Save')==0 and a.blocks_written>0
  assert a.boot()==0 and a.call('NesLibrary_Load',a.game_index(f'MMC5{index}.NES'))==0
  assert bytes(a.u.mem_read(sram,8192))==saved and a.r32(a.addr('nes_sd_save_restores'))>=1
 expansion_writes=sum(0x5000<=ad<=0x5015 for _,ad,v in a.apu_log)
 if index==1:assert expansion_writes>100
 results.append({'file':name,'frames':frames,'snapshots':snapshots,'pcm_range':[min(pcm),max(pcm)],'expansion_audio_writes':expansion_writes,'cpu_faults':0,'apu_queue_drops':0,'no_sd_io_during_game':True,'rom_payload_unchanged':True,'sram_cold_restore':index==1})
if len(sys.argv)>1:
 old=json.loads((ROOT/'Tests/nes_output/mmc5_games_sd_results.json').read_text())
 assert old['axf_sha256']==hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()
 results=results+[g for g in old['games'] if g['file'] not in [r['file'] for r in results]]
report={'result':'PASS','hardware_tested':False,'games':results,'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/mmc5_games_sd_results.json').write_text(json.dumps(report,indent=2))
