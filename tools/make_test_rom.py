"""Build an original NROM hardware-test cartridge, no third-party game data."""
from pathlib import Path
import struct
root=Path(__file__).resolve().parents[1]
code=bytearray();labels={};fix=[]
def emit(*v): code.extend(v)
def label(n): labels[n]=0x8000+len(code)
def absop(op,n): emit(op,0,0);fix.append((len(code)-2,n,False))
def branch(op,n): emit(op,0);fix.append((len(code)-1,n,True))
def lda(n): emit(0xa9,n)
def sta(n):emit(0x8d,n&255,n>>8)
label('reset');emit(0x78,0xd8,0xa2,0xff,0x9a,0xe8);sta(0x2000);sta(0x2001)
# Palette
lda(0x3f);sta(0x2006);lda(0);sta(0x2006);emit(0xa2,0)
label('pal');absop(0xbd,'palette');sta(0x2007);emit(0xe8,0xe0,32);branch(0xd0,'pal')
# Fill 960 name tiles with alternating patterns, then clear attributes.
lda(0x20);sta(0x2006);lda(0);sta(0x2006);emit(0xa0,3,0xa2,0)
label('fill');emit(0x8a,0x29,3);sta(0x2007);emit(0xe8);branch(0xd0,'fill');emit(0x88);branch(0xd0,'fill')
emit(0xa2,0);label('tail');emit(0x8a,0x29,3);sta(0x2007);emit(0xe8,0xe0,192);branch(0xd0,'tail')
lda(0);emit(0xa2,64);label('attrs');sta(0x2007);emit(0xca);branch(0xd0,'attrs')
# Hide all other OAM sprites.
lda(0);sta(0x2003);lda(255);emit(0xa2,0);label('hide');sta(0x2004);emit(0xe8);branch(0xd0,'hide')
lda(120);emit(0x85,1);lda(128);emit(0x85,2);lda(0x80);sta(0x2000);lda(0x1e);sta(0x2001)
label('idle');absop(0x4c,'idle')
label('nmi');emit(0x48,0x8a,0x48,0x98,0x48,0xe6,0)
lda(1);sta(0x4016);lda(0);sta(0x4016);emit(0xa2,8)
label('pad');emit(0xad,0x16,0x40,0x4a,0x26,3,0xca);branch(0xd0,'pad')
# Serial bits end up reversed: right=1 left=2 down=4 up=8.
for mask,zp,op in [(1,2,0xe6),(2,2,0xc6),(4,1,0xe6),(8,1,0xc6)]:
    emit(0xa5,3,0x29,mask);branch(0xf0,f'skip{mask}');emit(op,zp);label(f'skip{mask}')
lda(0);sta(0x2003);emit(0xa5,1);sta(0x2004);lda(4);sta(0x2004);emit(0xa5,3,0x29,0x80);branch(0xf0,'normal');lda(1);branch(0xd0,'color');label('normal');lda(0);label('color');sta(0x2004);emit(0xa5,2);sta(0x2004)
lda(0);sta(0x2005);sta(0x2005);emit(0x68,0xa8,0x68,0xaa,0x68,0x40)
label('irq');emit(0x40)
label('palette');emit(*([0x0f,0x01,0x21,0x30]*4+[0x0f,0x16,0x27,0x30]*4))
for i,n,rel in fix:
    if rel:
        v=labels[n]-(0x8000+i+1);assert -128<=v<=127;code[i]=v&255
    else:code[i:i+2]=struct.pack('<H',labels[n])
prg=code+bytes([0xea])*(16384-len(code));prg[-6:]=struct.pack('<HHH',labels['nmi'],labels['reset'],labels['irq'])
chr=bytearray(8192)
for t in range(1,5):
    for y in range(8):
        chr[t*16+y]=[0,0x55 if y%2 else 0xaa,0xff if y in (0,7) else 0x81,0x18,0x3c if y in (0,7) else 0x7e][t]
        chr[t*16+y+8]=0 if t<3 else 0x3c
rom=b'NES\x1a'+bytes([1,1,1,0])+bytes(8)+prg+chr
(root/'Roms').mkdir(exist_ok=True);(root/'Roms/controller_test.nes').write_bytes(rom)
print('Original test cartridge:',len(rom),'bytes')
