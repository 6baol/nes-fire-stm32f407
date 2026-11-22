#include "nes_mapper.h"

/* Mapper 40 - Nintendo MMC (Super Mario Bros. 2 / Lost Levels).
 *   $8000-$9FFF  write: 16 KiB PRG bank mapped to $8000-$BFFF (bits 2:0)
 *   $A000-$BFFF  write: 8 KiB CHR bank mapped to $0000-$1FFF (bits 2:0)
 *   $C000-$FFFF  fixed to the last 16 KiB PRG bank
 * Mapper 40 has no scanline IRQ and no PRG RAM banking. */

static void MAP40_Reset()
{
	if(VROM_1K_SIZE)
	{
		set_PPU_banks(0,1,2,3,4,5,6,7);
	}
}

static void MAP40_MemoryWrite(uint16 addr, uint8 data)
{
	if(addr < 0xA000)
	{
		uint32 bank = (uint32)data & (RomHeader->num_16k_rom_banks - 1);
		set_CPU_banks(bank*2, bank*2+1, num_8k_ROM_banks-2, num_8k_ROM_banks-1);
	}
	else if(addr < 0xC000 && RomHeader->num_8k_vrom_banks)
	{
		uint32 base = ((uint32)data & (RomHeader->num_8k_vrom_banks - 1)) << 3;
		set_PPU_banks(base+0,base+1,base+2,base+3,base+4,base+5,base+6,base+7);
	}
}

void MAP40_Init(void)
{
	NES_Mapper->Reset=MAP40_Reset;
	NES_Mapper->Write=MAP40_MemoryWrite;
}
