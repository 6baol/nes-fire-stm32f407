"""Test real ARM RC touch driver with simulated TIM2 captures and foreground time."""
from pathlib import Path
p=Path(__file__).with_name('test_nes_input.py')
exec(compile(p.read_text(encoding='utf-8'),str(p),'exec'))
w32(addr('SystemCoreClock'),168000000);w32(0x40023808,5<<10) # APB1=/4
# Neighbouring PA4/PA6 ADC and PA0 KEY1 settings must survive touch init.
w32(0x40020000,(3<<8)|(3<<12));original=r32(0x40020000)
assert r32(0x08000000+(16+28)*4)==addr('TIM2_IRQHandler')
call('Touchpad_Init');assert r32(0x40000028)==23 # TIM2 PSC: 84MHz /24
assert r32(0x40020000)&~(3<<10)==original
state_ptr=call('Touchpad_Get');timer=0x40000000
def state():
 data=u.mem_read(state_ptr,16)
 return dict(zip(['raw','baseline','ready','pressed','samples','errors'],struct.unpack('<HHBB2xII',data)))
clock=0
def capture(value,flag=2):
 global clock
 call('Touchpad_Poll',clock)
 call('Touchpad_Poll',clock+4) # still discharging
 assert (r32(0x40020000)>>10)&3==1
 call('Touchpad_Poll',clock+5)
 assert (r32(0x40020000)>>10)&3==2
 w32(timer+0x34,value);w32(timer+0x10,flag)
 call('TIM2_IRQHandler')
 assert r32(timer+0x0c)==0 and r32(timer+0x20)==0
 call('Touchpad_Poll',clock+6);clock+=10
for v in [500,501,499,502,498,500,500,501,500,499]:capture(v)
assert state()['ready']==1 and 499<=state()['baseline']<=501
assert state()['pressed']==0
capture(535);assert state()['pressed']==0 # measured idle-like noise
capture(560);assert state()['pressed']==1 # first light-touch sample is enough
before=r32(addr('touchpad_press_count'))
for _ in range(10):capture(560)
assert r32(addr('touchpad_press_count'))==before # no repeated edge while held
# Select combines with A+B+Start; no suppression of any physical key.
w32(addr('uwTick'),clock);w32(0x40020810,1<<13);w32(0x40020010,1);w32(0x40020410,0)
call('NesPort_Input');w32(addr('uwTick'),clock+20);call('NesPort_Input')
assert u.mem_read(addr('PADdata'),1)[0]==15
# The input poll progressed the capture state; reinitialize for timeout tests.
call('Touchpad_Init');clock=0
for _ in range(10):capture(500)
capture(700);capture(700);assert state()['pressed']==1
capture(540);assert state()['pressed']==1 # release hysteresis
capture(520);capture(520);assert state()['pressed']==0
capture(535);assert state()['pressed']==0 # below press gate
capture(650);capture(650);assert state()['pressed']==1
# No rising edge: deadline releases a previously held Select instead of hanging.
call('Touchpad_Poll',clock);call('Touchpad_Poll',clock+5)
call('Touchpad_Poll',clock+25);clock+=30
assert state()['pressed']==0 and state()['errors']==1
capture(650);capture(650);assert state()['pressed']==1
capture(650,1);assert state()['pressed']==0 # overflow without an edge releases the key
capture(650);capture(650);assert state()['pressed']==1
call('Touchpad_Poll',clock);call('Touchpad_Poll',clock+5)
w32(timer+0x34,520);w32(timer+0x10,2);call('TIM2_IRQHandler')
w32(timer+0x34,20000);w32(timer+0x10,0x202);call('TIM2_IRQHandler')
call('Touchpad_Poll',clock+6)
assert state()['raw']==520 # later disabled-channel IRQ must not overwrite first edge
assert r32(timer+0x0c)==0 and r32(timer+0x20)==0
report={'result':'PASS' ,'scope':'actual Keil ARM touch driver with simulated GPIO/TIM2, no hardware sensitivity claim','checks':['PA5/TIM2 mapping and APB1 prescaler','neighbour pin preservation','10 sample trimmed calibration','first-sample light-touch press, noise margin and debounced release','Select+A+B+Start coexistence','timeout and overflow release','first-edge IRQ latch survives delayed foreground and later spurious IRQ'],'state':state()}
(out/'touchpad_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
