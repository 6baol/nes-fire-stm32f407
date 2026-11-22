"""Render the compiled menu via its actual LCD calls; validate display bounds.
LCD commands are replaced by a host RGB565 surface. This is not a board photo.
"""
from pathlib import Path
import struct,json,hashlib,sys
from array import array
from PIL import Image
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_CODE,UC_HOOK_MEM_WRITE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_SP,UC_ARM_REG_PC,UC_ARM_REG_LR

root=Path(__file__).resolve().parents[1]
u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
for a,n in [(0x08000000,0x100000),(0x20000000,0x20000),(0x10000000,0x10000),(0x68000000,0x1000)]:u.mem_map(a,n)
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 e=ELFFile(f)
 for s in e.iter_sections():
  if s['sh_flags']&2 and s['sh_type']!='SHT_NOBITS' and s['sh_size']:u.mem_write(s['sh_addr'],s.data())
 sy={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name}
sd_mode='--sd' in sys.argv
if sd_mode:
 from sd_arm_harness import SdArm,pack_files
 # The titles dictionary would replace filename labels; this test checks the
 # filename path, so the fixture ships without it (TITLES.DB has its own test).
 sd=SdArm({k:v for k,v in pack_files().items() if k!='TITLES.DB'});assert sd.boot()==0
 u=sd.u;sy=sd.symbols;u.mem_map(0x68000000,0x1000)
def r32(p):return struct.unpack('<I',u.mem_read(p,4))[0]
def w32(p,v):u.mem_write(p,struct.pack('<I',v))
stop=0x080ff000;u.mem_write(stop,b'\0\xbe')
fill_stub,open_stub=0x2001d000,0x2001d004
u.mem_write(fill_stub,b'\x70\x47');u.mem_write(open_stub,b'\x70\x47')
w32(sy['lcd_fill_color'],fill_stub|1);w32(sy['lcd_open_window'],open_stub|1)
u.mem_write(sy['LCD_X_LENGTH'],struct.pack('<H',480));u.mem_write(sy['LCD_Y_LENGTH'],struct.pack('<H',800))
surface=array('H',[0])*384000;window=[0,0,0,0,0];rectangles=[];pixels=[0]
regs=(UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)
def rect():
 x,y,w,h=(u.reg_read(r) for r in regs)
 assert 0<w<=480 and 0<h<=800 and x+w<=480 and y+h<=800,(x,y,w,h)
 return x,y,w,h
def fill(uc,a,size,data):
 x,y,w,h=rect();c=r32(u.reg_read(UC_ARM_REG_SP))&65535
 for row in range(y,y+h):surface[row*480+x:row*480+x+w]=array('H',[c])*w
 rectangles.append((x,y,w,h));u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
def opened(uc,a,size,data):
 window[:]=[*rect(),0];u.reg_write(UC_ARM_REG_PC,u.reg_read(UC_ARM_REG_LR))
