//////////////////////////////////////////////////////////////////////////////////	 
//本程序移植自网友ye781205的NES模拟器工程		  
////////////////////////////////////////////////////////////////////////////////// 	 
#include "nes_mapper.h"


//根据自己需要添加其他map文件用.  
#include "mapper/000.cpp"
#include "mapper/001.cpp"

#include "mapper/002.cpp"
#include "mapper/003.cpp"
#include "mapper/004.cpp"
#include "mapper/005.cpp"
#include "mapper/007.cpp"
#include "mapper/011.cpp"
#include "mapper/020.cpp"
#include "mapper/040.cpp"
#include "mapper/066.cpp"
#include "mapper/071.cpp"
#include "mapper/074.cpp"
#include "mapper/117.cpp"
#include "mapper/033.cpp"
#include "mapper/016.cpp"







 










  
  
  
 
     
    
   
  
  
   
 







  



 
 


//支持的Mapper号,自己添加
const int MapTab[] = {0,1,2,3,4,5,7,11,20,40,66,71,-1};
#define MASK_BANK(bank,mask) (bank) = ((bank) & (mask))
#define VALIDATE_VROM_BANK(bank) \
		MASK_BANK(bank,VROM_mask); \
		if((bank) >= (uint32)VROM_1K_SIZE) return;
		
		
uint32 VROM_mask;  
/* CHR ROM above 128 KiB does not fit the decoded buffer. The raw CHR stays in
 * the ROM image and the eight visible 1 KiB banks are decoded into a slot
 * cache instead (same idea as the MMC5 path). */
uint8 chr_large;
static uint16 tile_key[8];
static uint8 *tile_ptr(unsigned slot,uint32 bank)
{
	if(!chr_large) return VROM_tiles + bank*0x400;
	if(tile_key[slot]!=(uint16)bank) {
		compile(64,VROM_banks+bank*1024,VROM_tiles+slot*1024);
		tile_key[slot]=(uint16)bank;
	}
	return VROM_tiles + slot*1024;
}

void Mapper_Reset(void){} 
uint8 Mapper_ReadLow(uint16 addr){(void)addr;return 0;}  
void Mapper_WriteLow(uint16 addr,uint8 data){(void)addr;(void)data;}
void Mapper_Write( uint16 addr , uint8 data){(void)addr;(void)data;}
void Mapper_Read( uint8 data,uint16 addr ){(void)data;(void)addr;}
void Mapper_HSync( int scanline ){(void)scanline;}  
void Mapper_VSync(void)  {}	
	
 void Mapper_Init(void)
{
	uint32 probe; 
	NES_Mapper->Reset         = Mapper_Reset;
	NES_Mapper->Write         = Mapper_Write;
	NES_Mapper->Read          = Mapper_Read;
	NES_Mapper->WriteLow      = Mapper_WriteLow;
	NES_Mapper->ReadLow       = Mapper_ReadLow;	
	NES_Mapper->HSync         = Mapper_HSync;
	NES_Mapper->VSync         = Mapper_VSync; 
	memset(tile_key,0xFF,sizeof(tile_key));
	VROM_mask = 0xFFFF; 
	for(probe = 0x8000; probe; probe >>= 1)
	{
		if((VROM_1K_SIZE-1) & probe) break;
		VROM_mask >>= 1;
	}
	
	switch (MapperNo)
	{
		case 0 :MAP0_Init();break;
		case 5 :MAP5_Init();break;
		case 1 :MAP1_Init();break;
		
 		case 2 :MAP2_Init();break;
 		case 3 :MAP3_Init();break;
	 		case 4 :MAP4_Init();break;
 		case 20:MAP20_Init();break;
		case 7 :MAP7_Init();break;
		case 11:MAP11_Init();break;
		case 66:MAP66_Init();break;
		case 71:MAP71_Init();break;
		case 74:MAP74_Init();break;
		case 117:MAP117_Init();break;
		case 33:MAP33_Init();break;
		case 16:MAP16_Init();break;
		case 40:MAP40_Init();break;
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		 
 		 
 		 
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		
 		 
		default:break;
	}
	NES_Mapper->Reset();
} 
static void mapper_write_direct(uint8 byData,uint16 wAddr)
{	
	NES_Mapper->Write(wAddr,byData);
}  
uint8 asm_Mapper_ReadLow( uint16 wAddr) //添加的
{	
	return NES_Mapper->ReadLow( wAddr);
} 
void asm_Mapper_WriteLow( uint8 byData ,uint16 wAddr) 
{	
	NES_Mapper->WriteLow(wAddr, byData );
}
volatile u32 nes_rmw_value;
/* The legacy core emits only the final RMW write. For MMC1 reconstruct the
 * original ROM-data write and suppress the following D0 write; D7 resets on
 * the second write still take effect. Only supported legal absolute RMWs
 * reach this path. GxROM must see both writes: the first can change the ROM
 * byte participating in the second bus conflict. */
