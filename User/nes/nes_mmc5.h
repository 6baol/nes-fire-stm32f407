#ifndef NES_MMC5_H
#define NES_MMC5_H
#include "nes_main.h"
void MAP5_Init(void);
void MAP5_IRQLevel(void);
void MAP5_Line(int line);
u8 *MAP5_Tile(u32 address,int background,u32 nt,u32 screen_tile,u32 *palette,u32 *row);
u8 MAP5_PpuRead(u32 address);
void MAP5_PpuWrite(u32 address,u8 data);
extern u8 mmc5_ram_write_allowed;
#endif
