#include "nes_mapper.h"

/* Standard GNROM/MHROM wiring, including ROM/CPU AND bus conflicts.
 * Read the OLD mapping before either PRG or CHR is changed. */
void MAP66_MemoryWrite(uint16 addr,uint8 data)
{
    unsigned prg,chr;
    data&=Nes_ApuReadDmc(addr);
    prg=((data>>4)&3)*4;chr=(data&3)*8;
    set_CPU_banks(prg,prg+1,prg+2,prg+3);
    set_PPU_banks(chr,chr+1,chr+2,chr+3,chr+4,chr+5,chr+6,chr+7);
}
void MAP66_Reset(void)
{
    set_CPU_banks(0,1,2,3);
    set_PPU_banks(0,1,2,3,4,5,6,7);
}
void MAP66_Init(void)
{NES_Mapper->Reset=MAP66_Reset;NES_Mapper->Write=MAP66_MemoryWrite;}
