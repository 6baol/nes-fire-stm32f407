"""Actual ARM RPG adaptation, GPIO polling, and ROM-CRC profile selection."""
import sys,struct,json,hashlib
from sd_arm_harness import SdArm,ROOT
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0

def main():
    a=SdArm();assert a.boot()==0
    assert a.call('NesLibrary_Load',a.game_index('Just Breed (Japan).nes'))==0
    assert a.call('NesLibrary_InputProfile')==1
    def pad(buttons,x,y):return a.call('NesPort_RpgPad',buttons,x&0xffffffff,y&0xffffffff)
    assert pad(0,0,0)==0
    assert pad(0,800,0)==128 and pad(0,800,700)==128
    assert pad(0,700,800)==128,'diagonal jitter changed axis'
    assert pad(0,600,900)==32 and pad(0,700,800)==32
    assert pad(0,0,0)==0 and pad(0,340,0)==0
    assert pad(0,400,0)==128 and pad(0,240,0)==128 and pad(0,210,0)==0
    assert pad(0,-900,0)==64 and pad(0,900,0)==128,'reversal required recenter'
    for buttons in (1,2,3,8,9,10,11):
        assert pad(buttons,900,900)==buttons,'held stick swallowed action'
    assert pad(0,900,0)==128,'stick did not resume after confirmation release'
    assert pad(4,0,-900)==20,'Select was lost'
    # Actual GPIO reads and original 20ms independent debounce, simulated ADC.
    a.u.hook_del(a.input_hook);a.u.mem_map(0x40000000,0x30000)
    a.u.hook_add(UC_HOOK_CODE,a._skip,begin=a.addr('Joystick_Poll')&~1,end=a.addr('Joystick_Poll')&~1)
    a.u.hook_add(UC_HOOK_CODE,a._skip,begin=a.addr('Touchpad_Poll')&~1,end=a.addr('Touchpad_Poll')&~1)
    def joy(u,*args):u.reg_write(UC_ARM_REG_R0,0x20018000);a._skip(u,*args)
    a.u.hook_add(UC_HOOK_CODE,joy,begin=a.addr('Joystick_Get')&~1,end=a.addr('Joystick_Get')&~1)
    a.u.mem_write(0x20018000,struct.pack('<4H2fBB2x3I',2048,2048,2048,2048,.9,.7,1,1,0,1,0))
    a.u.mem_write(a.addr('app_state'),b'\x01');tick=1000
    def poll(aa,bb,sw):
        nonlocal tick
        a.u.mem_write(0x40020010,struct.pack('<I',bb));a.u.mem_write(0x40020810,struct.pack('<I',aa<<13))
        a.u.mem_write(0x40020410,struct.pack('<I',(not sw)<<7))
        for dt in (1,21):
            tick+=dt;a.u.mem_write(a.addr('uwTick'),struct.pack('<I',tick));a.call('NesPort_Input')
        return a.read8(a.addr('PADdata'))
    assert poll(0,0,0)==128
    assert poll(1,0,0)==1 and poll(0,1,0)==2 and poll(1,1,0)==3
    assert poll(0,0,0)==128
    a.u.mem_write(a.addr('app_state'),b'\x00');assert poll(1,0,0)==0xa1,'RPG shaping leaked into library'
    a.call('NesLibrary_EnterMenu');assert a.call('NesLibrary_Load',5)==0
    assert a.call('NesLibrary_InputProfile')==0,'RPG profile leaked into Castlevania III'
    a.u.mem_write(a.addr('app_state'),b'\x01');assert poll(1,1,0)==0xa3,'native diagonal+A+B changed'
    # Drawing cadence is changed only for the known RPG profile.
    cases=[(3,59000,6500,0,3),(3,59000,6500,1,6),(3,35000,4000,1,3),(3,50000,7000,1,5),(3,0,0,1,3),(20,60000,16000,1,8)]
    for requested,draw,skip,rpg,expected in cases:
        assert a.call('NesPort_RenderDivisor',requested,draw,skip,rpg)==expected
    report={'result':'PASS','hardware_tested':False,'checks':['4-way dominant-axis hysteresis','A/B/Start priority during held stick',
        'no mandatory recenter after confirmation','real GPIO and 20ms debounce','menu bypass','CRC-specific profile and cross-game reset',
        'native diagonal+A+B unchanged','cost-based RPG rendering cadence'],
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT/'Tests/nes_output/rpg_controls_results.json').write_text(json.dumps(report,indent=2))
    print('PASS: RPG controls / native GPIO / profile isolation / cadence')
if __name__=='__main__':main()
