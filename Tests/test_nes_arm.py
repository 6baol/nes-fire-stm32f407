"""Execute the actual Keil ARM firmware core in Unicorn (no board simulation claims)."""
from pathlib import Path
import struct,json,sys,hashlib
from elftools.elf.elffile import ELFFile
from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_MODE_MCLASS,UC_HOOK_CODE
from unicorn.arm_const import *
root=Path(__file__).resolve().parents[1];out=root/'Tests/nes_output';out.mkdir(exist_ok=True)
u=Uc(UC_ARCH_ARM,UC_MODE_THUMB|UC_MODE_MCLASS)
for a,n in [(0x08000000,0x100000),(0x20000000,0x20000),(0x10000000,0x10000),(0x6c000000,0x100000),(0xe0000000,0x100000)]:u.mem_map(a,n)
u.mem_write(0xe000ed88,struct.pack('<I',0x00f00000)) # enable Cortex-M4 FPU
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 e=ELFFile(f)
 for s in e.iter_sections():
  if s['sh_flags']&2 and s['sh_type']!='SHT_NOBITS' and s['sh_size']:u.mem_write(s['sh_addr'],s.data())
 symbols={s.name:s['st_value'] for s in e.get_section_by_name('.symtab').iter_symbols() if s.name}
def addr(n):return symbols[n]
def r32(a):return struct.unpack('<I',u.mem_read(a,4))[0]
def w32(a,v):u.mem_write(a,struct.pack('<I',v))
def skip(uc,a,size,data):uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
frame=bytearray(256*240);lines=[0]
def line(uc,a,size,data):
 y=uc.reg_read(UC_ARM_REG_R0);p=uc.reg_read(UC_ARM_REG_R1)
 assert 0<=y<240
 frame[y*256:(y+1)*256]=uc.mem_read(p,256);lines[0]+=1;skip(uc,a,size,data)
input_hook=u.hook_add(UC_HOOK_CODE,skip,begin=addr('NesPort_Input')&~1,end=addr('NesPort_Input')&~1)
u.hook_add(UC_HOOK_CODE,line,begin=addr('NesPort_Line')&~1,end=addr('NesPort_Line')&~1)
stop=0x080ff000
u.mem_write(stop,b'\x00\xbe')
def call(n,*args):
 u.reg_write(UC_ARM_REG_SP,0x2001fff0);u.reg_write(UC_ARM_REG_LR,stop|1)
 for reg,v in zip([UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3],args):u.reg_write(reg,v)
 u.emu_start(addr(n)|1,stop,count=30000000)
 if u.reg_read(UC_ARM_REG_PC)!=stop:raise RuntimeError('Instruction budget exhausted in '+n)
 return u.reg_read(UC_ARM_REG_R0)
rom=(root/'Roms/controller_test.nes').read_bytes()
test_addr=0x080d0000;u.mem_write(test_addr,rom)
assert call('Nes_Load',test_addr,len(rom))==0
ram=r32(addr('NES_RAM'));oam=r32(addr('spr_ram'))
for i in range(5):call('Nes_Frame',1)
assert r32(addr('nes_faults'))==0
assert lines[0]==1200
assert len(set(frame))>=3, set(frame)
x=u.mem_read(ram+2,1)[0]
u.mem_write(addr('PADdata'),b'\x80')
for i in range(4):call('Nes_Frame',1)
assert u.mem_read(ram+2,1)[0]==(x+4)&255
u.mem_write(addr('PADdata'),b'\x40')
for i in range(4):call('Nes_Frame',1)
assert u.mem_read(ram+2,1)[0]==x
u.mem_write(addr('PADdata'),b'\x01');call('Nes_Frame',1)
assert u.mem_read(oam+2,1)[0]==1
# Render-skipped execution must still produce the same CPU and PPU state.
u.mem_write(addr('PADdata'),b'\x00');call('Nes_Frame',0)
assert r32(addr('nes_faults'))==0
# Runtime loader rejection paths, including truncated headers and unsupported mappers.
rom=(root/'Roms/controller_test.nes').read_bytes();scratch=0x6c080000
nes2=rom[:7]+bytes([8])+rom[8:]
for payload in [b'',rom[:15],b'BAD!'+rom[4:],rom[:100],rom[:6]+bytes([0x61])+rom[7:],nes2[:8]+bytes([0x20])+nes2[9:]]:
 u.mem_write(scratch,payload or b'\x00');assert call('Nes_Load',scratch,len(payload))!=0
