"""User-provided Metroid / Wizards & Warriors, actual ARM core, no board."""
import hashlib,json,wave
from test_smb3_arm import Smb3Arm,PCM_SCRATCH,ROOT,OUT

def run_game(filename,slug):
    raw=(ROOT/'Roms'/filename).read_bytes();a=Smb3Arm();assert a.load(raw)==0
    pcm=bytearray();frames=0
    def run(n,name=None,pad=0):
        nonlocal frames
        a.u.mem_write(a.addr('PADdata'),bytes([pad]))
        for i in range(n):
            a.frame_no=frames;a.call('Nes_Frame',int(i==n-1 and name is not None))
            samples=(frames+1)*11025//60-frames*11025//60;frames+=1
            a.call('apu_process',PCM_SCRATCH,samples)
            pcm.extend(a.u.mem_read(PCM_SCRATCH,samples))
        assert a.r32(a.addr('nes_faults'))==0,(slug,frames,'CPU fault')
        if name:a.save_frame(slug+'_'+name);print(slug,frames,name,hex(a.pc()),len(set(a.frame)),flush=True)
    for i in range(1,7):run(60,'boot_'+str(i))
    run(4,pad=8);run(120,'start')
    run(4,pad=8);run(120,'start2')
    # Jump soon after the opening scene settles, before the first encounter
    # can hit Kuros and hide his OAM sprites during damage blinking.
    run(420 if slug=='wizards' else 360,'ready')
    oam=a.r32(a.addr('spr_ram'))
    ram=a.r32(a.addr('NES_RAM'))
    # Player sprites occupy slots 8..15 in this Metroid scene and 1..10 in
    # this Wizards scene. Compare actual OAM geometry, not an assumed common
    # game-RAM layout. Metroid's $52 is Samus screen Y (disassembly reference).
    player=slice(32,64) if slug=='metroid' else slice(4,44)
    def geometry():
        data=bytes(a.u.mem_read(oam,256))[player]
        return min(data[0::4]),sum(data[3::4])/len(data[3::4])
    initial_ground=geometry()[0]
    initial_jump=[]
    for i in range(12):
        run(1,'initial_jump' if i==11 else None,1)
        initial_jump.append(geometry()[0])
    print(slug,'initial jump',initial_ground,initial_jump,flush=True)
    assert min(initial_jump)<initial_ground-12,(slug,'jump did not lift player',initial_ground,initial_jump)
    run(60)
    before=geometry()
    run(30,'right',128)
    after=geometry()
    assert after[1]>before[1]+10,(slug,'right did not move player',before,after)
    run(30,'settled')
    ram=a.r32(a.addr('NES_RAM'))
    jump_trace=[]
    for i in range(12):
        run(1,'jump' if i==11 else None,1)
        jump_trace.append(geometry()[0])
    run(20,'action',130)
    run(30,'idle')
    with wave.open(str(OUT/(slug+'_audio.wav')),'wb') as wav:
        wav.setnchannels(1);wav.setsampwidth(1);wav.setframerate(11025);wav.writeframes(pcm)
    result={'file':filename,'sha256':hashlib.sha256(raw).hexdigest(),'frames':frames,
            'cpu_faults':a.r32(a.addr('nes_faults')),'apu_queue_drops':a.r32(a.addr('nes_apu_queue_drops')),
            'pcm_range':[min(pcm),max(pcm)],'hardware_tested':False}
    result.update(player_x_before=before[1],player_x_right=after[1],
                  initial_ground_y=initial_ground,jump_y=initial_jump,
                  title_and_start_to_game=True,movement_and_jump_checked=True,
                  axf_sha256=hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest())
    assert result['apu_queue_drops']==0 and max(pcm)-min(pcm)>32
    return result

if __name__=='__main__':
    OUT.mkdir(exist_ok=True)
    results=[run_game('Metroid (USA).nes','metroid'),run_game('Wizards & Warriors (U).nes','wizards')]
    (OUT/'mmc1_axrom_games_results.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
