"""Exercise actual ARM input polling with simulated GPIO and debounce time."""
from pathlib import Path
import json,hashlib
source=Path(__file__).with_name('test_nes_arm.py')
exec(compile(source.read_text(encoding='utf-8').split("rom=(root/'Roms/controller_test.nes')")[0],str(source),'exec'))
u.hook_del(input_hook)
u.mem_map(0x40000000,0x30000)
# Keep real GPIO reads and debounce. Only ADC servicing/state are stubbed.
u.hook_add(UC_HOOK_CODE,skip,begin=addr('Joystick_Poll')&~1,end=addr('Joystick_Poll')&~1)
def joy(uc,a,size,data):
 uc.reg_write(UC_ARM_REG_R0,0x20018000);skip(uc,a,size,data)
u.hook_add(UC_HOOK_CODE,joy,begin=addr('Joystick_Get')&~1,end=addr('Joystick_Get')&~1)
tick=0
samples=[]
def poll(a,b,start,delay):
 global tick
 tick+=delay;w32(addr('uwTick'),tick)
 w32(0x40020010,int(b)) # KEY1=PA0
 w32(0x40020810,int(a)<<13) # KEY2=PC13
 w32(0x40020410,int(not start)<<7) # SW=PB7 active low
 call('NesPort_Input');return u.mem_read(addr('PADdata'),1)[0]
def stable(a,b,start,expected):
 poll(a,b,start,1);pad=poll(a,b,start,20)
 assert pad==expected,(a,b,start,hex(pad),hex(expected))
 samples.append({'A':a,'B':b,'Start':start,'pad':pad})
# B held, A pressed/released: acceleration must remain active throughout jump.
stable(0,0,0,0);stable(0,1,0,2)
assert poll(1,1,0,1)==2 # debounce does not drop B
assert poll(1,1,0,19)==2
assert poll(1,1,0,1)==3 # combined A+B, never Select
stable(0,1,0,2);stable(0,0,0,0)
# Also check reverse order and all simultaneous button combinations.
stable(1,0,0,1);stable(1,1,0,3)
for mask in range(8):stable(mask&1!=0,mask&2!=0,mask&4!=0,(mask&3)|((mask&4)<<1))
report={'result':'PASS','scope':'actual Keil NesPort_Input with real GPIO reads and real 20ms debounce, simulated ADC state','cases':samples,'axf_sha256':hashlib.sha256((root/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(out/'input_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('PASS: B held + A press/release; reverse order; all A/B/Start combinations; no accidental Select')