void asm_Mapper_Write(uint8 data,uint16 addr)
{
    if(MapperNo==1 && (nes_rmw_value&0x100)) {
        MAP1_MemoryWrite(addr,(u8)nes_rmw_value);
        if(data&0x80)MAP1_MemoryWrite(addr,0x80);
    } else {
        if(MapperNo==66 && (nes_rmw_value&0x100))mapper_write_direct((u8)nes_rmw_value,addr);
        mapper_write_direct(data,addr);
    }
}

void set_CPU_bank3(signed char page )  {map67_(page) ;} 
void set_CPU_bank4(signed char page )  {map89_(page) ;} 
void set_CPU_bank5(signed char page )  {mapAB_(page) ;}
void set_CPU_bank6(signed char page )  {mapCD_(page) ;} 
void set_CPU_bank7(signed char page )  {mapEF_(page) ;}
void set_CPU_banks(int bank0_num,int bank1_num,int bank2_num, int bank3_num)
{
    map89_(bank0_num);
	mapAB_(bank1_num);
	mapCD_(bank2_num);
	mapEF_(bank3_num);
}
void set_PPU_banks(uint32 bank0_num, uint32 bank1_num,
				   uint32 bank2_num, uint32 bank3_num,
				   uint32 bank4_num, uint32 bank5_num,
				   uint32 bank6_num, uint32 bank7_num)
{
  VALIDATE_VROM_BANK(bank0_num);
  VALIDATE_VROM_BANK(bank1_num);
  VALIDATE_VROM_BANK(bank2_num);
  VALIDATE_VROM_BANK(bank3_num);
  VALIDATE_VROM_BANK(bank4_num);
  VALIDATE_VROM_BANK(bank5_num);
  VALIDATE_VROM_BANK(bank6_num);
  VALIDATE_VROM_BANK(bank7_num);

  ppu->PPU_VRAM_banks[0] = VROM_banks + (bank0_num << 10); // * 0x400
  ppu->PPU_VRAM_banks[1] = VROM_banks + (bank1_num << 10);
  ppu->PPU_VRAM_banks[2] = VROM_banks + (bank2_num << 10);
  ppu->PPU_VRAM_banks[3] = VROM_banks + (bank3_num << 10);
  ppu->PPU_VRAM_banks[4] = VROM_banks + (bank4_num << 10);
  ppu->PPU_VRAM_banks[5] = VROM_banks + (bank5_num << 10);
  ppu->PPU_VRAM_banks[6] = VROM_banks + (bank6_num << 10);
  ppu->PPU_VRAM_banks[7] = VROM_banks + (bank7_num << 10);
	
  set_tile_banks( tile_ptr(0,bank0_num),
				  tile_ptr(1,bank1_num),
				  tile_ptr(2,bank2_num),
				  tile_ptr(3,bank3_num),
				  tile_ptr(4,bank4_num),
				  tile_ptr(5,bank5_num),
				  tile_ptr(6,bank6_num),
				  tile_ptr(7,bank7_num) );
}
void set_PPU_bank0(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[0] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(0, tile_ptr(0, bank_num));
}

void set_PPU_bank1(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[1] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(1, tile_ptr(1, bank_num));
}

void set_PPU_bank2(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[2] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(2, tile_ptr(2, bank_num));
}

void set_PPU_bank3(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[3] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(3, tile_ptr(3, bank_num));
}

void set_PPU_bank4(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[4] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(4, tile_ptr(4, bank_num));
} 
void set_PPU_bank5(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[5] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(5, tile_ptr(5, bank_num));
}

void set_PPU_bank6(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[6] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(6, tile_ptr(6, bank_num));
}

void set_PPU_bank7(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[7] = VROM_banks + (bank_num << 10); // * 0x400
	set_tile_bank(7, tile_ptr(7, bank_num));
}
// for mapper 19,68,90
void set_PPU_bank8(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[8] = VROM_banks + (bank_num << 10);
}
void set_PPU_bank9(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[9] = VROM_banks + (bank_num << 10);
}
void set_PPU_bank10(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[10] = VROM_banks + (bank_num << 10);
}
void set_PPU_bank11(uint32 bank_num)
{
	VALIDATE_VROM_BANK(bank_num);
	ppu->PPU_VRAM_banks[11] = VROM_banks + (bank_num << 10);
}

// for mapper 1,4,5,6,13,19,80,85,96,119
void set_VRAM_bank(uint8 bank, uint32 bank_num)
{
	if(bank < 8)
	{        
		ppu->PPU_VRAM_banks[bank] = PPU_patterntables + ((bank_num & 0x0f) << 10);
	}
	else if(bank < 12)
	{
		set_name_table(bank, bank_num);
	}
}












