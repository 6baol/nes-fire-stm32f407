#include "nes_mapper.h"

/* Mapper 33 (Taito TC0190): 8K PRG registers at $8000/$A000 with the last two
 * banks fixed, 2K CHR at $0000/$0800 and four 1K CHR banks. No IRQ. */
static uint8 reg033[8];

static void map033_prg(void)
{
    set_CPU_banks(reg033[0],reg033[1],num_8k_ROM_banks-2,num_8k_ROM_banks-1);
}
static void map033_chr(void)
{
    set_PPU_banks(reg033[2]*2,reg033[2]*2+1,reg033[3]*2,reg033[3]*2+1,
                  reg033[4],reg033[5],reg033[6],reg033[7]);
}
void MAP33_Reset(void)
{
    memset(reg033,0,sizeof(reg033));
    reg033[3]=1;
    reg033[4]=0;reg033[5]=1;reg033[6]=2;reg033[7]=3;
    set_mirroring(0,1,0,1);            /* vertical */
    map033_prg();
    map033_chr();
}
void MAP33_Write(uint16 addr,uint8 data)
{
    switch(addr&0xA003) {
        case 0x8000:
            reg033[0]=data&0x3F;
            if(data&0x40) set_mirroring(0,0,1,1);   /* horizontal */
            else set_mirroring(0,1,0,1);            /* vertical */
            map033_prg();
            break;
        case 0x8001: reg033[1]=data; map033_prg(); break;
        case 0x8002: reg033[2]=data; map033_chr(); break;
        case 0x8003: reg033[3]=data; map033_chr(); break;
        case 0xA000: reg033[4]=data; map033_chr(); break;
        case 0xA001: reg033[5]=data; map033_chr(); break;
        case 0xA002: reg033[6]=data; map033_chr(); break;
        case 0xA003: reg033[7]=data; map033_chr(); break;
        default: break;
    }
}
void MAP33_Init(void)
{
    NES_Mapper->Reset=MAP33_Reset;
    NES_Mapper->Write=MAP33_Write;
}
