#include "nes_mapper.h"

/* Mapper 117 (Future Media: San Guo Zhi 4 / Crayon Shin-Chan).
 * Three 8 KiB PRG banks at $8000/$A000/$C000, $E000 fixed to the last bank,
 * eight 1 KiB CHR banks and a scanline IRQ. */
static uint8 prg117[3];
static uint8 chr117[8];
static uint8 irq_latch117,irq_counter117,irq_enabled117,irq_pending117;

static void map117_prg(void)
{
    set_CPU_banks(prg117[0],prg117[1],prg117[2],num_8k_ROM_banks-1);
}
static void map117_chr(void)
{
    set_PPU_banks(chr117[0],chr117[1],chr117[2],chr117[3],
                  chr117[4],chr117[5],chr117[6],chr117[7]);
}
void MAP117_IRQLevel(void)
{
    cpuirq=(irq_enabled117&&irq_pending117)?1:0;
}
void MAP117_HSync(int scanline)
{
    (void)scanline;
    if(!irq_enabled117)return;
    if(irq_counter117==0) irq_counter117=irq_latch117;
    else irq_counter117--;
    if(irq_counter117==0) irq_pending117=1;
    MAP117_IRQLevel();
}
void MAP117_Reset(void)
{
    prg117[0]=0;prg117[1]=1;prg117[2]=2;
    {unsigned i;for(i=0;i<8;i++)chr117[i]=(uint8)i;}
    irq_latch117=irq_counter117=irq_enabled117=irq_pending117=0;
    set_mirroring(0,1,0,1);         /* horizontal */
    MAP117_IRQLevel();
    map117_prg();
    map117_chr();
}
void MAP117_Write(uint16 addr,uint8 data)
{
    if(addr<=0x8002) {
        prg117[addr&3]=data;
        map117_prg();
    } else if(addr>=0xA000 && addr<=0xA007) {
        chr117[addr&7]=data;
        map117_chr();
    } else if(addr>=0xA008 && addr<=0xA00F) {
        /* documented as unknown; Crayon Shin-Chan writes $01 here */
    } else if(addr==0xC001) {
        irq_latch117=data;
    } else if(addr==0xC002) {
        irq_pending117=0;
        MAP117_IRQLevel();
    } else if(addr==0xC003) {
        irq_counter117=irq_latch117;
    } else if(addr==0xD000) {
        if(data&1) set_mirroring(0,1,0,1);   /* vertical */
        else set_mirroring(0,0,1,1);         /* horizontal */
    } else if(addr==0xE000) {
        irq_enabled117=(uint8)(data&1);
        irq_pending117=0;
        MAP117_IRQLevel();
    }
}
void MAP117_Init(void)
{
    NES_Mapper->Reset=MAP117_Reset;
    NES_Mapper->Write=MAP117_Write;
    NES_Mapper->HSync=MAP117_HSync;
}
