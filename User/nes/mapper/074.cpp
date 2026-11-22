#include "nes_mapper.h"

/* Mapper 74 (Waixing 43-393 / 860908C): an MMC3 clone whose 1 KiB CHR banks
 * #8 and #9 are wired to 2 KiB of CHR RAM. Everything else is MMC3. */
static uint8 map74_ram[2048];
static uint8 map74_tiles[2048];
static uint8 map74_slot[8];           /* 0/1 = RAM half, 0xFF = CHR ROM */

static unsigned map74_bank(unsigned slot)
{
    uint8 pair0=mmc3_regs[0]&0xFE,pair1=mmc3_regs[1]&0xFE;
    uint8 banks[8];
    if(mmc3_bank_select&0x80) {
        banks[0]=mmc3_regs[2];banks[1]=mmc3_regs[3];
        banks[2]=mmc3_regs[4];banks[3]=mmc3_regs[5];
        banks[4]=pair0;banks[5]=pair0+1;
        banks[6]=pair1;banks[7]=pair1+1;
    } else {
        banks[0]=pair0;banks[1]=pair0+1;
        banks[2]=pair1;banks[3]=pair1+1;
        banks[4]=mmc3_regs[2];banks[5]=mmc3_regs[3];
        banks[6]=mmc3_regs[4];banks[7]=mmc3_regs[5];
    }
    return banks[slot];
}
static void map74_update_chr(void)
{
    unsigned i;
    MAP4_UpdateChr();
    for(i=0;i<8;i++) {
        unsigned bank=map74_bank(i);
        if(bank==8||bank==9) {
            unsigned half=bank-8;
            map74_slot[i]=(uint8)half;
            ppu->PPU_VRAM_banks[i]=map74_ram+half*1024;
            set_tile_bank(i,map74_tiles+half*1024);
        } else {
            map74_slot[i]=0xFF;
        }
    }
}
void MAP74_Write(uint16 addr,uint8 data)
{
    MAP4_MemoryWrite(addr,data);
    map74_update_chr();
}
void MAP74_Reset(void)
{
    memset(map74_ram,0,sizeof(map74_ram));
    memset(map74_tiles,0,sizeof(map74_tiles));
    memset(map74_slot,0xFF,sizeof(map74_slot));
    MAP4_Reset();
    map74_update_chr();
}
void MAP74_Init(void)
{
    NES_Mapper->Reset=MAP74_Reset;
    NES_Mapper->Write=MAP74_Write;
    NES_Mapper->HSync=MAP4_HSync;
}
/* $2007 writes that land in the RAM window must update both the raw CHR RAM and
 * the decoded tile cache; CHR ROM windows stay read-only. */
int MAP74_PpuWrite(uint16 addr,uint8 data)
{
    unsigned slot=addr>>10;
    if(slot>=8||map74_slot[slot]==0xFF)return 0;
    map74_ram[map74_slot[slot]*1024+(addr&0x3FF)]=data;
    compile(64,map74_ram+map74_slot[slot]*1024,map74_tiles+map74_slot[slot]*1024);
    return 1;
}
