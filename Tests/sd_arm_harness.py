"""Actual ARM FatFs + library + emulator; only SD hardware blocks are mocked.
The in-memory FAT32 disk is independent of the user's F: card.
"""
import struct,hashlib,sys
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_PC,UC_ARM_REG_LR
from test_smb3_arm import Smb3Arm,ROOT
sys.path.insert(0,str(ROOT/'tools'))

def pack_files():
    return {p.name:p.read_bytes() for p in (ROOT/'Release/SD_ROOT/NES').iterdir() if p.is_file()}

def _sfn(name,index):
    base,_,ext=name.rpartition('.')
    if not base:base,ext=name,''
    def clean(text,limit):
        # 8.3 names are ASCII only; a Chinese name gets a generated alias.
        text=''.join(c for c in text.upper() if c.isascii() and (c.isalnum() or c in '_-'))
        return (text or 'GAME')[:limit]
    base,ext=clean(base,8),clean(ext,3) or 'NES'
    tail=f'~{index:x}'
    return (base[:8-len(tail)]+tail).ljust(8)+ext.ljust(3)

def _lfn_entries(name,sfn):
    check=0
    for byte in sfn.encode('ascii'):
        check=(((check&1)<<7)+(check>>1)+byte)&0xFF
    chars=[ord(c) for c in name if ord(c)<0x10000]+[0]
    while len(chars)%13:chars.append(0xFFFF)
    slots=[1,3,5,7,9,14,16,18,20,22,24,28,30]
    out=bytearray()
    for seq in range(len(chars)//13,0,-1):
        entry=bytearray(32)
        entry[0]=seq|(0x40 if seq==len(chars)//13 else 0)
        entry[11]=0x0F;entry[13]=check
        for i,ch in enumerate(chars[(seq-1)*13:seq*13]):struct.pack_into('<H',entry,slots[i],ch)
        out+=entry
    return bytes(out)

def fat32_image(files,mbr=True):
    sectors=131072;fat_sectors=1024;reserved=32;data_start=reserved+2*fat_sectors
    disk=bytearray(sectors*512);boot=memoryview(disk)[:512]
    boot[:11]=b'\xeb\x58\x90MSDOS5.0'
    struct.pack_into('<HBHBHHBHHHII',boot,11,512,1,reserved,2,0,0,0xf8,0,63,255,0,sectors)
    struct.pack_into('<IHHIHH',boot,36,fat_sectors,0,0,2,1,6)
    boot[64]=0x80;boot[66]=0x29;struct.pack_into('<I',boot,67,0x1234)
    boot[71:82]=b'NES TEST   ';boot[82:90]=b'FAT32   ';boot[510:512]=b'\x55\xaa'
    struct.pack_into('<I',disk,512,0x41615252);struct.pack_into('<I',disk,512+484,0x61417272)
    struct.pack_into('<III',disk,512+488,0xffffffff,0xffffffff,0xaa550000)
    disk[6*512:7*512]=boot
    fat=bytearray(fat_sectors*512);struct.pack_into('<II',fat,0,0x0ffffff8,0xffffffff)
    next_cluster=2
    def allocate(data):
        nonlocal next_cluster
        count=max(1,(len(data)+511)//512);first=next_cluster
        for n in range(count):
            c=next_cluster;next_cluster+=1
            struct.pack_into('<I',fat,c*4,0x0fffffff if n==count-1 else c+1)
            offset=(data_start+c-2)*512
            chunk=data[n*512:(n+1)*512];disk[offset:offset+len(chunk)]=chunk
        return first
    def entry(sfn,attr,cluster,size):
        e=bytearray(32);e[:11]=sfn.encode('ascii');e[11]=attr
        struct.pack_into('<H',e,20,cluster>>16);struct.pack_into('<H',e,26,cluster&65535);struct.pack_into('<I',e,28,size)
        return e
    root=allocate(bytes(512));assert root==2
    def emit(tree):
        """Directory payload for a nested {name: bytes | dict} tree."""
        out=bytearray();sfns=set()
        for index,name in enumerate(sorted(tree)):
            node=tree[name]
            sfn=_sfn(name,index)
            while sfn in sfns:sfn=_sfn(name,index+len(sfns)+1)
            sfns.add(sfn)
            if isinstance(node,dict):
                out+=_lfn_entries(name,sfn)+entry(sfn,0x10,allocate(emit(node)),0)
            else:
                out+=_lfn_entries(name,sfn)+entry(sfn,0x20,allocate(node),len(node))
        return bytes(out)
    tree={}
    for name,data in files.items():
        node=tree
        parts=name.split('/')
        for part in parts[:-1]:node=node.setdefault(part,{})
        node[parts[-1]]=data
    nes=allocate(emit(tree))
    off=(data_start+root-2)*512;disk[off:off+32]=entry('NES        ',0x10,nes,0)
    disk[reserved*512:(reserved+fat_sectors)*512]=fat
    disk[(reserved+fat_sectors)*512:data_start*512]=fat
    if not mbr:return disk
    # Match the user's MBR-partitioned FAT32 card, not only a superfloppy.
    partition_start=2048
    struct.pack_into('<I',disk,28,partition_start)
    disk[6*512:7*512]=disk[:512]
    partitioned=bytearray((partition_start+sectors)*512)
    partitioned[partition_start*512:]=disk
    partitioned[446+4]=0x0c
    struct.pack_into('<II',partitioned,446+8,partition_start,sectors)
    partitioned[510:512]=b'\x55\xaa'
    return partitioned

class SdArm(Smb3Arm):
    def __init__(self,files=None):
        super().__init__();self.files=pack_files() if files is None else files
        self.disk=fat32_image(self.files);self.present=True;self.io_error=False;self.blocks_read=0
        self.blocks_written=0;self.write_error=False;self.write_limit=None
        self.u.mem_map(0x6c100000,0x1000)
        for name,hook in [('SDIO_Config',self._config),('disk_initialize',self._status),('disk_status',self._status),
                          ('disk_read',self._read),('disk_write',self._write),('disk_ioctl',self._ioctl)]:
            if name in self.symbols:self.u.hook_add(UC_HOOK_CODE,hook,begin=self.addr(name)&~1,end=self.addr(name)&~1)
    def _result(self,uc,value):
        uc.reg_write(UC_ARM_REG_R0,value);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    def _config(self,uc,a,size,data):self._result(uc,0 if self.present else 1)
    def _status(self,uc,a,size,data):self._result(uc,0 if self.present else 1)
    def _read(self,uc,a,size,data):
        drive,buff,sector,count=[uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if not self.present or self.io_error or drive or not count or (sector+count)*512>len(self.disk):self._result(uc,1);return
        self.blocks_read+=count;uc.mem_write(buff,bytes(self.disk[sector*512:(sector+count)*512]));self._result(uc,0)
    def _write(self,uc,a,size,data):
        drive,buff,sector,count=[uc.reg_read(r) for r in (UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3)]
        if not self.present or self.io_error or self.write_error or drive or not count or (sector+count)*512>len(self.disk):
            self._result(uc,1);return
        allowed=count if self.write_limit is None else min(count,max(0,self.write_limit-self.blocks_written))
        if allowed:self.disk[sector*512:(sector+allowed)*512]=uc.mem_read(buff,allowed*512)
        self.blocks_written+=allowed;self._result(uc,0 if allowed==count else 1)
    def _ioctl(self,uc,a,size,data):
        cmd=uc.reg_read(UC_ARM_REG_R1);ptr=uc.reg_read(UC_ARM_REG_R2)
        if cmd==1:uc.mem_write(ptr,struct.pack('<I',len(self.disk)//512))
        elif cmd==2:uc.mem_write(ptr,struct.pack('<H',512))
        elif cmd==3:uc.mem_write(ptr,struct.pack('<I',1))
        elif cmd!=0:self._result(uc,4);return
        self._result(uc,0)
    def replace_files(self,files):self.files=files;self.disk=fat32_image(files)
    def boot(self):return self.call('NesLibrary_Boot')
    def names(self):
        out=[]
        for i in range(self.call('NesLibrary_Count')):
            game=self.call('NesLibrary_Game',i)
            ptr=self.r32(game+4)
            out.append(bytes(self.u.mem_read(ptr,161)).split(b'\0')[0].decode('utf-8'))
        return out
    def game_index(self,name):
        found=self.names()
        if name not in found:raise AssertionError(f'{name} not in library {found}')
        return found.index(name)
    def call(self,name,*args):
        reads=self.blocks_read if hasattr(self,'blocks_read') else 0
        result=super().call(name,*args)
        if name=='Nes_Frame':assert self.blocks_read==reads,'SD was accessed during emulation'
        return result
    def load(self,raw):
        import embed_roms
        if self.call('NesLibrary_Count')!=len(embed_roms.load_manifest()):assert self.boot()==0
        for g in embed_roms.load_manifest():
            d=embed_roms.normalize((ROOT/'Roms'/g['file']).read_bytes())
            if d==raw:
                self.call('NesLibrary_EnterMenu')
                rc=self.call('NesLibrary_Load',self.game_index(g.get('sd_name') or g['file']))
                if not rc:
                    arena=bytes(self.u.mem_read(0x6c020000 if embed_roms.validate(raw)==5 else 0x6c060000,len(raw)))
                    assert hashlib.sha256(arena).digest()==hashlib.sha256(raw).digest()
                return rc
        raise AssertionError('ROM not in SD fixture')
