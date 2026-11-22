"""Temporary RAM-only render stress scenes; restore the user's game afterwards."""
from pathlib import Path
import ctypes as C
import json
import sys
import time
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

class Bullet(C.Structure):
    _fields_=[('x',C.c_float),('y',C.c_float),('vx',C.c_float),('vy',C.c_float),
              ('active',C.c_uint8),('kind',C.c_uint8),('radius',C.c_uint8)]
class Enemy(C.Structure):
    _fields_=[('x',C.c_float),('y',C.c_float),('hp',C.c_uint16),('age',C.c_uint16),('active',C.c_uint8)]
class Game(C.Structure):
    _fields_=[('mode',C.c_uint8),('tick',C.c_uint32),('score',C.c_uint32),('dropped',C.c_uint32),
              ('px',C.c_float),('py',C.c_float),('bx',C.c_float),('invincible',C.c_uint16),
              ('flash',C.c_uint16),('hp',C.c_uint16),('lives',C.c_uint8),('bombs',C.c_uint8),
              ('slow',C.c_uint8),('boss',C.c_uint8),('bullets',Bullet*256),('shots',Bullet*64),('enemies',Enemy*12)]

root=Path(__file__).resolve().parents[1]
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    tab=ELFFile(f).get_section_by_name('.symtab')
    symbols={s.name:(s['st_value'],s['st_size']) for s in tab.iter_symbols() if s.name}
assert C.sizeof(Game)==symbols['game'][1]==6632
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
options={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,
         'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False}
reports=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=options) as session:
    t=session.target;t.halt();address=symbols['game'][0];ma=symbols['metrics'][0]
    saved=bytes(t.read_memory_block8(address,C.sizeof(Game)))
    try:
        for count in [0,128,256]:
            scene=Game();scene.mode=2;scene.tick=1000 if count else 10
            scene.px=240;scene.py=724;scene.bx=240;scene.invincible=60000
            scene.hp=900;scene.lives=3;scene.bombs=2;scene.boss=count!=0
            for i in range(count):
                b=scene.bullets[i];b.x=14+(i*37)%450;b.y=90+(i*53)%430
                b.vy=30;b.active=1;b.radius=4;b.kind=i%3
            t.write_memory_block8(address,bytes(scene));t.write_memory_block8(ma,bytes(24));t.resume()
            time.sleep(4)
            t.halt();data=bytes(t.read_memory_block8(ma,24))
            import struct
            values=struct.unpack('<6I',data)
            current=Game.from_buffer_copy(bytes(t.read_memory_block8(address,C.sizeof(Game))))
            report=dict(requested_bullets=count,mode=current.mode,game_tick=current.tick,
                        active_bullets=sum(bool(b.active) for b in current.bullets),
                        **dict(zip(['fps','render_us','render_max_us','logic_max_us','overruns','fill_us'],values)))
            reports.append(report);print(json.dumps(report),flush=True)
    finally:
        t.write_memory_block8(address,saved);t.resume()
destination=root/'Release'/('performance_'+(sys.argv[1] if len(sys.argv)>1 else 'current')+'.json')
destination.write_text(json.dumps(reports,indent=2),encoding='utf-8')
print('Saved',destination,flush=True)
