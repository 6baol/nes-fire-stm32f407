#include "nes_mapper.h"

/* Mapper 16 (Bandai FCG-1/2, LZ93D50 without EEPROM). Responds at $6000-$7FFF
 * (FCG) and $8000-$FFFF (LZ93D50). The IRQ is a 16-bit M2 counter; here it is
 * clocked once per scanline with the equivalent cycle count. */
static uint8 reg016[16];
static uint16 latch016,counter016;
static uint8 irq016_enabled,irq016_pending;

void MAP16_IRQLevel(void)
{
    cpuirq=(irq016_enabled&&irq016_pending)?1:0;
}
void MAP16_HSync(int scanline)
{
    (void)scanline;
    if(!irq016_enabled)return;
    if(counter016>114) counter016-=(uint16)114;
    else counter016=0;
    if(counter016==0) irq016_pending=1;
    MAP16_IRQLevel();
}
static void map016_chr(void)
{
    set_PPU_banks(reg016[0],reg016[1],reg016[2],reg016[3],
                  reg016[4],reg016[5],reg016[6],reg016[7]);
}
static void map016_prg(void)
{
    unsigned bank=(unsigned)reg016[8]*2;
    set_CPU_banks(bank,bank+1,num_8k_ROM_banks-2,num_8k_ROM_banks-1);
}
void MAP16_Reset(void)
{
    unsigned i;
    memset(reg016,0,sizeof(reg016));
    for(i=0;i<8;i++)reg016[i]=(uint8)i;
    latch016=counter016=0;irq016_enabled=irq016_pending=0;
    set_mirroring(0,0,1,1);
    MAP16_IRQLevel();
    map016_chr();
    map016_prg();
}
void MAP16_Write(uint16 addr,uint8 data)
{
    uint16 masked;
    unsigned reg;
    /* FCG-1/2 decodes only $6000-$600F, LZ93D50 only $8000-$800F. Anything
     * else is cartridge RAM or ROM and must not touch the registers. */
    if(addr<=0x600F) masked=addr;
    else if(addr>=0x8000&&addr<=0x800F) masked=addr;
    else return;
    reg=masked&0x0F;
    if(reg<8){
        reg016[reg]=data;
        map016_chr();
    } else if(reg==8){
        reg016[8]=data&0x0F;
        map016_prg();
    } else if(reg==9){
        switch(data&3){
            case 0: set_mirroring(0,0,1,1);break;
            case 1: set_mirroring(0,1,0,1);break;
            case 2: set_mirroring(0,0,0,0);break;
            default:set_mirroring(1,1,1,1);break;
        }
    } else if(reg==0x0A){
        irq016_enabled=(uint8)(data&1);
        counter016=latch016;
        irq016_pending=0;
        MAP16_IRQLevel();
    } else if(reg==0x0B){
        latch016=(uint16)((latch016&0xFF00u)|data);
    } else if(reg==0x0C){
        latch016=(uint16)((latch016&0x00FFu)|((uint16)data<<8));
    }
}
void MAP16_Init(void)
{
    NES_Mapper->Reset=MAP16_Reset;
    NES_Mapper->Write=MAP16_Write;
    NES_Mapper->WriteLow=MAP16_Write;
    NES_Mapper->HSync=MAP16_HSync;
}
