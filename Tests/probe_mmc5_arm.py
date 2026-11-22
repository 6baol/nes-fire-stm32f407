"""Offline MMC5 game exploration; snapshots are not automatic acceptance."""
import sys,json
from test_smb3_arm import Smb3Arm,ROOT,OUT
sys.path.insert(0,str(ROOT/'tools'))
import embed_roms
name=sys.argv[1] if len(sys.argv)>1 else "Castlevania III - Dracula's Curse (USA).nes"
slug='mmc5_cv3' if name.startswith('Castlevania') else 'mmc5_justbreed'
a=Smb3Arm();raw=embed_roms.normalize((ROOT/'Roms'/name).read_bytes())
assert embed_roms.validate(raw)==5
a.u.mem_write(0x6c020000,raw);assert a.call('Nes_Load',0x6c020000,len(raw))==0
frames=0
for n,pad,label in [(60,0,'boot60'),(120,0,'boot180'),(180,0,'boot360'),(4,8,'start1'),(120,0,'after1'),(4,8,'start2'),(180,0,'after2'),(4,8,'start3'),(180,0,'after3'),(600,0,'wait1452'),(4,1,'a1'),(180,0,'aftera1'),(4,8,'start4'),(300,0,'after4'),(4,1,'a2'),(300,0,'aftera2'),(60,128,'right'),(16,1,'jump')]:
 a.u.mem_write(a.addr('PADdata'),bytes([pad]))
 for i in range(n):
  a.frame_no=frames;a.call('Nes_Frame',int(i==n-1));a.call('apu_process',0x6c010000,184);frames+=1
 a.save_frame(slug+'_'+label)
 print(slug,label,frames,'PC',hex(a.pc()),'faults',a.r32(a.addr('nes_faults')),'drops',a.r32(a.addr('nes_apu_queue_drops')),'colors',len(set(a.frame)),flush=True)
 if a.r32(a.addr('nes_faults')):break
