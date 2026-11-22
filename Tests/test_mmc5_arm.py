"""Restricted MMC5 board profile on actual ARM firmware; synthetic ROMs."""
import sys,struct,json,hashlib
from test_mmc3_arm import NesArm,ROOT
from test_discrete_mappers_arm import cartridge,prg_layout
sys.path.insert(0,str(ROOT/'tools'))
import embed_roms

def rom():return cartridge(5,prg16=32,chr8=32)
def load(a,raw=None):
    raw=rom() if raw is None else raw
    a.u.mem_write(0x6c020000,raw);assert a.call('Nes_Load',0x6c020000,len(raw))==0
def wr(a,addr,value):a.call('asm_Mapper_WriteLow',value,addr)
def rd(a,addr):return a.call('asm_Mapper_ReadLow',addr)
def tile(a,addr,bg=0,nt=0,x=0):
    a.u.mem_write(0x6c010000,struct.pack('<II',0,0))
    # Six arguments: invoke uses R0-R3 plus an AAPCS stack slot for each extra.
    from unicorn.arm_const import UC_ARM_REG_SP,UC_ARM_REG_LR,UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_PC
    from test_mmc3_arm import STOP
    a.u.reg_write(UC_ARM_REG_SP,0x2001fff0);a.u.mem_write(0x2001fff0,struct.pack('<II',0x6c010000,0x6c010004))
    a.u.reg_write(UC_ARM_REG_LR,STOP|1)
    for r,v in zip((UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3),(addr,bg,nt,x)):a.u.reg_write(r,v)
    a.u.emu_start(a.addr('MAP5_Tile')|1,STOP,count=100000)
    assert a.u.reg_read(UC_ARM_REG_PC)==STOP
    ptr=a.u.reg_read(UC_ARM_REG_R0)
    return bytes(a.u.mem_read(ptr,16)),a.r32(0x6c010000)
def decoded(value):
    row=bytes(sum((3 if value&(128>>(n*4+k)) else 0)<<(6-2*k) for k in range(4)) for n in range(2))
    return row*8

