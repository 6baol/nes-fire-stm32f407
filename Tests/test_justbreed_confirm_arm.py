"""Real Just Breed name entry: native held-direction+A vs adapted confirmation."""
import sys,hashlib,json
from test_smb3_arm import Smb3Arm,ROOT
sys.path.insert(0,str(ROOT/'tools'));import embed_roms
raw=embed_roms.normalize((ROOT/'Roms/Just Breed (Japan).nes').read_bytes())
a=Smb3Arm();a.u.mem_write(0x6c020000,raw);assert a.call('Nes_Load',0x6c020000,len(raw))==0

def run(obj,n,pad=0):
 obj.u.mem_write(obj.addr('PADdata'),bytes([pad]))
 for i in range(n):obj.call('Nes_Frame',int(i==n-1));obj.call('apu_process',0x6c010000,184)
 assert obj.r32(obj.addr('nes_faults'))==0
run(a,600);run(a,2,1);run(a,60);run(a,12,128)
def name_region(obj):return b''.join(obj.frame[y*256+146:y*256+200] for y in range(80,110))
before_name=name_region(a)
b=Smb3Arm()
for base,size in [(0x20000000,0x20000),(0x10000000,0x10000),(0x6c000000,0x100000)]:b.u.mem_write(base,bytes(a.u.mem_read(base,size)))
run(a,3,129);run(a,30,128);a.save_frame('justbreed_native_stick_confirm')
adapted=b.call('NesPort_RpgPad',129,900,0);assert adapted==1
run(b,3,adapted);run(b,30,128);b.save_frame('justbreed_adapted_stick_confirm')
assert a.frame!=b.frame,'Adaptation made no visible difference in actual name entry'
assert name_region(a)==name_region(b) and name_region(a)!=before_name,'Confirmation character was not preserved'
report={'result':'PASS','scope':'Actual Japanese ROM name-entry comparison: confirmation during held right',
 'native_and_adapted_both_confirmed_in_this_scene':True,'note':'Cursor handling differs. This scene does not reproduce every user-reported missed press.',
 'native_pad':129,'adapted_pad':adapted,'native_frame_sha256':hashlib.sha256(a.frame).hexdigest(),
 'adapted_frame_sha256':hashlib.sha256(b.frame).hexdigest(),'hardware_tested':False,
 'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/justbreed_confirmation_results.json').write_text(json.dumps(report,indent=2));print('PASS: real Just Breed held-stick confirmation comparison')
