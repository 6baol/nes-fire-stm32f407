#include "nes_mapper.h"
 
// Mapper 2
void MAP2_Reset()
{
//	// set CPU bank pointers
//	set_CPU_banks(0,1,num_8k_ROM_banks-2,num_8k_ROM_banks-1);
}

void MAP2_MemoryWrite(uint16 addr, uint8 data)
{
    (void)addr;
	data &= RomHeader->num_16k_rom_banks-1;
	set_CPU_banks(data*2,(data*2)+1,num_8k_ROM_banks-2,num_8k_ROM_banks-1);
}
void MAP2_Init()
{
	NES_Mapper->Reset=MAP2_Reset;
	NES_Mapper->Write=MAP2_MemoryWrite;
}