def test_prg(a):
    load(a)
    for i,v in enumerate((0,0x85,0x89,0x8d,0x91)):wr(a,0x5113+i,v)
    for mode,expect in [(0,[16,17,18,19]),(1,[8,9,16,17]),(2,[8,9,13,17]),(3,[5,9,13,17])]:
        wr(a,0x5100,mode);assert prg_layout(a)==expect,(mode,prg_layout(a))
    # Switching the bank holding the executing STA must update encoded PC.
    raw=bytearray(rom());off=16+32*16384-8192
    raw[off:off+5]=bytes.fromhex('a9 80 8d 17 51')
    raw[16+5:16+12]=bytes.fromhex('a9 42 85 10 4c 09 e0')
    raw[16+32*16384-4:16+32*16384-2]=struct.pack('<H',0xe000)
    load(a,bytes(raw));a.call('run6502',300*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x42

def test_ram_and_indirect_jump(a):
    raw=bytearray(rom());off=16+32*16384-8192
    code=bytes.fromhex('a9 02 8d 02 51 a9 01 8d 03 51 a9 00 8d 14 51 a9 55 8d 00 81 ad 00 61 85 10 4c 19 e0')
    raw[off:off+len(code)]=code;raw[16+32*16384-4:16+32*16384-2]=struct.pack('<H',0xe000)
    load(a,bytes(raw));a.call('run6502',500*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x55
    wr(a,0x5102,0);a.mapper_write(0x8100,0xaa)
    assert a.read8(a.r32(a.addr('NES_SRAM'))+256)==0x55
    raw[off:off+3]=bytes.fromhex('6c ad 6d');raw[off+16:off+23]=bytes.fromhex('a9 42 85 10 4c 14 e0')
    load(a,bytes(raw));a.u.mem_write(a.r32(a.addr('NES_SRAM'))+0xdad,struct.pack('<H',0xe010))
    a.call('run6502',300*256)
    assert a.read8(a.r32(a.addr('NES_RAM'))+16)==0x42,'JMP through $6000 WRAM used an unrebased address'
    assert a.r32(a.addr('nes_faults'))==0

def test_chr_cache(a):
    load(a)
    for mode in range(4):
        wr(a,0x5101,mode);span=8>>mode
        for i in range(12):wr(a,0x5120+i,i+1)
        for page in range(8):
            reg=page|(span-1);bank=((reg+1)*span+(page&(span-1)))%256
            assert a.call('MAP5_PpuRead',page*1024)==bank
            assert tile(a,page*1024)[0]==decoded(bank),(mode,page,bank)
    a.call('PPU_WriteToPort',32,0x2000);wr(a,0x5101,3)
    assert tile(a,0,1)[0]==decoded(9) and tile(a,0,0)[0]==decoded(1)
    wr(a,0x5130,1);wr(a,0x5120,2);wr(a,0x5130,0)
    assert tile(a,0)[0]==decoded(2),'upper bits must latch at CHR register write'
    # Same direct cache slot with different source tag, then back again.
    for bank in (1,65,129,1):wr(a,0x5120,bank);assert tile(a,0)[0]==decoded(bank)

def test_exram_fill_irq_multiplier(a):
    load(a);wr(a,0x5104,2);wr(a,0x5c19,0x83);assert rd(a,0x5c19)==0x83
    wr(a,0x5104,1);a.call('PPU_WriteToPort',8,0x2001);a.call('MAP5_Line',0)
    data,palette=tile(a,0x50,1,0x2019);assert data==decoded(12) and palette==8
    wr(a,0x5105,0xff);wr(a,0x5106,7);wr(a,0x5107,2)
    assert a.call('MAP5_PpuRead',0x2000)==7 and a.call('MAP5_PpuRead',0x23c0)==0xaa
    a.call('MAP5_PpuWrite',0x2000,0x55);assert a.call('MAP5_PpuRead',0x2000)==7
    wr(a,0x5203,2);wr(a,0x5204,0);a.call('MAP5_Line',1);a.call('MAP5_Line',2)
    assert a.r32(a.addr('cpuirq'))==0
    wr(a,0x5204,128);assert a.read8(a.addr('cpuirq'))==1
    assert rd(a,0x5204)==0xc0 and rd(a,0x5204)==0x40 and a.read8(a.addr('cpuirq'))==0
    a.call('MAP5_Line',240);assert rd(a,0x5204)==0
    for x,y in ((0,255),(255,255),(17,93)):
        wr(a,0x5205,x);wr(a,0x5206,y);assert rd(a,0x5205)+(rd(a,0x5206)<<8)==x*y

def test_audio(a):
    a.call('Mmc5Audio_Reset');a.call('Mmc5Audio_Apply',0x5015,1)
    for ad,v in ((0x5000,0x9f),(0x5002,253),(0x5003,0x08)):a.call('Mmc5Audio_Apply',ad,v)
    samples=[a.call('Mmc5Audio_Sample',162<<16) for _ in range(512)]
    assert min(samples)==0 and max(samples)==15*256
    transitions=sum((samples[i]>0)!=(samples[i-1]>0) for i in range(1,len(samples)))
    assert 35<transitions<48,transitions
    a.call('Mmc5Audio_Apply',0x5015,0);assert a.call('Mmc5Audio_Sample',162<<16)==0
    a.call('Mmc5Audio_Apply',0x5011,128);assert a.call('Mmc5Audio_Sample',162<<16)==4096
    a.call('Mmc5Audio_Apply',0x5011,0);assert a.call('Mmc5Audio_Sample',162<<16)==4096
    a.call('Mmc5Audio_Reset');a.call('Mmc5Audio_Write',0x5015,3);a.call('Mmc5Audio_Write',0x5003,0x18)
    assert a.call('Mmc5Audio_Read',0x5015)==1
    a.call('Mmc5Audio_Tick',16000);assert a.call('Mmc5Audio_Read',0x5015)==0

def test_capture_guard(a):
    from unicorn import UC_HOOK_CODE
    class NativeLineArm(NesArm):
        def _line(self,*args):pass
    b=NativeLineArm();b.u.mem_map(0x68000000,0x1000)
    b.u.mem_write(0x080fef00,bytes.fromhex('70 47'))
    b.u.mem_write(b.addr('lcd_open_window'),struct.pack('<I',0x080fef01))
    raw=rom();load(b,raw)
    b.u.mem_write(b.addr('nes_capture_request'),struct.pack('<I',1))
    b.u.mem_write(0x6c010000,bytes(256));b.u.mem_write(0x6c011000,bytes(128))
    b.call('NesPort_Line',0,0x6c010000,0x6c011000)
    b.call('NesPort_Line',239,0x6c010000,0x6c011000)
    assert bytes(b.u.mem_read(0x6c020000,len(raw)))==raw
    assert b.r32(b.addr('nes_capture_request'))==0 and b.r32(b.addr('nes_capture_ready'))==0

def main():
    a=NesArm();tests=[test_prg,test_ram_and_indirect_jump,test_chr_cache,test_exram_fill_irq_multiplier,test_audio,test_capture_guard]
    for t in tests:t(a);print('PASS',t.__name__,flush=True)
    (ROOT/'Tests/nes_output/mmc5_core_results.json').write_text(json.dumps({'result':'PASS','tests':[t.__name__ for t in tests],
        'hardware_tested':False,'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()},indent=2))
if __name__=='__main__':main()
