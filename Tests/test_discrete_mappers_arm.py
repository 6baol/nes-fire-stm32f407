"""Mapper 11/66/71: real compiled ARM core, synthetic cartridge payloads only.
No commercial ROMs are fetched or added to the user's library.
"""
import hashlib,json,struct,sys
from test_mmc3_arm import NesArm,ROOT
from test_mmc1_axrom_arm import prg_layout,chr_layout
sys.path.insert(0,str(ROOT/'tools'))
import embed_roms


def cartridge(mapper,prg16=8,chr8=None,vertical=False):
    if chr8 is None:chr8={11:16,66:4,71:0}[mapper]
    header=b'NES\x1a'+bytes([prg16,chr8,((mapper&15)<<4)|int(vertical),mapper&0xf0])+bytes(8)
    prg=bytearray(b'\xea'*(prg16*16384))
    for bank in range(prg16*2):
        base=bank*8192
        prg[base+0x100]=bank
        prg[base+0x200]=0xff  # safe write at any $x200 address
        prg[base+0x300]=0x11  # deliberate AND conflict
    for base in range(0,len(prg),16384):
        prg[base+16378:base+16384]=struct.pack('<HHH',0x8000,0x8000,0x8000)
    return header+prg+b''.join(bytes([n])*1024 for n in range(chr8*8))


def nametables(a):return [a.ppu_bank(i) for i in range(8,12)]


def test_registers_and_wrap(a):
    for mapper in (11,66):
        for vertical in (False,True):
            assert a.load(cartridge(mapper,vertical=vertical))==0
            assert prg_layout(a)==[0,1,2,3] and chr_layout(a)==list(range(8))
            nts=nametables(a);base=nts[0]
            assert nts==[base+n*1024 for n in ([0,1,0,1] if vertical else [0,0,1,1])]
            # Exercise all bits, including the unused/CIC bits; both raw and
            # decoded CHR pointers must agree after every bank selection.
            for value in range(256):
                a.mapper_write(0x8200,value)
                p=((value&3) if mapper==11 else ((value>>4)&3))*4
                c=((value>>4) if mapper==11 else (value&3))*8
                assert prg_layout(a)==list(range(p,p+4)),(mapper,value)
                assert chr_layout(a)==list(range(c,c+8)),(mapper,value)
                assert a.call('Nes_ApuReadDmc',0xe100)==p+3
                assert nametables(a)==nts
                assert a.read8(a.ppu_bank(0))==c
    # Disconnected address lines wrap small ROMs rather than reading past them.
    for mapper in (11,66):
        assert a.load(cartridge(mapper,prg16=2,chr8=1))==0
        a.mapper_write(0xffff,255)
        assert prg_layout(a)==[0,1,2,3] and chr_layout(a)==list(range(8))


def test_conflicts_and_aliases(a):
    for mapper in (11,66):
        for address in (0x8200,0xa200,0xc200,0xe200,0x8300):
            assert a.load(cartridge(mapper))==0
            a.mapper_write(address,0x32)
            value=0x10 if mapper==66 and address==0x8300 else 0x32
            p=((value&3) if mapper==11 else ((value>>4)&3))*4
            c=((value>>4) if mapper==11 else (value&3))*8
            assert prg_layout(a)==list(range(p,p+4))
            assert chr_layout(a)==list(range(c,c+8))
    # Read the active PRG byte, not the unbanked file offset.
    raw=bytearray(cartridge(66));raw[16+32768+0x300]=0x22
    assert a.load(bytes(raw))==0;a.mapper_write(0x8200,0x11)
    a.mapper_write(0x8300,0x33)
    assert prg_layout(a)==[8,9,10,11] and chr_layout(a)==list(range(16,24))


