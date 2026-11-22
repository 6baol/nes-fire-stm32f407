"""Synthetic MMC1B/AxROM cartridges executed by the actual Keil ARM core.
No commercial-game or board acceptance is implied by these tests.
"""
import hashlib,json,struct,sys
from test_mmc3_arm import NesArm, ROOT
sys.path.insert(0,str(ROOT/'tools'))
import embed_roms

def rom(mapper,prg16=8,chr8=4,code=None):
    prg=bytearray(b'\xea'*(prg16*16384))
    for bank in range(prg16*2):
        off=bank*8192
        prg[off:off+3]=bytes([0x4c,0,0xe0])
        prg[off+0x100]=bank
    for off in range(0,len(prg),16384):
        prg[off+16378:off+16384]=struct.pack('<HHH',0xe000,0xe000,0xe000)
    if code is not None:prg[-8192:-8192+len(code)]=code
    chr_data=b''.join(bytes([n])*1024 for n in range(chr8*8))
    return b'NES\x1a'+bytes([prg16,chr8,mapper<<4])+bytes(9)+prg+chr_data

def serial(a,addr,value):
    for bit in range(5):a.mapper_write(addr,(value>>bit)&1)

def prg_layout(a):return [a.cpu_read(x) for x in (0x8100,0xa100,0xc100,0xe100)]

