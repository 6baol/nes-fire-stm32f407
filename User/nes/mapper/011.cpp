#include "nes_mapper.h"

/* Color Dreams: legacy iNES defaults to no conflicts, as with AxROM.
 * Conflict-dependent boards / NES 2.0 submappers are outside this profile. */
void MAP11_MemoryWrite(uint16 addr,uint8 data)
{
    unsigned prg=(data&3)*4,chr=(data>>4)*8;
    (void)addr;
    set_CPU_banks(prg,prg+1,prg+2,prg+3);
    set_PPU_banks(chr,chr+1,chr+2,chr+3,chr+4,chr+5,chr+6,chr+7);
}
void MAP11_Reset(void){MAP11_MemoryWrite(0x8000,0);}
void MAP11_Init(void)
{NES_Mapper->Reset=MAP11_Reset;NES_Mapper->Write=MAP11_MemoryWrite;}
