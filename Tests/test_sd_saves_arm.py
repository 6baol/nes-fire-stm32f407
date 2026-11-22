"""Battery SRAM persistence through actual ARM FatFs on an isolated FAT32 disk."""
import json,hashlib,zlib,struct
from unicorn.arm_const import UC_ARM_REG_R2, UC_ARM_REG_R3
from sd_arm_harness import SdArm,ROOT,pack_files
from test_mmc1_axrom_arm import rom as make_rom

rom=bytearray(make_rom(1,prg16=2,chr8=0,code=bytes.fromhex('4c 00 e0')))
rom[6]|=2;rom=bytes(rom) # Self-made battery-backed test cartridge, not a game edit.
files=pack_files();files['SAVE.NES']=rom
a=SdArm(files);assert a.boot()==0
save_index=a.game_index('SAVE.NES')
assert a.call('NesLibrary_Load',save_index)==0
ram=a.r32(a.addr('NES_SRAM'));pattern_a=bytes((i*17+3)&255 for i in range(8192));pattern_b=bytes((i*29+5)&255 for i in range(8192))
assert 0<a.blocks_written<20,'first boot should write only the index cache'
assert a.call('NesLibrary_SavePending')==0
a.u.mem_write(ram,pattern_a);assert a.call('NesLibrary_SavePending')==1
assert a.call('NesLibrary_Save')==0 and a.call('NesLibrary_SavePending')==0
assert a.blocks_written>0 and a.r32(a.addr('nes_sd_save_writes'))==1
before=a.blocks_written;assert a.call('NesLibrary_Save')==0 and a.blocks_written==before
a.u.mem_write(ram,pattern_b);assert a.call('NesLibrary_Save')==0
assert a.r32(a.addr('nes_sd_save_writes'))==2

def fresh(disk):
    b=SdArm(files);b.disk=bytearray(disk);assert b.boot()==0;return b
def loaded(disk,expected):
    b=fresh(disk);assert b.call('NesLibrary_Load',save_index)==0
    assert bytes(b.u.mem_read(b.r32(b.addr('NES_SRAM')),8192))==expected
    assert b.r32(b.addr('nes_sd_save_restores'))==1
    return b
b=loaded(a.disk,pattern_b)
assert b.blocks_written==0,'Restoring a save wrote the card'
# Real f_open/read/write are also used to inspect and deliberately damage only
# the private fixture's save files. No host/physical SD card is accessed.
def file_io(b,path,payload=None):
    fil=0x6c100000;name=fil+1024;got=fil+2048;buf=0x6c0a0000
    b.u.mem_write(name,path.encode()+b'\0')
    assert b.call('f_open',fil,name,1 if payload is None else 10)==0
    if payload is None:
        assert b.call('f_read',fil,buf,9000,got)==0
        data=bytes(b.u.mem_read(buf,b.r32(got)))
    else:
        b.u.mem_write(buf,bytes(payload));assert b.call('f_write',fil,buf,len(payload),got)==0
        assert b.r32(got)==len(payload);data=payload
    assert b.call('f_close',fil)==0
    return data
key=zlib.crc32(rom);paths=[f'0:/NES/SAVES/{key:08X}.SV{i}' for i in range(2)]
slots=[file_io(b,p) for p in paths]
for i,s in enumerate(slots):
    assert len(s)==8220 and s[:4]==b'NSV1'
    assert struct.unpack_from('<I',s,24)[0]==zlib.crc32(s[:24])
    assert struct.unpack_from('<I',s,20)[0]==zlib.crc32(s[28:])
assert slots[0][28:]==pattern_a and slots[1][28:]==pattern_b
damaged=bytearray(slots[1]);damaged[128]^=255;file_io(b,paths[1],damaged)
c=loaded(b.disk,pattern_a)
msg=c.r32(c.addr('status'));assert b'BACKUP' in bytes(c.u.mem_read(msg,40))

class InterruptedSlot(SdArm):
    """Fail reads at the first sector of selected generations only."""
    def __init__(self, disk, generations):
        self.generations = generations
        super().__init__(files)
        self.disk = bytearray(disk)

    def _read(self, uc, addr, size, data):
        start = uc.reg_read(UC_ARM_REG_R2)
        count = uc.reg_read(UC_ARM_REG_R3)
        for sector in range(start, start + count):
            offset = sector * 512
            if self.disk[offset:offset + 4] == b'NSV1':
                generation = struct.unpack_from('<I', self.disk, offset + 16)[0]
                if generation in self.generations:
                    self._result(uc, 1)
                    return
        super()._read(uc, addr, size, data)

