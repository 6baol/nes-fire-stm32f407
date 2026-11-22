"""Capture consecutive Wizards frames and PPU writes on the actual ARM core."""
import json,struct,hashlib,sys
from PIL import Image,ImageDraw
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1
from test_smb3_arm import Smb3Arm,ROOT,PCM_SCRATCH

a=Smb3Arm();assert a.load((ROOT/'Roms/Wizards & Warriors (U).nes').read_bytes())==0
prerender='--prerender' in sys.argv
out=ROOT/('Tests/nes_output/wizards_visual_prerender' if prerender else 'Tests/nes_output/wizards_visual');out.mkdir(exist_ok=True)
if prerender:
    def clear_prerender(uc,address,size,data):
        if a.r32(a.addr('NES_scanline'))==261:
            p=a.r32(a.addr('ppu'));uc.mem_write(p,b'\0'*4)
            uc.mem_write(p+24,bytes([a.read8(p+24)&0x1f]))
    a.u.hook_add(UC_HOOK_CODE,clear_prerender,begin=a.addr('run6502')&~1,end=a.addr('run6502')&~1)
frame=0;trace=[]
def writes(uc,address,size,data):
    port=uc.reg_read(UC_ARM_REG_R1)&7
    if port in (0,1,5,6):
        trace.append([frame,a.r32(a.addr('NES_scanline')),port,uc.reg_read(UC_ARM_REG_R0)&255])
a.u.hook_add(UC_HOOK_CODE,writes,begin=a.addr('PPU_WriteToPort')&~1,end=a.addr('PPU_WriteToPort')&~1)
def run(n,pad=0,draw=0):
    global frame
    a.u.mem_write(a.addr('PADdata'),bytes([pad]))
    for _ in range(n):
        a.call('Nes_Frame',draw);a.call('apu_process',PCM_SCRATCH,184);frame+=1
run(360);run(4,8);run(120);run(4,8);run(720)
regions=[(0x20000000,0x20000),(0x10000000,0x10000),(0x6c000000,0x100000)]
memory=[bytes(a.u.mem_read(base,size)) for base,size in regions];ctx=a.u.context_save();base_frame=frame
results={}
for mode in ('draw','skip','third'):
    for (base,size),content in zip(regions,memory):a.u.mem_write(base,content)
    a.u.context_restore(ctx);frame=base_frame;trace.clear();rows=[];tiles=[]
    for f in range(36):
        drawn=mode=='draw' or (mode=='third' and f%3==0)
        run(1,draw=int(drawn));p=a.r32(a.addr('ppu'));ram=a.r32(a.addr('NES_RAM'))
        rows.append({'frame':frame,'pc':a.pc(),'ppu':bytes(a.u.mem_read(p,64)).hex(),
                     'ram_sha256':hashlib.sha256(a.u.mem_read(ram,2048)).hexdigest()})
        if drawn and len(tiles)<12:
            rgb=bytearray()
            for v in a.frame:
                c=a.palette[v&63];rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
            im=Image.frombytes('RGB',(256,240),bytes(rgb));im.save(out/f'{mode}_{f:02d}.png');tiles.append((f,im))
    results[mode]={'states':rows,'writes':trace.copy()}
    if tiles:
        sheet=Image.new('RGB',(4*256,3*264));d=ImageDraw.Draw(sheet)
        for i,(f,im) in enumerate(tiles):x=i%4*256;y=i//4*264;sheet.paste(im,(x,y+24));d.text((x,y+4),str(f),fill='white')
        sheet.save(out/f'{mode}_contact.png')
    print(mode,[(r['frame'],hex(r['pc']),r['ppu'][:48]) for r in rows[:4]],flush=True)
(out/'trace.json').write_text(json.dumps(results,indent=2))
print('draw/skip same RAM frames:',sum(x['ram_sha256']==y['ram_sha256'] for x,y in zip(results['draw']['states'],results['skip']['states'])))
