"""Real ARM frame scheduler must retain 60 Hz under bursty display work."""
from pathlib import Path
source=Path(__file__).with_name('test_nes_arm.py')
exec(compile(source.read_text(encoding='utf-8').split("rom=(root/'Roms/controller_test.nes')")[0],str(source),'exec'))
clock=[0];hclk=168000000;end=2*hclk
w32(addr('SystemCoreClock'),hclk);u.mem_write(addr('loaded'),b'\x01');u.mem_write(addr('app_state'),b'\x01')
w32(addr('stats_due'),10000)
u.mem_map(0x40000000,0x30000);w32(0x40020410,1<<7) # SW released; KEY1/KEY2 released.
def joy(uc,a,size,data):uc.reg_write(UC_ARM_REG_R0,0x20018000);skip(uc,a,size,data)
def frame_cost(uc,a,size,data):
 clock[0]+=hclk*(35 if uc.reg_read(UC_ARM_REG_R0) else 2)//1000
 w32(0xe0001004,clock[0]);skip(uc,a,size,data)
u.hook_add(UC_HOOK_CODE,joy,begin=addr('Joystick_Get')&~1,end=addr('Joystick_Get')&~1)
u.hook_add(UC_HOOK_CODE,skip,begin=addr('LCD_DispString_EN')&~1,end=addr('LCD_DispString_EN')&~1)
u.hook_add(UC_HOOK_CODE,skip,begin=addr('PixelFont_Text')&~1,end=addr('PixelFont_Text')&~1)
u.hook_add(UC_HOOK_CODE,frame_cost,begin=addr('Nes_Frame')&~1,end=addr('Nes_Frame')&~1)
while clock[0]<end:
 w32(0xe0001004,clock[0]);w32(addr('uwTick'),clock[0]//(hclk//1000));call('NesApp_Poll')
 clock[0]+=hclk//10000
frames=r32(addr('nes_logic_total'));draw=r32(addr('nes_draw_total'));drops=r32(addr('nes_clock_drops'))
assert 119<=frames<=121 and 39<=draw<=41 and drops==0,(frames,draw,drops)
print('PASS: real ARM scheduler retains ~60 logic Hz /20 render Hz with 35ms display frames, no clock drops:',frames,draw)
