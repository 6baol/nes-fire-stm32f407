"""Execute the real board SDIO wrapper with mocked HAL commands, no board.
Checks conservative setup, aligned internal bounce buffer, retries and bounds.
"""
import struct
from test_mmc3_arm import NesArm
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R2,UC_ARM_REG_R3,UC_ARM_REG_PC,UC_ARM_REG_LR

class Driver(NesArm):
    def __init__(self,init_failures=0,bus_fail=False,read_failures=0):
        super().__init__();self.u.mem_map(0x40000000,0x30000)
        self.inits=[];self.widths=[];self.reads=[];self.aborts=0;self.writes=[];self.write_failures=0
        self.init_failures=init_failures;self.bus_fail=bus_fail;self.read_failures=read_failures
        for name,hook in [('HAL_SD_Init',self.init),('HAL_SD_ConfigWideBusOperation',self.bus),
                          ('HAL_SD_GetCardInfo',self.info),('HAL_SD_GetCardState',self.ready),
                          ('HAL_SD_ReadBlocks',self.read),('HAL_SD_WriteBlocks',self.write),
                          ('HAL_SD_Abort',self.abort),('HAL_Delay',self.delay)]:
            self.u.hook_add(UC_HOOK_CODE,hook,begin=self.addr(name)&~1,end=self.addr(name)&~1)
    def ret(self,uc,value=0):uc.reg_write(UC_ARM_REG_R0,value);uc.reg_write(UC_ARM_REG_PC,uc.reg_read(UC_ARM_REG_LR))
    def init(self,uc,a,size,data):
        handle=uc.reg_read(UC_ARM_REG_R0);self.inits.append(self.r32(handle+24))
        fail=len(self.inits)<=self.init_failures
        uc.mem_write(handle+56,struct.pack('<I',4 if fail else 0));self.ret(uc,int(fail))
    def bus(self,uc,a,size,data):
        width=uc.reg_read(UC_ARM_REG_R1);self.widths.append(width)
        fail=self.bus_fail and width==0x800
        if fail:uc.mem_write(self.addr('g_sd_handle')+56,struct.pack('<I',2))
        self.ret(uc,int(fail))
    def info(self,uc,a,size,data):
        uc.mem_write(uc.reg_read(UC_ARM_REG_R1),struct.pack('<8I',1,1,0,0x1234,10000,512,10000,512));self.ret(uc)
    def ready(self,uc,a,size,data):self.ret(uc,4)
    def delay(self,uc,a,size,data):self.ret(uc)
    def abort(self,uc,a,size,data):self.aborts+=1;self.ret(uc)
    def write(self,uc,a,size,data):
        pointer=uc.reg_read(UC_ARM_REG_R1);sector=uc.reg_read(UC_ARM_REG_R2);count=uc.reg_read(UC_ARM_REG_R3)
        assert 0x20000000<=pointer<0x20020000 and pointer%4==0 and count==1
        self.writes.append((sector,bytes(uc.mem_read(pointer,512))))
        if self.write_failures:
            self.write_failures-=1;uc.mem_write(self.addr('g_sd_handle')+56,struct.pack('<I',0x10));self.ret(uc,1)
        else:self.ret(uc)
    def read(self,uc,a,size,data):
        pointer=uc.reg_read(UC_ARM_REG_R1);sector=uc.reg_read(UC_ARM_REG_R2);count=uc.reg_read(UC_ARM_REG_R3)
        assert 0x20000000<=pointer<0x20020000 and pointer%4==0,'FIFO copied directly to external/unaligned memory'
        assert count==1,'polling read used a multi-sector transfer'
        self.reads.append(sector)
        if self.read_failures:
            self.read_failures-=1;uc.mem_write(self.addr('g_sd_handle')+56,struct.pack('<I',0x20));self.ret(uc,1)
        else:uc.mem_write(pointer,bytes([sector&255])*512);self.ret(uc)

def main():
    a=Driver(read_failures=1);assert a.call('SDIO_Config')==0
    assert a.inits==[46] and a.widths==[0x800] and a.r32(a.addr('sd_bus_width'))==4
    target=0x6c060001;a.u.mem_write(target-1,b'G'*1026)
    assert a.call('BSP_SD_ReadBlocks',target,7,2)==0
    assert bytes(a.u.mem_read(target,1024))==b'\x07'*512+b'\x08'*512
    assert a.read8(target-1)==a.read8(target+1024)==ord('G')
    assert a.reads==[7,7,8] and a.aborts==1 and a.r32(a.addr('sd_read_retries'))==1
    assert a.r32(a.addr('sd_last_error'))==0x20
    before=len(a.reads)
    for addr,sector,count in [(0,1,1),(target,1,0),(target,10000,1),(target,9999,2)]:
        assert a.call('BSP_SD_ReadBlocks',addr,sector,count)!=0
    assert len(a.reads)==before
    a.read_failures=2;assert a.call('BSP_SD_ReadBlocks',target,8,1)!=0
    a.u.mem_write(target,b'A'*512+b'B'*512);a.write_failures=1
    assert a.call('BSP_SD_WriteBlocks',target,9,2)==0
    assert a.writes==[(9,b'A'*512),(9,b'A'*512),(10,b'B'*512)]
    assert a.r32(a.addr('sd_write_retries'))==1 and a.r32(a.addr('sd_blocks_written'))==2
    assert a.call('BSP_SD_Sync')==0
    before=len(a.writes)
    for addr,sector,count in [(0,1,1),(target,1,0),(target,10000,1),(target,9999,2)]:
        assert a.call('BSP_SD_WriteBlocks',addr,sector,count)!=0
    assert len(a.writes)==before
    a.write_failures=2;assert a.call('BSP_SD_WriteBlocks',target,9,1)!=0
    b=Driver(init_failures=1);assert b.call('SDIO_Config')==0
    assert b.inits==[46,118] and b.widths==[0] and b.r32(b.addr('sd_bus_width'))==1
    c=Driver(bus_fail=True);assert c.call('SDIO_Config')==0
    assert c.inits==[46,118] and c.widths==[0x800,0] and c.aborts==1
    d=Driver(init_failures=3);assert d.call('SDIO_Config')!=0 and len(d.inits)==3
    print('PASS: clocks/fallback, aligned read/write staging, bounded retries, sync and sector guards')
if __name__=='__main__':main()