def chr_layout(a):
    raw=a.r32(a.addr('VROM_banks'));tiles=a.r32(a.addr('VROM_tiles'))
    indices=[(a.ppu_bank(i)-raw)//1024 for i in range(8)]
    assert [a.ppu_bank(i,True)-tiles for i in range(8)]==[n*1024 for n in indices]
    return indices

def test_serial_and_mapping(a):
    assert a.load(rom(1))==0
    assert prg_layout(a)==[0,1,14,15]
    for _ in range(4):a.mapper_write(0xe000,1)
    assert prg_layout(a)==[0,1,14,15], 'partial serial write committed'
    a.mapper_write(0x8000,0x80)
    assert a.read8(a.addr('mmc1_count'))==0
    serial(a,0xe000,3);assert prg_layout(a)==[6,7,14,15]
    for control,expected in [(0,[4,5,6,7]),(4,[4,5,6,7]),(8,[0,1,6,7]),(12,[6,7,14,15])]:
        serial(a,0x8000,control);assert prg_layout(a)==expected
        assert a.call('Nes_ApuReadDmc',0xa100)==expected[1]
    serial(a,0x8000,0x1c)
    serial(a,0xa000,3);serial(a,0xc000,5)
    assert chr_layout(a)==list(range(12,16))+list(range(20,24))
    serial(a,0x8000,0x0c);assert chr_layout(a)==list(range(8,16))
    # All five data writes share one shift register; only the fifth address
    # decides which register gets the value.
    a.mapper_write(0x8000,0x80)
    for bit in (1,0,1,0):a.mapper_write(0x8000,bit)
    a.mapper_write(0xa000,0)
    assert a.read8(a.addr('mmc1_chr0'))==5
    assert a.read8(a.addr('mmc1_control'))==12

def test_nametables(a):
    assert a.load(rom(1))==0
    base=a.ppu_bank(8)
    for mode,indices in [(0,[0,0,0,0]),(1,[1,1,1,1]),(2,[0,1,0,1]),(3,[0,0,1,1])]:
        serial(a,0x8000,12|mode)
        assert [a.ppu_bank(i) for i in range(8,12)]==[base+n*1024 for n in indices]

def test_sram(a):
    def write_reg(value):
        return b''.join(bytes([0xa9,(value>>i)&1,0x8d,0,0xe0]) for i in range(5))
    code=bytes.fromhex('a9 55 8d 00 60')+write_reg(16)
    code+=bytes.fromhex('a9 aa 8d 00 60 ad 00 60 85 10')+write_reg(0)
    code+=bytes.fromhex('ad 00 60 85 11')
    code+=bytes([0x4c,len(code)&255,0xe0+(len(code)>>8)])
    assert a.load(rom(1,code=code))==0
    a.call('run6502',3000*256);ram=a.r32(a.addr('NES_RAM'))
    assert bytes(a.u.mem_read(ram+16,2))==b'\0\x55'
    assert a.r32(a.addr('nes_faults'))==0

def test_rmw_and_live_code(a):
    # Both old and new bus writes can reset; only the first writes D0.
    for op in (0x0e,0x1e,0x2e,0x3e,0x4e,0x5e,0x6e,0x7e,0xce,0xde,0xee,0xfe):
        for old in (1,0xff):
            data=bytearray(rom(1,code=bytes([op,0,0xe1,0x4c,3,0xe0])))
            data[16+8*16384-8192+0x100]=old
            assert a.load(bytes(data))==0
            a.call('run6502',100*256)
            assert a.read8(a.addr('mmc1_count'))==(0 if old&128 else 1), (hex(op),old)
            assert a.r32(a.addr('nes_rmw_value'))==0
            assert a.r32(a.addr('nes_faults'))==0
    # INC $7F -> $80: second-cycle reset must not be suppressed.
    data=bytearray(rom(1,code=bytes.fromhex('ee 00 e1 4c 03 e0')))
    data[16+8*16384-8192+0x100]=0x7f
    assert a.load(bytes(data))==0;a.call('run6502',100*256)
    assert a.read8(a.addr('mmc1_count'))==0
    # SRAM RMW must clear its annotation before an ordinary mapper write.
    assert a.load(rom(1,code=bytes.fromhex('ee 00 60 a9 01 8d 00 e0 4c 08 e0')))==0
    a.call('run6502',100*256)
    assert a.read8(a.addr('mmc1_count'))==1 and a.read8(a.addr('mmc1_shift'))==1
    # Change the bank containing the executing instructions on the fifth STA.
    data=bytearray(rom(1));code=b''.join(bytes([0xa9,(2>>i)&1,0x8d,0,0xe0]) for i in range(5))
    data[16:16+len(code)]=code
    data[16+2*16384+25:16+2*16384+32]=bytes.fromhex('a9 42 85 10 4c 1d 80')
    data[16+8*16384-4:16+8*16384-2]=struct.pack('<H',0x8000)
    assert a.load(bytes(data))==0;a.call('run6502',1000*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x42

def test_chr_ram_and_snrom_gate(a):
    assert a.load(rom(1,chr8=0))==0
    serial(a,0x8000,0x1c);serial(a,0xa000,1);serial(a,0xc000,0)
    assert chr_layout(a)==[4,5,6,7,0,1,2,3]
    a.call('PPU_WriteToPort',0,0x2006);a.call('PPU_WriteToPort',0,0x2006)
    a.call('PPU_WriteToPort',255,0x2007)
    assert a.read8(a.r32(a.addr('VROM_banks'))+4096)==255
    assert any(a.u.mem_read(a.ppu_bank(0,True),16))
    serial(a,0xa000,16);assert a.read8(a.addr('mmc1_sram_enabled'))==0
    serial(a,0xa000,0);assert a.read8(a.addr('mmc1_sram_enabled'))==1

def test_axrom(a):
    raw=rom(7,chr8=0);assert a.load(raw)==0
    assert prg_layout(a)==[0,1,2,3]
    base=a.ppu_bank(8)
    for value in (0,1,2,3,7,0x10,0x11):
        a.mapper_write(0xffff,value)
        start=((value&7)*4)%16
        assert prg_layout(a)==list(range(start,start+4))
        assert [a.ppu_bank(i) for i in range(8,12)]==[base+((value>>4)&1)*1024]*4
    data=bytearray(raw)
    data[16:21]=bytes.fromhex('a9 01 8d 00 80')
    data[16+32768+5:16+32768+12]=bytes.fromhex('a9 42 85 10 4c 09 80')
    data[16+32768-4:16+32768-2]=struct.pack('<H',0x8000)
    # The inactive final bank vector is deliberately invalid.
    data[16+8*16384-4:16+8*16384-2]=b'\0\0'
    assert embed_roms.validate(bytes(data))==7
    assert a.load(bytes(data))==0;a.call('run6502',1000*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x42
    assert a.r32(a.addr('nes_faults'))==0

def test_validation(a):
    a.u.mem_map(0x30000000,0x100000)  # isolated test-only buffer for oversized inputs
    for raw in (rom(1),rom(1,chr8=0),rom(7,chr8=0)):
        assert embed_roms.validate(raw) in (1,7) and a.load(raw)==0
    for raw in (rom(1,prg16=32),rom(1,chr8=3),rom(7,chr8=1),rom(7,prg16=1,chr8=0)):
        try:embed_roms.validate(raw)
        except ValueError:pass
        else:raise AssertionError('importer accepted unsupported board configuration')
        a.u.mem_write(0x30000000,raw)
        assert a.call('Nes_Load',0x30000000,len(raw))!=0

def test_switching(a):
    assert a.load(rom(1,chr8=0))==0
    serial(a,0xe000,16)
    a.mapper_write(0xa000,1)  # leave a partial serial transaction behind
    assert a.load((ROOT/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes())==0
    a.call('Nes_Frame',0)
    code=bytes.fromhex('a9 55 8d 00 60 ad 00 60 85 10 4c 0a e0')
    # AxROM starts in bank 0, so place the code at its $E000 window.
    data=bytearray(rom(7,chr8=0));data[16+0x6000:16+0x6000+len(code)]=code
    assert a.load(bytes(data))==0;a.call('run6502',300*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0,'AxROM unexpectedly exposed SRAM'
    assert a.load(rom(0,prg16=2,chr8=1,code=code))==0
    a.call('run6502',300*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x55,'normal SRAM path was not restored'
    assert a.load(rom(1))==0
    assert a.read8(a.addr('mmc1_count'))==0 and a.read8(a.addr('mmc1_sram_enabled'))==1
    assert a.r32(a.addr('cpuirq'))==0 and a.r32(a.addr('nes_faults'))==0

def main():
    a=NesArm();tests=[test_serial_and_mapping,test_nametables,test_sram,test_rmw_and_live_code,test_chr_ram_and_snrom_gate,test_axrom,test_validation,test_switching]
    for test in tests:test(a);print('PASS:',test.__name__,flush=True)
    report={'result':'PASS','scope':'synthetic cartridges on actual ARM AXF; no commercial ROM or board acceptance',
            'tests':[t.__name__ for t in tests],'hardware_tested':False,
            'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT/'Tests/nes_output/mmc1_axrom_results.json').write_text(json.dumps(report,indent=2))
if __name__=='__main__':main()
