#ifndef NES_MMC5_AUDIO_H
#define NES_MMC5_AUDIO_H
#include "nes_main.h"
void Mmc5Audio_Reset(void);
void Mmc5Audio_Write(u16 address,u8 value);
void Mmc5Audio_Apply(u16 address,u8 value);
u8 Mmc5Audio_Read(u16 address);
void Mmc5Audio_Tick(u32 cycles);
int Mmc5Audio_Sample(u32 cycles_fixed);
#endif