def test_live_6502_and_reset_vector(a):
    for mapper,value in ((11,0xa2),(66,0x21)):
        raw=bytearray(cartridge(mapper));raw[16:21]=bytes([0xa9,value,0x8d,0,0x82])
        raw[16+65536+5:16+65536+12]=bytes.fromhex('a9 42 85 10 4c 09 80')
        # Only bank zero is initially visible; the inactive last vector is bad.
        raw[16+8*16384-4:16+8*16384-2]=b'\0\0'
        assert embed_roms.validate(raw)==mapper and a.load(bytes(raw))==0
        a.call('run6502',1000*256)
        assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x42
        assert prg_layout(a)==[8,9,10,11]
        assert chr_layout(a)==list(range(80,88) if mapper==11 else range(8,16))
        assert a.r32(a.addr('nes_faults'))==0
    # Mapper 71 executes in its fixed last bank while swapping the low window.
    raw=bytearray(cartridge(71));off=16+8*16384-8192
    raw[off:off+13]=bytes.fromhex('a9 03 8d 00 c0 ad 00 81 85 10 4c 0a e0')
    raw[16+8*16384-4:16+8*16384-2]=struct.pack('<H',0xe000)
    assert a.load(bytes(raw))==0;a.call('run6502',500*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==6
    assert prg_layout(a)==[6,7,14,15] and a.r32(a.addr('nes_faults'))==0


def test_gxrom_rmw(a):
    raw=bytearray(cartridge(66));off=16+0x6000
    raw[off:off+10]=bytes.fromhex('ee 00 e4 a9 42 85 10 4c 07 e0')
    raw[16+0x6400]=0x11;raw[16+32768+0x6400]=0x02
    raw[16+32768-4:16+32768-2]=struct.pack('<H',0xe000)
    assert a.load(bytes(raw))==0;a.call('run6502',500*256)
    assert prg_layout(a)==[0,1,2,3] and chr_layout(a)==list(range(16,24))
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x42
    assert a.r32(a.addr('nes_rmw_value'))==0 and a.r32(a.addr('nes_faults'))==0


def test_camerica_mirroring_and_chr(a):
    for vertical in (False,True):
        assert a.load(cartridge(71,vertical=vertical))==0
        nts=nametables(a);base=nts[0]
        for address in (0x8000,0x8fff,0xa000,0xbfff):
            a.mapper_write(address,0x10);assert nametables(a)==nts
            assert prg_layout(a)==[0,1,14,15]
        for value in (0x10,0,0xff,0x0f):
            a.mapper_write(0x9fff,value)
            expected=base+((value>>4)&1)*1024
            assert nametables(a)==[expected]*4
            # Test real PPU $2007 aliases, not just pointer arithmetic.
            for hi in (0x20,0x24,0x28,0x2c):
                a.call('PPU_WriteToPort',hi,0x2006);a.call('PPU_WriteToPort',0x19,0x2006)
                a.call('PPU_WriteToPort',hi,0x2007)
                assert a.read8(expected+0x19)==hi
        for address in (0xc000,0xd123,0xefff,0xffff):
            for value in (0,1,3,7,15,255):
                a.mapper_write(address,value);p=((value&15)*2)%16
                assert prg_layout(a)==[p,p+1,14,15]
                assert chr_layout(a)==list(range(8))
        a.call('PPU_WriteToPort',0,0x2006);a.call('PPU_WriteToPort',0,0x2006)
        a.call('PPU_WriteToPort',255,0x2007)
        assert a.read8(a.ppu_bank(0))==255 and any(a.u.mem_read(a.ppu_bank(0,True),16))
        a.mapper_write(0xc000,1);assert a.read8(a.ppu_bank(0))==255
    for mapper in (11,66):
        assert a.load(cartridge(mapper))==0
        before=bytes(a.u.mem_read(a.ppu_bank(0),16))
        a.call('PPU_WriteToPort',0,0x2006);a.call('PPU_WriteToPort',0,0x2006)
        a.call('PPU_WriteToPort',255,0x2007)
        assert bytes(a.u.mem_read(a.ppu_bank(0),16))==before,'CHR ROM was writable'


def test_absent_sram_and_switching(a):
    for mapper in (11,66,71):
        raw=bytearray(cartridge(mapper));raw[16:16+13]=bytes.fromhex('a9 55 8d 00 60 ad 00 60 85 10 4c 0a 80')
        assert a.load(bytes(raw))==0;a.call('run6502',500*256)
        assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0
        assert a.read8(a.r32(a.addr('NES_SRAM')))==0
        assert a.call('Nes_ApuReadDmc',0x6000)==0
        a.mapper_write(0x9200,0xff);a.mapper_write(0xe200,0xff)
        assert a.load(bytes(raw))==0 and nametables(a)[0]!=nametables(a)[-1]
    assert a.load((ROOT/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes())==0
    a.call('Nes_Frame',0)
    assert a.load(cartridge(71))==0
    assert prg_layout(a)==[0,1,14,15] and a.r32(a.addr('cpuirq'))==0
    # Restore ordinary SRAM dispatch when returning to an existing mapper.
    from test_mmc1_axrom_arm import rom
    raw=rom(0,prg16=2,chr8=1,code=bytes.fromhex('a9 55 8d 00 60 ad 00 60 85 10 4c 0a e0'))
    assert a.load(raw)==0;a.call('run6502',500*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x55


def test_header_validation(a):
    a.u.mem_map(0x30000000,0x200000)
    good=[cartridge(11),cartridge(66),cartridge(71,prg16=16)]
    good += [cartridge(m,prg16=2,chr8=c) for m,c in ((11,1),(66,1),(71,0))]
    for raw in good:
        assert embed_roms.validate(raw) in (11,66,71) and a.load(raw)==0
    bad=[cartridge(11,prg16=16),cartridge(11,chr8=0),cartridge(11,chr8=3),cartridge(11,chr8=32),
         cartridge(66,prg16=16),cartridge(66,chr8=0),cartridge(66,chr8=8),
         cartridge(71,prg16=32),cartridge(71,chr8=1)]
    for mapper in (11,66,71):
        bad.append(cartridge(mapper,prg16=1))
        for index,mask in ((6,2),(6,4),(6,8),(7,8),(8,1),(9,1)):
            raw=bytearray(cartridge(mapper));raw[index]|=mask;bad.append(bytes(raw))
        raw=bytearray(cartridge(mapper));end=32768 if mapper!=71 else 8*16384
        raw[16+end-4:16+end-2]=b'\0\0';bad.append(bytes(raw))
        raw=cartridge(mapper);bad.extend((raw[:-1],raw+b'\0'))
    for raw in bad:
        try:embed_roms.validate(raw)
        except ValueError:pass
        else:raise AssertionError('importer accepted unsupported board')
        a.u.mem_write(0x30000000,raw)
        assert a.call('Nes_Load',0x30000000,len(raw))!=0,'firmware accepted unsupported board'


def main():
    a=NesArm();tests=[test_registers_and_wrap,test_conflicts_and_aliases,test_live_6502_and_reset_vector,
                     test_gxrom_rmw,test_camerica_mirroring_and_chr,test_absent_sram_and_switching,test_header_validation]
    for test in tests:test(a);print('PASS:',test.__name__,flush=True)
    report={'result':'PASS','mappers':[11,66,71],'tests':[t.__name__ for t in tests],
            'scope':'synthetic cartridges on actual ARM AXF; no commercial-game or hardware acceptance',
            'hardware_tested':False,'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT/'Tests/nes_output/discrete_mappers_results.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
