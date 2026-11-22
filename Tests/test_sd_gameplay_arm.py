"""Existing real-game regressions with ROMs loaded by actual ARM FatFs.
Only the physical SD blocks / LCD / input port are replaced in Unicorn.
"""
import json,hashlib
from sd_arm_harness import SdArm,ROOT
import test_smb3_arm as smb3
import test_mmc1_axrom_games_arm as new_games

def main():
    smb3.Smb3Arm=SdArm;new_games.Smb3Arm=SdArm
    mario=smb3.run_smb3((ROOT/'Roms/SMB3.nes').read_bytes(),capture=True)
    assert mario['cpu_faults']==0 and mario['apu_queue_drops']==0
    games=[new_games.run_game('Metroid (USA).nes','metroid'),new_games.run_game('Wizards & Warriors (U).nes','wizards')]
    a=SdArm();assert a.load((ROOT/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes())==0
    ram=a.r32(a.addr('NES_RAM'))
    def run(n,pad=0):
        a.u.mem_write(a.addr('PADdata'),bytes([pad]))
        for i in range(n):
            a.call('Nes_Frame',int(i==n-1));a.call('apu_process',0x6c0f8000,184)
    run(900);a.save_frame('sd_smb2_title')
    run(4,8);run(120);a.save_frame('sd_smb2_gameplay')
    assert a.read8(ram+0x770)==1,'SD FDS did not enter 1-1'
    assert a.r32(a.addr('nes_faults'))==0
    report={'result':'PASS','scope':'ARM FatFs -> SRAM -> actual game execution on synthetic FAT32 blocks',
            'hardware_tested':False,'smb3_frames':mario['total_frames'],'new_games':games,
            'smb2_fds_title_and_1_1':True,'no_sd_reads_during_game_frames':True,
            'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT/'Tests/nes_output/sd_gameplay_results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
