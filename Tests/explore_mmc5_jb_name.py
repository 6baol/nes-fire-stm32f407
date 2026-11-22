import sys
sys.path[:0]=['Tests','tools']
from test_smb3_arm import Smb3Arm,ROOT
import embed_roms
a=Smb3Arm();d=embed_roms.normalize((ROOT/'Roms/Just Breed (Japan).nes').read_bytes());a.u.mem_write(0x6c020000,d);a.call('Nes_Load',0x6c020000,len(d));frame=0

def run(n,pad=0,label=None):
 global frame
 a.u.mem_write(a.addr('PADdata'),bytes([pad]))
 for i in range(n):
  a.call('Nes_Frame',int(i==n-1 and bool(label)));a.call('apu_process',0x6c010000,184);frame+=1
 assert a.r32(a.addr('nes_faults'))==0
 if label:a.save_frame('mmc5_jb_'+label);print(label,frame,hex(a.pc()),len(set(a.frame)),flush=True)
run(600,label='filemenu');run(2,1);run(60,label='nameentry')
for i in range(8):run(2,1);run(10)
run(30,label='namefilled');run(2,8);run(60,label='name_start')
run(2,1);run(600,label='opening');run(2,1);run(600,label='opening2')

for n in range(12):
 run(2,8);run(2,1);run(300,label='introstep'+str(n))
