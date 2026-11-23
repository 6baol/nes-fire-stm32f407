"""Read a real synthetic FAT32 filesystem using compiled ARM FatFs/library.
The card is scanned on the device and the listing lives in NES/CATALOG.IDX."""
import struct,json,hashlib,sys,zlib,tempfile
from pathlib import Path
from PIL import Image
from sd_arm_harness import SdArm,ROOT,pack_files,fat32_image
from test_mmc1_axrom_arm import rom as make_rom
sys.path.insert(0,str(ROOT/'tools'))
from prepare_sd import decode_cover,encode_cover

def text(a,p):return bytes(a.u.mem_read(p,64)).split(b'\0')[0].decode()
def games_in(files):return sorted(n for n in files if n.lower().endswith(('.nes','.fds')))
def label_of(name):return name.rsplit('.',1)[0].upper()[:46].rstrip()
def file_io(a,path,payload=None,size=9000):
    """Read or replace one file through the fixture's own FatFs instance."""
    fil=0x6c100000;name=fil+1024;got=fil+2048;buf=0x6c0a0000
    a.u.mem_write(name,path.encode()+b'\0')
    assert a.call('f_open',fil,name,1 if payload is None else 10)==0
    if payload is None:
        assert a.call('f_read',fil,buf,size,got)==0
        data=bytes(a.u.mem_read(buf,a.r32(got)))
    else:
        a.u.mem_write(buf,bytes(payload));assert a.call('f_write',fil,buf,len(payload),got)==0
        assert a.r32(got)==len(payload);data=payload
    assert a.call('f_close',fil)==0
    return data

