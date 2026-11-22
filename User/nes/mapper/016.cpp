#include "nes_mapper.h"

/* NESdev Bandai FCG: 16.4 uses the low window and direct counter writes,
 * 16.5 uses the high window and an IRQ latch. Neither supported board has
 * PRG RAM or EEPROM. IRQ assertion is checked at CPU slice boundaries. */
static uint8 reg016[16];
static uint16 latch016,counter016;
static uint8 irq016_enabled,irq016_pending;
static uint32 irq016_time;
extern u32 clocks;

static void map016_irq_level(void)
{
    cpuirq=(irq016_enabled&&irq016_pending)?1:0;
}
void MAP16_UpdateIRQ(void)
{
    uint32 elapsed=clocks-irq016_time;
    irq016_time=clocks;
    if(irq016_enabled) {
        if(elapsed>counter016)irq016_pending=1;
        counter016=(uint16)(counter016-elapsed);
    }
    map016_irq_level();
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
    irq016_time=0;
    map016_irq_level();
    map016_chr();
    map016_prg();
}
void MAP16_Write(uint16 addr,uint8 data)
{
    unsigned reg;
    uint16 *counter_register;
    if(nes_mapper16_submapper==4 ? (addr<0x6000||addr>=0x8000) : addr<0x8000)return;
    reg=addr&0x0F;
    if(reg<8){
        reg016[reg]=data;
        map016_chr();
    } else if(reg==8){
        reg016[8]=data&0x0F;
        map016_prg();
    } else if(reg==9){
        switch(data&3){
            case 0: set_mirroring(0,1,0,1);break;
            case 1: set_mirroring(0,0,1,1);break;
            case 2: set_mirroring(0,0,0,0);break;
            default:set_mirroring(1,1,1,1);break;
        }
    } else if(reg<=0x0C){
        MAP16_UpdateIRQ();
        if(reg==0x0A){
            irq016_enabled=(uint8)(data&1);
            if(nes_mapper16_submapper==5)counter016=latch016;
            irq016_pending=0;
            map016_irq_level();
        } else {
            counter_register=nes_mapper16_submapper==4?&counter016:&latch016;
            if(reg==0x0B)*counter_register=(uint16)((*counter_register&0xFF00u)|data);
            else *counter_register=(uint16)((*counter_register&0x00FFu)|((uint16)data<<8));
        }
    }
}
void MAP16_Init(void)
{
    NES_Mapper->Reset=MAP16_Reset;
    NES_Mapper->Write=MAP16_Write;
    NES_Mapper->WriteLow=MAP16_Write;
}
