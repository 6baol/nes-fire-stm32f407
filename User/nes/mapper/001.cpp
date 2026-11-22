#include "nes_mapper.h"

/* Basic MMC1B: <=256 KiB PRG, <=128 KiB CHR ROM or 8 KiB CHR RAM,
 * one 8 KiB WRAM bank. No SUROM/SOROM/SXROM outer banks or save persistence. */
static uint8 mmc1_shift,mmc1_count,mmc1_control,mmc1_chr0,mmc1_chr1,mmc1_prg;
uint8 mmc1_sram_enabled;

static void MAP1_Update(void)
{
    unsigned mode=(mmc1_control>>2)&3,lo,hi;
    unsigned bank=mmc1_prg&15,last=RomHeader->num_16k_rom_banks-1;
    if(mode<2){lo=bank&~1u;hi=lo+1;}
    else if(mode==2){lo=0;hi=bank;}
    else {lo=bank;hi=last;}
    set_CPU_banks(lo*2,lo*2+1,hi*2,hi*2+1);
    switch(mmc1_control&3){
        case 0:set_mirroring(0,0,0,0);break;
        case 1:set_mirroring(1,1,1,1);break;
        case 2:set_mirroring(0,1,0,1);break;
        default:set_mirroring(0,0,1,1);break;
    }
    lo=(mmc1_chr0&((mmc1_control&16)?31:30))*4;
    hi=(mmc1_control&16)?mmc1_chr1*4:lo+4;
    /* Both raw CHR pointers and decoded tiles must change together. */
    set_PPU_banks(lo,lo+1,lo+2,lo+3,hi,hi+1,hi+2,hi+3);
    mmc1_sram_enabled=!(mmc1_prg&16);
    /* With the supported CHR-RAM configuration this is SNROM's extra gate. */
    if(!RomHeader->num_8k_vrom_banks && (mmc1_chr0&16))mmc1_sram_enabled=0;
}
void MAP1_Reset(void)
{
    mmc1_shift=mmc1_count=mmc1_chr0=mmc1_chr1=mmc1_prg=0;
    mmc1_control=0x0c;
    MAP1_Update();
}
void MAP1_MemoryWrite(uint16 addr,uint8 data)
{
    if(data&0x80){mmc1_shift=mmc1_count=0;mmc1_control|=0x0c;MAP1_Update();return;}
    mmc1_shift|=(data&1)<<mmc1_count;
    if(++mmc1_count!=5)return;
    /* The fifth write's address selects the destination, not the first. */
    switch((addr>>13)&3){
        case 0:mmc1_control=mmc1_shift;break;
        case 1:mmc1_chr0=mmc1_shift;break;
        case 2:mmc1_chr1=mmc1_shift;break;
        default:mmc1_prg=mmc1_shift;break;
    }
    mmc1_shift=mmc1_count=0;MAP1_Update();
}
void MAP1_Init(void)
{NES_Mapper->Reset=MAP1_Reset;NES_Mapper->Write=MAP1_MemoryWrite;}
