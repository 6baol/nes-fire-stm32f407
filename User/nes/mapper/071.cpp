#include "nes_mapper.h"

/* Legacy iNES Camerica/BF9093 plus Fire Hawk compatibility:
 * retain header H/V until $9000-$9FFF is written; ignore $8000-$8FFF.
 * Quattro outer banking (mapper 232) is deliberately not implemented here. */
void MAP71_MemoryWrite(uint16 addr,uint8 data)
{
    if(addr>=0xc000) {
        unsigned bank=(data&15)*2;
        set_CPU_banks(bank,bank+1,num_8k_ROM_banks-2,num_8k_ROM_banks-1);
    } else if((addr&0xf000)==0x9000) {
        unsigned nt=(data>>4)&1;
        set_mirroring(nt,nt,nt,nt);
    }
}
void MAP71_Reset(void)
{
    set_CPU_banks(0,1,num_8k_ROM_banks-2,num_8k_ROM_banks-1);
    set_PPU_banks(0,1,2,3,4,5,6,7);
}
void MAP71_Init(void)
{NES_Mapper->Reset=MAP71_Reset;NES_Mapper->Write=MAP71_MemoryWrite;}