def main():
    files=pack_files();files.pop('TITLES.DB',None)   # filename labels by default
    a=SdArm(files);checks=[]
    order=games_in(files);game_count=len(order)
    assert a.boot()==0;assert a.call('NesLibrary_Count')==game_count
    assert a.blocks_read>0
    assert a.names()==order,'directory order or names differ'
    for i,name in enumerate(order):
        a.call('NesLibrary_EnterMenu');g=a.call('NesLibrary_Game',i)
        label=text(a,a.r32(g));file_name=text(a,a.r32(g+4));raw=files[name]
        assert file_name==name and label==label_of(name),('name/label',file_name,label)
        base=name.rsplit('.',1)[0]
        p=a.call('NesLibrary_Poster',g);assert p,'SD cover failed'
        palette=a.r32(p+8);pixels=a.r32(p+4);w,h,bits,expected=decode_cover(files[base+'.COV'])
        packed=bytes(a.u.mem_read(pixels,(w*h*bits+7)//8));pal=struct.unpack('<'+'H'*(1<<bits),a.u.mem_read(palette,2*(1<<bits)))
        actual=[pal[((packed[n//2]>>(0 if n&1 else 4))&15) if bits==4 else packed[n]] for n in range(w*h)]
        assert actual==expected
        before=a.blocks_read;assert a.call('NesLibrary_Poster',g)==p and a.blocks_read==before,'cover cache missed'
        guard=0x6c01ffe0 if ((raw[6]>>4)|(raw[7]&0xf0))==5 else 0x6c05ffe0
        a.u.mem_write(guard,b'G'*32);a.u.mem_write(0x6c100000,b'END!'*8)
        assert a.call('NesLibrary_Load',i)==0,label
        assert bytes(a.u.mem_read(0x6c020000 if a.r32(a.addr('MapperNo'))==5 else 0x6c060000,len(raw)))==raw
        assert bytes(a.u.mem_read(guard,32))==b'G'*32
        assert bytes(a.u.mem_read(0x6c100000,32))==b'END!'*8
        before=a.blocks_read
        assert a.call('NesLibrary_Poster',g)==0,'cover overwrote live ROM'
        for _ in range(5):a.call('Nes_Frame',0)
        assert a.blocks_read==before,'SD read occurred in game loop'
        assert a.r32(a.addr('nes_faults'))==0
        print('PASS SD:',i,label,'bytes',len(raw),flush=True)
    checks+=['on-device directory scan keeps original names','catalog entries load and verify in SRAM',
             'catalog covers match originals','menu cover cache','live ROM protected from cover reads',
             'no SD reads during game frames','arena upper boundary']

    # CATALOG.IDX: the second boot reuses the listing instead of rebuilding it.
    b=SdArm(files);b.disk=bytearray(a.disk);assert b.boot()==0
    assert b.call('NesLibrary_Count')==game_count and b.names()==order
    assert b.blocks_written==0,'cache hit must not rewrite the catalog'
    checks.append('catalog cache written once and reused on the next boot')
    # Removing a ROM invalidates the listing.
    changed=dict(files);del changed[order[0]]
    b.replace_files(changed);assert b.boot()==0 and b.call('NesLibrary_Count')==game_count-1
    assert order[0] not in b.names()
    checks.append('removing a ROM rebuilds the catalog')
    # A damaged catalog is rebuilt from the card, never trusted.
    c=SdArm(files);c.disk=bytearray(a.disk);assert c.boot()==0
    catalog=file_io(c,'0:/NES/CATALOG.IDX')
    file_io(c,'0:/NES/CATALOG.IDX',catalog[:8]+b'Z'*(len(catalog)-8))
    assert c.boot()==0 and c.names()==order
    checks.append('corrupt CATALOG.IDX is rebuilt from the directory')

    # Bad ROMs stay listed (the listing does not open every file) but refuse to run.
    bad_mapper=bytearray(make_rom(11,prg16=4,chr8=4));bad_mapper[6]=(bad_mapper[6]&0x0f)|0x90
    bad_header=bytearray(make_rom(0,prg16=2,chr8=1));bad_header[0:4]=b'BAD!'
    short=make_rom(0,prg16=2,chr8=1)[:-1]
    changed=dict(files);changed['a-bad-mapper.nes']=bytes(bad_mapper)
    changed['z-bad-header.nes']=bytes(bad_header);changed['z-short.nes']=short
    d=SdArm(changed);assert d.boot()==0 and d.call('NesLibrary_Count')==game_count+3
    for name,fragment in (('a-bad-mapper.nes','MAPPER'),('z-bad-header.nes','HEADER'),('z-short.nes','SIZE MISMATCH')):
        assert d.call('NesLibrary_Load',d.game_index(name))==10,name
        msg=text(d,d.call('NesLibrary_Error'))
        assert fragment in msg,(name,msg)
    checks.append('unsupported mapper / bad magic / truncated ROM rejected at load time')

    # TITLES.DB on the card supplies official names; unknown files keep theirs.
    import make_titles
    smb_name='Super Mario Bros. (World).nes'
    db=('NESDB1\n%08X\tSUPER MARIO BROS.\n' % make_titles.fingerprint(files[smb_name])).encode()
    changed=dict(files);changed['TITLES.DB']=db
    m=SdArm(changed);assert m.boot()==0
    assert text(m,m.r32(m.call('NesLibrary_Game',m.game_index(smb_name))))=='SUPER MARIO BROS.'
    assert text(m,m.r32(m.call('NesLibrary_Game',m.game_index('Metroid (USA).nes'))))=='METROID (USA)'
    # A damaged dictionary is ignored, never fatal.
    changed['TITLES.DB']=b'JUNK\n00000000\tNOPE\n'
    m.replace_files(changed);assert m.boot()==0
    assert text(m,m.r32(m.call('NesLibrary_Game',m.game_index(smb_name))))=='SUPER MARIO BROS. (WORLD)'
    checks.append('TITLES.DB names games by fingerprint; missing/damaged dictionary falls back to the filename')

    # Empty card, missing card and unreadable FAT fall back to the built-in game.
    e=SdArm({});assert e.boot()!=0 and e.call('NesLibrary_Count')==1
    assert 'NO GAMES ON SD' in text(e,e.call('NesLibrary_Status'))
    e.present=False;assert e.boot()!=0
    assert 'SD INIT ERROR' in text(e,e.call('NesLibrary_Status'))
    e.present=True;assert e.call('NesLibrary_Load',0)==0,'built-in fallback failed to load'
    e.call('Nes_Frame',0);assert e.r32(e.addr('nes_faults'))==0
    e.disk=bytearray(len(e.disk));assert e.boot()!=0
    checks+=['empty/missing card and invalid FAT fall back without running a ROM']

    # The old 64-entry ceiling is gone: 70 games are listed and counted.
    many={'GAME%03d.NES'%i:make_rom(0,prg16=2,chr8=1) for i in range(70)}
    f=SdArm(many);assert f.boot()==0 and f.call('NesLibrary_Count')==70
    assert len(f.names())==70
    checks.append('70 entries listed and reachable (old 64 ceiling removed)')

    # A ROM removed behind the firmware fails to open instead of running stale data.
    g=SdArm(files);assert g.boot()==0
    smb=g.game_index('Super Mario Bros. (World).nes')
    assert g.call('NesLibrary_Load',g.game_index('Metroid (USA).nes'))==0
    gone=dict(files);del gone['Super Mario Bros. (World).nes'];g.replace_files(gone)
    assert g.call('NesLibrary_Load',smb)==10,'missing ROM should not load'
    checks.append('a ROM deleted behind the firmware fails to load instead of running stale data')

    # Cover truncation and CRC are rejected.
    smb3='Super Mario Bros. 3 (USA)'
    for bad in (files[smb3+'.COV'][:-1],files[smb3+'.COV'][:20]+b'\0'*4+files[smb3+'.COV'][24:]):
        changed=dict(files);changed[smb3+'.COV']=bad;h=SdArm(changed);assert h.boot()==0
        assert h.call('NesLibrary_Poster',h.call('NesLibrary_Game',h.game_index(smb3+'.nes')))==0
    checks+=['cover truncation and CRC rejected']

    # Runtime capture: the firmware writes a valid NCV1 from the live frame,
    # the menu reads it back, and a second capture never overwrites it.
    captured=dict(files)
    captured['COVERTEST.nes']=make_rom(0,prg16=2,chr8=1)
    n=SdArm(captured);assert n.boot()==0
    indices=bytes(((x*3+y*5)&63) for y in range(240) for x in range(256))
    runtime_pal=[(i*1097)&0xFFFF for i in range(64)]
    n.u.mem_write(0x6c080000,indices)
    n.u.mem_write(0x6c090000,struct.pack('<64H',*runtime_pal))
    n.u.mem_write(0x6c091000,b'COVERTEST.nes\0')
    assert n.call('NesLibrary_CoverExists',0x6c091000)==0
    assert n.call('NesLibrary_SaveCover',0x6c091000,0x6c080000,0x6c090000)==0
    assert n.call('NesLibrary_CoverExists',0x6c091000)==1
    n.call('NesLibrary_EnterMenu')
    g=n.call('NesLibrary_Game',n.game_index('COVERTEST.nes'));assert g
    p=n.call('NesLibrary_Poster',g);assert p,'runtime cover not readable'
    width,height=struct.unpack('<HH',n.u.mem_read(p+12,4))
    assert (width,height)==(256,240)
    packed=bytes(n.u.mem_read(n.r32(p+4),width*height))
    pal=struct.unpack('<256H',n.u.mem_read(n.r32(p+8),512))
    assert [pal[c] for c in packed]==[runtime_pal[c] for c in indices]
    assert n.call('NesLibrary_SaveCover',0x6c091000,0x6c080000,0x6c090000)==1
    checks.append('runtime start-screen capture writes a valid NCV1 and refuses to overwrite')

    with tempfile.TemporaryDirectory() as folder:
        path=Path(folder)/'cover.png'
        for width,height,full in ((3,5,False),(16,16,False),(16,16,True)):
            image=Image.new('RGB',(width,height))
            image.putdata([(255,0,0)]*15 if width==3 else [(x*16,y*16,(x+y)*8) for y in range(height) for x in range(width)])
            image.save(path);packed=encode_cover(path,full);w,h,bits,values=decode_cover(packed)
            changed=dict(files);changed[smb3+'.COV']=packed;k=SdArm(changed);assert k.boot()==0
            p=k.call('NesLibrary_Poster',k.call('NesLibrary_Game',k.game_index(smb3+'.nes')));assert p
            pixels=k.r32(p+4);palette=k.r32(p+8)
            data=bytes(k.u.mem_read(pixels,(w*h*bits+7)//8));pal=struct.unpack('<'+'H'*(1<<bits),k.u.mem_read(palette,2*(1<<bits)))
            decoded=[pal[((data[i//2]>>(0 if i&1 else 4))&15) if bits==4 else data[i]] for i in range(w*h)]
            assert decoded==values
    checks.append('odd-sized 4-bit / 8-bit / portrait COV decoded exactly')

    a.disk=fat32_image(files,mbr=False);assert a.boot()==0 and a.call('NesLibrary_Count')==game_count
    checks+=['FAT32 with MBR partition and unpartitioned FAT32 both mount']
    report={'result':'PASS','checks':checks,'hardware_tested':False,
            'filesystem':'actual compiled FatFs on synthetic FAT32 blocks',
            'listing':'on-card NES/CATALOG.IDX, RAM keeps only a window',
            'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT/'Tests/nes_output/sd_library_results.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2))

if __name__=='__main__':main()
