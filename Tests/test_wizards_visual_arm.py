"""Consecutive HUD/scroll regression for the user's Wizards video defect."""
import hashlib,json
from test_smb3_arm import Smb3Arm,ROOT,PCM_SCRATCH

a=Smb3Arm();assert a.load((ROOT/'Roms/Wizards & Warriors (U).nes').read_bytes())==0
def run(n,pad=0):
    a.u.mem_write(a.addr('PADdata'),bytes([pad]))
    for _ in range(n):a.call('Nes_Frame',0);a.call('apu_process',PCM_SCRATCH,184)
run(360);run(4,8);run(120);run(4,8);run(720)
regions=[(0x20000000,0x20000),(0x10000000,0x10000),(0x6c000000,0x100000)]
memory=[bytes(a.u.mem_read(base,size)) for base,size in regions];ctx=a.u.context_save()
states={};reference=None;drawn=0
for mode,count in [('draw',120),('skip',120),('third',360)]:
    for (base,size),data in zip(regions,memory):a.u.mem_write(base,data)
    a.u.context_restore(ctx);rows=[]
    for f in range(count):
        draw=mode=='draw' or (mode=='third' and f%3==0)
        a.call('Nes_Frame',int(draw));a.call('apu_process',PCM_SCRATCH,184)
        ram=a.r32(a.addr('NES_RAM'))
        rows.append((hashlib.sha256(a.u.mem_read(ram,2048)).hexdigest(),a.pc()))
        assert a.r32(a.addr('nes_faults'))==a.r32(a.addr('nes_apu_queue_drops'))==0
        if draw:
            # LIFE / EVIL / SCORE labels must stay in the bottom HUD on every
            # submitted frame. The old code alternated with forest tiles here.
            labels=tuple(a.palette[a.frame[y*256+x]&63]
                         for left,right in [(8,40),(56,96),(192,240)]
                         for y in range(192,208) for x in range(left,right))
            if reference is None:
                reference=labels
                assert len(set(labels))>=4,'HUD labels missing in reference frame'
            assert labels==reference,('HUD/scroll jumped on a consecutive frame',mode,f)
            drawn+=1
    states[mode]=rows
    print('PASS',mode,count,'frames',flush=True)
assert states['draw']==states['skip']==states['third'][:120],'LCD frame skipping changed CPU execution'
report={'result':'PASS','hardware_tested':False,'scope':'real ARM CPU/PPU, consecutive Wizards HUD/scroll check',
        'full_draw_frames':120,'skipped_frames':120,'one_in_three_logic_frames':360,
        'hud_frames_checked':drawn,'draw_skip_cpu_ram_pc_match':True,
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/wizards_hud_labels.json').write_text(json.dumps(list(reference)))
(ROOT/'Tests/nes_output/wizards_visual_results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