for unreadable, expected in ((1, pattern_b), (2, pattern_a)):
    fallback = InterruptedSlot(a.disk, {unreadable})
    assert fallback.boot() == 0 and fallback.call('NesLibrary_Load', save_index) == 0
    assert bytes(fallback.u.mem_read(fallback.r32(fallback.addr('NES_SRAM')), 8192)) == expected
    assert fallback.blocks_written == 0
unreadable = InterruptedSlot(a.disk, {1, 2})
assert unreadable.boot() == 0 and unreadable.call('NesLibrary_Load', save_index) == 10
assert unreadable.blocks_written == 0

# Failed writes preserve the previous valid slot. A new ROM is blocked while
# unsaved SRAM is pending, then the same request can be retried successfully.
d=loaded(a.disk,pattern_b);other=d.game_index('Super Mario Bros. (World).nes')
ram_d=d.r32(d.addr('NES_SRAM'));d.u.mem_write(ram_d,pattern_a)
d.write_error=True;assert d.call('NesLibrary_Save')==1
assert d.call('NesLibrary_Load',other)==10
assert bytes(d.u.mem_read(ram_d,8192))==pattern_a
loaded(d.disk,pattern_b)
d.write_error=False;assert d.call('NesLibrary_Save')==0
loaded(d.disk,pattern_a)
# Loss during inactive-slot data writing must not discard the active slot.
e=loaded(a.disk,pattern_b);e.u.mem_write(e.r32(e.addr('NES_SRAM')),pattern_a)
e.write_limit=e.blocks_written+7;assert e.call('NesLibrary_Save')==1
loaded(e.disk,pattern_b)
# Sweep every individual sector boundary, including a failure *inside* a
# multi-sector FatFs request. A complete newly committed slot is acceptable;
# partial SRAM contents are never acceptable after a cold start.
pattern_c=bytes((i*7+13)&255 for i in range(8192))
probe=loaded(a.disk,pattern_b);probe.u.mem_write(probe.r32(probe.addr('NES_SRAM')),pattern_c)
assert probe.call('NesLibrary_Save')==0;write_sectors=probe.blocks_written;cuts=[]
for cut in range(write_sectors+1):
    interrupted=loaded(a.disk,pattern_b)
    interrupted.u.mem_write(interrupted.r32(interrupted.addr('NES_SRAM')),pattern_c)
    interrupted.write_limit=cut;result=interrupted.call('NesLibrary_Save')
    recovered=fresh(interrupted.disk);assert recovered.call('NesLibrary_Load',save_index)==0,('Unrecoverable cut',cut)
    content=bytes(recovered.u.mem_read(recovered.r32(recovered.addr('NES_SRAM')),8192))
    assert content in (pattern_b,pattern_c),('Partial save accepted',cut)
    if result==0:assert content==pattern_c
    cuts.append({'sectors_before_cut':cut,'save_result':result,'recovered':'new' if content==pattern_c else 'previous'})
# Both slots invalid: refuse to silently start over or overwrite either file.
f=fresh(a.disk)
for p,s in zip(paths,slots):
    bad=bytearray(s);bad[0]^=1;file_io(f,p,bad)
g=fresh(f.disk);before=g.blocks_written;assert g.call('NesLibrary_Load',save_index)==10 and g.blocks_written==before
# A non-battery cartridge does not create save files.
h=SdArm();assert h.boot()==0;assert h.load((ROOT/'Roms/SMB3.nes').read_bytes())==0
writes=h.blocks_written
h.u.mem_write(h.r32(h.addr('NES_SRAM')),pattern_a);assert h.call('NesLibrary_Save')==0 and h.blocks_written==writes
report={'result':'PASS','hardware_tested':False,'filesystem':'actual ARM FatFs on private FAT32 block image',
        'checks':['battery SRAM cold restore','two alternating CRC-checked slots','no writes for unchanged SRAM',
                  'bad newest slot restores backup','read-only restore','failed write preserves progress and blocks game switch',
                  'I/O failure in either slot restores the other; two unreadable slots are left alone',
                  'retry recovers','partial inactive write retains active save','two invalid slots rejected without writes',
                  'non-battery games do not save'],
        'sector_boundary_faults':cuts,
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/sd_saves_results.json').write_text(json.dumps(report,indent=2))
print(json.dumps(report,indent=2))
