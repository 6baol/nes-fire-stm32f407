"""New discrete mappers through real ARM FatFs/index/preload/loader paths.
Synthetic FAT32 and cartridges exist only in memory, never on a physical card.
"""
import hashlib,json
from sd_arm_harness import SdArm,ROOT
from test_discrete_mappers_arm import cartridge,prg_layout,chr_layout


def main():
    files={};mappers=(11,66,71)
    for i,mapper in enumerate(mappers):
        name=f'TEST{i}.NES';raw=bytearray(cartridge(mapper));raw[16:19]=bytes.fromhex('4c 00 80')
        files[name]=bytes(raw)
    a=SdArm(files);assert a.boot()==0 and a.call('NesLibrary_Count')==3
    for i,mapper in enumerate(mappers):
        a.call('NesLibrary_EnterMenu');assert a.call('NesLibrary_Load',i)==0
        assert a.r32(a.addr('MapperNo'))==mapper
        raw=files[f'TEST{i}.NES'];assert bytes(a.u.mem_read(0x6c060000,len(raw)))==raw
        before=a.blocks_read;writes=a.blocks_written
        for _ in range(3):a.call('Nes_Frame',0)
        assert a.blocks_read==before and a.blocks_written==writes
        assert a.r32(a.addr('nes_faults'))==0
        if mapper==71:
            a.mapper_write(0xc000,3);assert prg_layout(a)==[6,7,14,15]
            assert chr_layout(a)==list(range(8))
        else:
            a.mapper_write(0x8200,0x21)
            p=4 if mapper==11 else 8;c=16 if mapper==11 else 8
            assert prg_layout(a)==list(range(p,p+4))
            assert chr_layout(a)==list(range(c,c+8))
        print('PASS SD scan / preload / CPU / banks:',mapper,flush=True)
    report={'result':'PASS','mappers':list(mappers),'hardware_tested':False,
            'scope':'actual ARM FatFs/directory-scan/preload/emulator; in-memory synthetic FAT32 and cartridges',
            'checks':['three mapper IDs accepted by the on-device header check','preload bytes verified',
                      '6502 frames without faults','bank/CHR mapping after SD load',
                      'no SD access during game frames','no SD writes'],
            'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT/'Tests/nes_output/discrete_mappers_sd_results.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