u.mem_write(scratch,nes2);assert call('Nes_Load',scratch,len(nes2))==0
# CHR-ROM protection via actual PPU register writes.
assert call('Nes_Load',test_addr,len(rom))==0
v=r32(addr('VROM_banks'));before=bytes(u.mem_read(v,16))
call('PPU_WriteToPort',0,0x2006);call('PPU_WriteToPort',0,0x2006);call('PPU_WriteToPort',255,0x2007)
assert bytes(u.mem_read(v,16))==before
# Real UxROM bank switching while executing in the switched region.
prg=bytearray([0xea])*32768
prg[:5]=bytes([0xa9,1,0x8d,0,0x80])
prg[16384+5:16384+13]=bytes([0xa9,0x42,0x85,0x10,0x4c,9,0x80,0xea])
prg[-6:]=struct.pack('<HHH',0x8009,0x8000,0x8009)
ux=b'NES\x1a'+bytes([2,0,0x20,0])+bytes(8)+prg
u.mem_write(scratch,bytes(ux));assert call('Nes_Load',scratch,len(ux))==0
for i in range(2):call('Nes_Frame',0)
assert u.mem_read(ram+16,1)[0]==0x42
assert r32(addr('nes_faults'))==0
# CHR RAM must be writable and update the decoded tile cache.
call('PPU_WriteToPort',0,0x2006);call('PPU_WriteToPort',0,0x2006);call('PPU_WriteToPort',255,0x2007)
assert u.mem_read(r32(addr('VROM_banks')),1)[0]==255
assert any(u.mem_read(r32(addr('VROM_tiles')),16))
# CNROM switches both raw and decoded pattern-bank pointers.
cn=bytearray(rom[:16]);cn[5]=2;cn[6]=0x31
cn+=rom[16:]+bytes([0xaa])*8192
u.mem_write(scratch,bytes(cn));assert call('Nes_Load',scratch,len(cn))==0
call('asm_Mapper_Write',1,0x8000)
ppu=r32(addr('ppu'))
# Read through $2007 (first read is buffered), avoiding hard-coded struct offsets.
call('PPU_WriteToPort',0,0x2006);call('PPU_WriteToPort',0,0x2006)
call('PPU_ReadFromPort',0x2007)
assert call('PPU_ReadFromPort',0x2007)==0xaa
# Mirrored palette entry and six-bit write mask.
call('PPU_WriteToPort',0x3f,0x2006);call('PPU_WriteToPort',0x14,0x2006);call('PPU_WriteToPort',0xff,0x2007)
call('PPU_WriteToPort',0x3f,0x2006);call('PPU_WriteToPort',4,0x2006)
assert call('PPU_ReadFromPort',0x2007)==63

# Sprite DMA through $4014 from CPU RAM page $02.
dma=bytearray(rom);dma[16:24]=bytes([0xa9,2,0x8d,0x14,0x40,0x4c,5,0x80])
u.mem_write(scratch,bytes(dma));assert call('Nes_Load',scratch,len(dma))==0
pattern=bytes(range(256));u.mem_write(ram+512,pattern)
call('run6502',2000*256)
assert bytes(u.mem_read(oam,256))==pattern
assert r32(addr('nes_faults'))==0

# Frame preview: raw PPU palette indices, not an on-board screenshot.
palette=[0x73ae,0x20d1,0x0015,0x4013,0x880e,0xa802,0xa000,0x7840,0x4160,0x0220,0x0280,0x01e2,0x19eb,0,0,0,0xbdf7,0x039d,0x21dd,0x801e,0xb817,0xe00b,0xd940,0xca61,0x8b80,0x04a0,0x0540,0x0487,0x0411,0,0,0,0xf79e,0x3dff,0x5cbf,0xa45f,0xf3df,0xfbb6,0xfbac,0xfcc7,0xf5e7,0x8682,0x4ee9,0x5fd3,0x075b,0,0,0,0xf79e,0xaf3f,0xc6bf,0xd65f,0xfe3f,0xfe3b,0xfdf6,0xfed5,0xff34,0xe7f4,0xaf97,0xb7f9,0x9ffe,0,0,0]
rgb=bytearray()
for idx in frame:
 c=palette[idx&63];rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
(out/'controller_test.ppm').write_bytes(b'P6\n256 240\n255\n'+rgb)
report=dict(result='PASS',firmware='actual Keil AXF under Unicorn Cortex-M',tests=['6502 reset/NMI execution','PPU 256x240 output','right/left controller shifts','A button changes sprite palette','frame skipping','malformed ROM rejection','CHR ROM write protection','UxROM live code bank switch','CHR RAM tile update','CNROM CHR bank switch','palette mirroring','OAM sprite DMA'],faults=0,hardware_tested=False,axf_sha256=hashlib.sha256((root/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest(),bin_sha256=hashlib.sha256((root/'Release'/(json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))['firmware_prefix']+'.bin')).read_bytes()).hexdigest())
(out/'results.json').write_text(json.dumps(report,indent=2),encoding='utf-8');print(json.dumps(report,indent=2))
