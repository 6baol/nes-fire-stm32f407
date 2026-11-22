#include "nes_mmc5.h"
#include "nes_mapper.h"
#include "nes_mmc5_audio.h"

/* Restricted 8 KiB WRAM board profile. CHR remains in the preloaded ROM;
 * decoded tiles use a 64 KiB direct-mapped cache instead of duplicating CHR. */
static u8 m5_prg_mode,m5_chr_mode,m5_prg[5],m5_protect[2];
static u16 m5_chr[12];
static u8 m5_upper,m5_last_chr,m5_exmode,m5_nt,m5_fill_tile,m5_fill_color;
static u8 m5_exram[1024],m5_fill[1024],m5_zero[1024];
static u16 m5_tile_keys[4096];
volatile u32 nes_mmc5_cache_misses;
static u8 m5_target,m5_enabled,m5_pending,m5_in_frame,m5_count;
static u8 m5_mul[2],m5_split,m5_split_scroll,m5_split_bank;
static u8 m5_ram_windows;
u8 mmc5_ram_write_allowed;
extern u32 cpu_data[];

void MAP5_IRQLevel(void){cpuirq=(m5_enabled&&m5_pending)?1:0;}
void MAP5_Line(int line)
{
    if(line>=240 || !(bg_enabled()||spr_enabled())){m5_in_frame=0;return;}
    if(!m5_in_frame){m5_in_frame=1;m5_count=0;m5_pending=0;}
    else {++m5_count;if(m5_count==m5_target)m5_pending=1;}
    MAP5_IRQLevel();
}
static void MAP5_MapWindow(unsigned page,unsigned bank,int rom)
{
    if(rom) {
        switch(page){case 4:map89_(bank);break;case 5:mapAB_(bank);break;
                     case 6:mapCD_(bank);break;default:mapEF_(bank);break;}
    } else {
        cpu_data[17+page]=(u32)(uintptr_t)NES_SRAM-page*8192u;
        m5_ram_windows|=(u8)(1u<<page);
    }
}
static void MAP5_UpdatePrg(void)
{
    unsigned page,reg,span,bank;int rom;
    m5_ram_windows=0;
    for(page=4;page<8;page++) {
        if(m5_prg_mode==0){reg=4;span=4;}
        else if(m5_prg_mode==1){reg=page<6?2:4;span=2;}
        else if(m5_prg_mode==2&&page<6){reg=2;span=2;}
        else {reg=page-3;span=1;}
        bank=(m5_prg[reg]&0x7f)&~(span-1u);bank+=page&(span-1u);
        rom=reg==4 || (m5_prg[reg]&0x80);
        MAP5_MapWindow(page,bank,rom);
    }
    mmc5_ram_write_allowed=((m5_protect[0]&3)==2 && (m5_protect[1]&3)==1);
}
static unsigned MAP5_ChrBank(unsigned address,int set_b)
{
    unsigned page=address>>10,span=8u>>m5_chr_mode,index;
    if(set_b){if(span<8)page&=3;index=8+((page|((span>4?4:span)-1))&3);}
    else index=page|(span-1);
    return ((unsigned)m5_chr[index]*span+(page&(span-1)))&(VROM_1K_SIZE-1);
}
static void MAP5_UpdateChr(void)
{
    unsigned i;
    for(i=0;i<8;i++)ppu->PPU_VRAM_banks[i]=VROM_banks+MAP5_ChrBank(i*1024,(ppu->LowRegs[0]&32)&&m5_last_chr)*1024;
}
static void MAP5_UpdateNt(void)
{
    unsigned i;memset(m5_fill,m5_fill_tile,960);
    memset(m5_fill+960,(m5_fill_color&3)*0x55,64);
    for(i=0;i<4;i++) {
        unsigned source=(m5_nt>>(i*2))&3;
        ppu->PPU_VRAM_banks[8+i]=source<2?ppu->PPU_nametables+source*1024:
            source==3?m5_fill:(m5_exmode==0?m5_exram:m5_zero);
    }
}
static u8 *MAP5_Decode(unsigned address)
{
    unsigned key=(address>>4)&((VROM_1K_SIZE*1024u/16)-1),slot=key&4095;
    u8 *dest=(u8*)0x6c000000+slot*16;
    if(m5_tile_keys[slot]!=key){compile(1,VROM_banks+key*16,dest);m5_tile_keys[slot]=(u16)key;++nes_mmc5_cache_misses;}
    return dest;
}
u8 *MAP5_Tile(u32 address,int background,u32 nt,u32 screen_tile,u32 *palette,u32 *row)
{
    unsigned bank;
    if(background && (m5_split&0x80) && m5_exmode<2 &&
       (((screen_tile>=(m5_split&31))?1:0)==((m5_split>>6)&1))) {
        unsigned y=(ppu->current_frame_line+m5_split_scroll)%240,x=screen_tile&31;
        unsigned tile=m5_exram[(y/8)*32+x];
        unsigned attr=m5_exram[960+(y/32)*8+x/4];
        *palette=((attr>>(((y/8)&2)*2+(x&2)))&3)*4;*row=y&7;
        return MAP5_Decode((m5_split_bank*4096u+tile*16)&(VROM_1K_SIZE*1024u-1));
    }
    if(background && m5_exmode==1) {
        unsigned ex=m5_exram[nt&1023];*palette=(ex>>6)*4;
        address=(((ex&63)|((unsigned)m5_upper<<6))*4096)+(address&4095);
    } else {
        bank=MAP5_ChrBank(address,background&&(ppu->LowRegs[0]&32));
        address=bank*1024+(address&1023);
    }
    return MAP5_Decode(address);
}
u8 MAP5_PpuRead(u32 address)
{
    if(address<8192) return VROM_banks[MAP5_ChrBank(address,(ppu->LowRegs[0]&32)&&m5_last_chr)*1024+(address&1023)];
    return ppu->PPU_VRAM_banks[address>>10][address&1023];
}
void MAP5_PpuWrite(u32 address,u8 data)
{
    unsigned source;
    if(address<8192)return;
    source=(m5_nt>>(((address>>10)&3)*2))&3;
    if(source<2 || (source==2 && m5_exmode==0))ppu->PPU_VRAM_banks[address>>10][address&1023]=data;
}
static u8 MAP5_ReadLow(u16 address)
{
    if(address==0x5010||address==0x5015)return Mmc5Audio_Read(address);
    if(address>=0x5c00)return m5_exmode>=2?m5_exram[address&1023]:0;
    if(address==0x5204){u8 v=(m5_pending?128:0)|(m5_in_frame?64:0);m5_pending=0;MAP5_IRQLevel();return v;}
    if(address==0x5205)return (u8)(m5_mul[0]*m5_mul[1]);
    if(address==0x5206)return (u8)((m5_mul[0]*m5_mul[1])>>8);
    return 0;
}
static void MAP5_Write(u16 address,u8 data)
{
    if((address>=0x5000&&address<=0x5007)||address==0x5010||address==0x5011||address==0x5015){Mmc5Audio_Write(address,data);return;}
    if(address>=0x8000) {
        if((m5_ram_windows&(1u<<(address>>13)))&&mmc5_ram_write_allowed)NES_SRAM[address&8191]=data;
        return;
    }
    if(address>=0x5c00) {
        if(m5_exmode<2)m5_exram[address&1023]=m5_in_frame?data:0;
        else if(m5_exmode==2)m5_exram[address&1023]=data;
        return;
    }
    if(address>=0x5113&&address<=0x5117){m5_prg[address-0x5113]=data;MAP5_UpdatePrg();return;}
    if(address>=0x5120&&address<=0x512b){m5_chr[address-0x5120]=data|((u16)m5_upper<<8);m5_last_chr=address>=0x5128;MAP5_UpdateChr();return;}
    switch(address) {
    case 0x5100:m5_prg_mode=data&3;MAP5_UpdatePrg();break;
    case 0x5101:m5_chr_mode=data&3;MAP5_UpdateChr();break;
    case 0x5102:case 0x5103:m5_protect[address-0x5102]=data;MAP5_UpdatePrg();break;
    case 0x5104:m5_exmode=data&3;MAP5_UpdateNt();break;
    case 0x5105:m5_nt=data;MAP5_UpdateNt();break;
    case 0x5106:m5_fill_tile=data;MAP5_UpdateNt();break;
    case 0x5107:m5_fill_color=data&3;MAP5_UpdateNt();break;
    case 0x5130:m5_upper=data&3;break;
    case 0x5200:m5_split=data;break;case 0x5201:m5_split_scroll=data;break;case 0x5202:m5_split_bank=data;break;
    case 0x5203:m5_target=data;break;case 0x5204:m5_enabled=data&128;MAP5_IRQLevel();break;
    case 0x5205:case 0x5206:m5_mul[address-0x5205]=data;break;
    default:break;
    }
}
static void MAP5_Reset(void)
{
    memset(m5_prg,0,sizeof(m5_prg));m5_prg[4]=0xff;
    memset(m5_chr,0,sizeof(m5_chr));memset(m5_exram,0,sizeof(m5_exram));
    memset(m5_tile_keys,0xff,sizeof(m5_tile_keys));memset(m5_zero,0,sizeof(m5_zero));
    nes_mmc5_cache_misses=0;
    m5_prg_mode=3;m5_chr_mode=0;m5_protect[0]=1;m5_protect[1]=2;
    m5_upper=m5_last_chr=m5_nt=m5_fill_tile=m5_fill_color=0;m5_exmode=3;
    m5_target=m5_enabled=m5_pending=m5_in_frame=m5_count=0;m5_mul[0]=m5_mul[1]=0;
    m5_split=m5_split_scroll=m5_split_bank=0;
    MAP5_UpdatePrg();MAP5_UpdateChr();MAP5_UpdateNt();MAP5_IRQLevel();
}
void MAP5_Init(void)
{NES_Mapper->Reset=MAP5_Reset;NES_Mapper->Write=MAP5_Write;NES_Mapper->WriteLow=MAP5_Write;NES_Mapper->ReadLow=MAP5_ReadLow;}