def pixel(uc,access,a,size,value,data):
 x,y,w,h,offset=window
 assert offset<w*h,('LCD window overflow',window)
 surface[(y+offset//w)*480+x+offset%w]=value&65535;window[4]+=1;pixels[0]+=1
u.hook_add(UC_HOOK_CODE,fill,begin=fill_stub,end=fill_stub)
u.hook_add(UC_HOOK_CODE,opened,begin=open_stub,end=open_stub)
u.hook_add(UC_HOOK_MEM_WRITE,pixel,begin=0x68000002,end=0x68000003)
def call(name,*args):
 u.reg_write(UC_ARM_REG_SP,0x2001fff0);u.reg_write(UC_ARM_REG_LR,stop|1)
 for r,v in zip(regs,args):u.reg_write(r,v)
 for i,v in enumerate(args[4:]):w32(0x2001fff0+i*4,v)
 u.emu_start(sy[name]|1,stop,count=100000000)
 assert u.reg_read(UC_ARM_REG_PC)==stop,'instruction budget exhausted: '+name
 return u.reg_read(UC_ARM_REG_R0)
def save(name):
 rgb=bytearray()
 for c in surface:rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
 Image.frombytes('RGB',(480,800),bytes(rgb)).save(out/name)
def assert_native_cover(filename):
 # Compare every LCD pixel with a single nearest-neighbour sampling pass
 # from the original capture, detecting any lossy intermediate downsample.
 src=Image.open(root/'Assets/posters'/filename).convert('RGB');w,h=src.size
 for y in range(360):
  for x in range(456):
   r,g,b=src.getpixel((x*w//456,y*h//360))
   expected=((r>>3)<<11)|((g>>2)<<5)|(b>>3)
   assert surface[(104+y)*480+12+x]==expected,('cover pixel differs from native capture',filename,x,y)
out=root/'Tests/nes_output';out.mkdir(exist_ok=True)
manifest=json.loads((root/'Roms/roms.json').read_text())['games']
posters={c['file']:c['image'] for c in json.loads((root/'Assets/posters/posters.json').read_text())['covers']}
# sd_name lets a short repo filename ship under its full title.
poster_images={(g.get('sd_name') or g['file']):posters.get(g['file']) for g in manifest}
if sd_mode:
    listed=sd.names()
    expected_names=tuple(name.rsplit('.',1)[0].upper()[:46].rstrip() for name in listed)
    images=[poster_images.get(name) for name in listed]
else:
    expected_names=tuple(g['label'] for g in manifest)
    images=[posters.get(g['file']) for g in manifest]
state=0x2001c000;count=call('NesLibrary_Count')
call('NesMenu_Init',state,count,1,1);call('NesMenu_Draw',state)
save(f'menu_{Path(images[0]).stem}.png')
assert_native_cover(images[0])
assert rectangles.count((0,0,480,800))==1
assert any(surface[y*480+x]==0xfe8b for y in range(550,598) for x in range(24,76)), 'selection cursor missing'
assert count==len(expected_names)
for i,expected in enumerate(expected_names):
 pointer=r32(call('NesLibrary_Game',i))
 assert bytes(u.mem_read(pointer,len(expected)+1))==expected.encode()+b'\0','game name was abbreviated'
for index in range(1,count):
 name=f'menu_{Path(images[index]).stem}.png'
 before=pixels[0];rectangles.clear();call('NesMenu_Move',state,1);call('NesMenu_DrawRows',state);call('NesMenu_DrawCover',state)
 assert (0,0,480,800) not in rectangles,'selection unnecessarily clears whole display'
 assert (118,102,244,364) not in rectangles,'cover border frame must not be drawn'
 save(name);print(name,'LCD pixels',pixels[0]-before)
 assert_native_cover(images[index])
assert struct.unpack('<hhh',u.mem_read(state,6))==(count-1,count,count-3),'last game should scroll into view'
# Native controller diagnostics, including simultaneous B+A and all directions.
call('NesSettings_Draw',1)
call('NesSettings_Update',0,2048,2048,1,1,92);save('settings_idle.png')
call('NesSettings_Audio',1,1,0);save('settings_speaker.png')
call('NesSettings_Audio',2,1,0);save('settings_mute.png')
call('NesSettings_Audio',0,1,0)
call('NesSettings_Update',0xff,3200,900,1,1,142);save('settings_pressed.png')
for x,y in [(104,198),(32,250),(160,250),(104,302),(300,222),(384,222),(56,374),(272,374)]:
 assert surface[y*480+x]==0x31f4,('settings button did not highlight',x,y)
call('NesSettings_Update',0,2048,2048,0,0,0)
for x,y in [(104,198),(32,250),(160,250),(104,302),(300,222),(384,222),(56,374),(272,374)]:
 assert surface[y*480+x]==0x194c,('settings button did not release',x,y)
# Exercise the real app transition: KEY1 opens settings without a ROM load;
# holding SW returns to the same selected game, without running the NES core.
u.mem_map(0x40000000,0x30000)
if not sd_mode:u.mem_map(0xe0000000,0x100000)
def skip(uc,a,size,data):uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
def joystick(uc,a,size,data):
 uc.reg_write(UC_ARM_REG_R0,0x2001b000);skip(uc,a,size,data)
def cap(uc,a,size,data):
 uc.reg_write(UC_ARM_REG_R0,0x2001b080);skip(uc,a,size,data)
def clock(uc,a,size,data):
 uc.reg_write(UC_ARM_REG_R0,168000000);skip(uc,a,size,data)

def i2c(uc,a,size,data):
 uc.reg_write(UC_ARM_REG_R0,0);skip(uc,a,size,data)
def forbidden(uc,a,size,data):raise AssertionError('Settings loaded/ran a ROM')
rom_guard_hooks=[]
for name,hook in [('NesPort_Input',skip),('Joystick_Get',joystick),('Touchpad_Get',cap),
                  ('HAL_RCC_GetHCLKFreq',clock),('HAL_I2C_Master_Transmit',i2c),('HAL_Delay',skip),
                  ('Nes_Load',forbidden),('Nes_Frame',forbidden)]:
 handle=u.hook_add(UC_HOOK_CODE,hook,begin=sy[name]&~1,end=sy[name]&~1)
 if name in ('Nes_Load','Nes_Frame'):rom_guard_hooks.append(handle)
u.mem_write(0x2001b000,struct.pack('<HHHHffBB2xIII',2048,2048,2048,2048,0,0,1,1,0,0,0))
u.mem_write(0x2001b080,bytes(32))
app_menu=sy['menu'];call('NesMenu_Init',app_menu,count,1,1);call('NesMenu_Move',app_menu,1)
u.mem_write(sy['app_state'],b'\0');u.mem_write(sy['menu_armed'],b'\0')
w32(0x40020410,128);w32(0x40020010,0);w32(0x40020810,0)
call('NesApp_Poll')  # release arms menu
w32(0x40020010,1);call('NesApp_Poll')
w32(0x40020010,0);call('NesApp_Poll')
assert bytes(u.mem_read(sy['app_state'],1))==b'\x02','KEY1 did not enter native settings'
call('NesApp_Poll');save('settings_app.png')
w32(sy['nes_audio_ready'],1)
w32(sy['uwTick'],10);call('NesApp_Poll')
w32(sy['uwTick'],70);call('NesApp_Poll')
u.mem_write(0x2001b008,struct.pack('<f',.8));w32(sy['uwTick'],80);call('NesApp_Poll')
assert call('NesAudio_GetOutput')==2,'Settings right from default speaker did not select mute'
w32(sy['uwTick'],90);call('NesApp_Poll')
assert call('NesAudio_GetOutput')==2,'Held Settings stick repeated output choice'
save('settings_app_mute.png')
w32(0x40020410,0);w32(sy['uwTick'],100);call('NesApp_Poll')
w32(sy['uwTick'],1600);call('NesApp_Poll')
assert bytes(u.mem_read(sy['app_state'],1))==b'\0','SW hold did not return to library'
assert struct.unpack('<h',u.mem_read(app_menu,2))[0]==1,'settings lost selected game'
assert call('NesAudio_GetOutput')==2,'Output choice lost when leaving Settings'
# A save error must remain visible even while the stick is calibrating.
old_status=r32(sy['status']);error_text=0x2001c300
u.mem_write(error_text,b'SD SAVE FAILED - CHECK CARD\0');w32(sy['status'],error_text)
u.mem_write(0x2001b010,b'\0\0');call('NesApp_Poll')
assert bytes(u.mem_read(sy['shown_status'],48)).split(b'\0')[0]==b'SD SAVE FAILED - CHECK CARD'
w32(sy['status'],old_status);u.mem_write(0x2001b010,b'\1\1')
# Real app navigation: one step per deflection, stable centre required.
w32(0x40020410,128);w32(0x40020010,0)
def menu_sample(ms,y):
 w32(sy['uwTick'],ms);u.mem_write(0x2001b00c,struct.pack('<f',y));call('NesApp_Poll')
 return struct.unpack('<h',u.mem_read(app_menu,2))[0]
assert menu_sample(1700,0)==1
assert menu_sample(1760,0)==1
assert menu_sample(1800,.8)==2
assert menu_sample(3000,.8)==2,'held stick repeated'
assert menu_sample(3010,.5)==2
assert menu_sample(3020,.7)==2,'threshold noise repeated'
assert menu_sample(3030,-.8)==2,'rebound changed direction without centre'
assert menu_sample(3040,0)==2
assert menu_sample(3070,.8)==2,'brief centre rearmed selection'
assert menu_sample(3080,0)==2
assert menu_sample(3140,0)==2
assert menu_sample(3150,-.8)==1,'new deliberate deflection did not move'
if sd_mode:
 # Now allow the real loader/core and exercise the actual KEY2 -> SD/FDS
 # start -> long-SW return path, including audio arena ownership.
 for handle in rom_guard_hooks:u.hook_del(handle)
 u.mem_write(0x2001b00c,struct.pack('<f',0));w32(0x40020810,1<<13)
 call('NesApp_Poll')
 assert bytes(u.mem_read(sy['app_state'],1))==b'\x01' and bytes(u.mem_read(sy['loaded'],1))==b'\x01'
 assert bytes(u.mem_read(sy['nes_audio_suspended'],1))==b'\0'
 w32(0x40020810,0);w32(0x40020410,0);w32(sy['uwTick'],3200);call('NesApp_Poll')
 w32(sy['uwTick'],4700);call('NesApp_Poll')
 assert bytes(u.mem_read(sy['app_state'],1))==b'\0' and bytes(u.mem_read(sy['loaded'],1))==b'\0'
 assert bytes(u.mem_read(sy['nes_audio_suspended'],1))==b'\x01'
 assert struct.unpack('<h',u.mem_read(app_menu,2))[0]==1
call('NesMenu_Init',state,8,1,1)
for _ in range(7):call('NesMenu_Move',state,1)
assert struct.unpack('<hhh',u.mem_read(state,6))==(7,8,5)
call('NesMenu_Move',state,1);assert struct.unpack('<hh',u.mem_read(state,4))==(0,8)
call('NesMenu_Init',state,0,0,0);call('NesMenu_Draw',state);save('menu_empty.png')
# Unknown image + a long title must use the generic cover and bounded text.
entry=sy['nes_rom_images'];w32(entry,0x2001c100);w32(entry+4,0x2001c180)
if sd_mode:u.mem_write(sy['sd_active'],b'\0')
u.mem_write(0x2001c100,b'A VERY LONG GAME TITLE FOR THE FUTURE\0')
u.mem_write(0x2001c180,b'unknown.nes\0')
call('NesMenu_Init',state,1 if sd_mode else count,1,1);call('NesMenu_Draw',state);save('menu_unknown.png')
# A real 8x8 glyph must enlarge only by integer pixel replication. Lowercase
# is normalized, and the LCD never receives writes beyond the right edge.
glyph_at=0x2001c200;u.mem_write(glyph_at,b'Aa\0')
call('PixelFont_Text',8,8,glyph_at,0xffdf,0x0865,1)
base=[[surface[(8+y)*480+8+x] for x in range(8)] for y in range(8)]
assert any(v==0xffdf for row in base for v in row)
assert all(surface[(8+y)*480+16+x]==base[y][x] for y in range(8) for x in range(8))
u.mem_write(glyph_at,b'A\0')
for scale in (2,3):
 call('PixelFont_Text',8,8,glyph_at,0xffdf,0x0865,scale)
 assert all(surface[(8+y)*480+8+x]==base[y//scale][x//scale]
            for y in range(8*scale) for x in range(8*scale))
before=pixels[0];call('PixelFont_Text',479,8,glyph_at,0xffdf,0x0865,1)
assert pixels[0]==before
report={'result':'PASS','scope':'actual Keil menu/LCD glyph code under Unicorn, not board LCD capture',
 'checks':['all LCD rectangles bounded','all pixel streams bounded','three games without controller ROM','full game names','selection redraw avoids full clear','wrap/scroll','zero games','unknown cover and long title','8x8 font scaling','native settings button highlight/release','KEY1 opens settings without loading ROM','SW hold returns to same game','one selection per deflection; no hold/noise/rebound repeat','60ms stable centre rearm','all three covers match native source pixel for pixel after one scaling pass'],
 'axf_sha256':hashlib.sha256((root/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
report['storage']='ARM FatFs / synthetic FAT32' if sd_mode else 'embedded regression'
report['checks'].append('Settings output selector, no hold-repeat, choice retained on return')
report['checks'].append('save failure remains visible over stick calibration hint')
if sd_mode:report['checks'].append('actual KEY2 -> SD/FDS start and long SW return with audio pause/resume')
(out/'menu_visual_results.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print('PASS: LCD bounds, artwork, navigation and fallbacks; rendered to',out)
