#include "nes_mapper.h"

/* iNES mapper 7 (unspecified bus conflicts: emulate no conflicts). */
void MAP7_MemoryWrite(uint16 addr,uint8 data)
{
    unsigned bank=(data&7)*4,nt=(data>>4)&1;
    (void)addr;
    set_CPU_banks(bank,bank+1,bank+2,bank+3);
    set_mirroring(nt,nt,nt,nt);
}
void MAP7_Reset(void){MAP7_MemoryWrite(0x8000,0);}
void MAP7_Init(void)
{NES_Mapper->Reset=MAP7_Reset;NES_Mapper->Write=MAP7_MemoryWrite;}
