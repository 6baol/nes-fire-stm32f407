#include "nes_main.h"
#include "nes_ppu.h"
#include "nes_mapper.h"
#include "nes_port.h"
#include "nes_apu.h"
#include "nes_fds.h"
#include "nes_fds_bios.h"
#include "nes_mmc5.h"
#include "nes_mmc5_audio.h"
/* Static storage, no allocator. CHR ROM is copied to external SRAM so old
 * core code cannot modify Flash. Decoded tiles have a separate buffer. */
static _Alignas(1024) u8 cpu_ram[2048];
static u8 save_ram[8192],oam[256];
static ppu_data ppu_state;
static NES_header header;
static MAPPER mapper;
u8 *NES_RAM=cpu_ram,*NES_SRAM=save_ram,*spr_ram=oam;
ppu_data *ppu=&ppu_state;
NES_header *RomHeader=&header;
MAPPER *NES_Mapper=&mapper;
Mapper1Res *MAP1; MapperCommRes *MAPx;
u8 *VROM_banks,*VROM_tiles,*romfile;
u8 PADdata,PADdata1;
int MapperNo,NES_scanline,VROM_1K_SIZE,VROM_8K_SIZE;
volatile u32 nes_faults;
static apu_t apu_state;
apu_t *apu=&apu_state;
extern u32 clocks;
extern volatile u32 nes_apu_queue_drops;
extern u32 cpu_data[];
static int power2(unsigned n) {return n && !(n&(n-1));}
extern void cpu_reset_now(void);
extern void MAP4_IRQLevel(void);
static void fds_restore_dispatch(void);
int Nes_Load(const u8 *data,u32 size)
{
    u32 prg,chr,needed;
    if(data && size>=4 && (!memcmp(data,"FDS\x1a",4) ||
       (size>=15 && data[0]==1 && !memcmp(data+1,"*NINTENDO-HVC*",14)))) {
        return Nes_LoadDisk(data,size,nes_fds_bios,nes_fds_bios_size);
    }
    if(!data || size<16 || memcmp(data,"NES\x1a",4)) return 1;
    if((data[7]&0x0c) || (data[6]&0x0c)) return 2; /* NES2, trainer, 4-screen (battery is harmless) */
    if((data[9]&1) || (data[7]&3)) return 2; /* NTSC standard console only */
    prg=(u32)data[4]*16384;chr=(u32)data[5]*8192;
    needed=16+prg+chr;
    if(!power2(data[4]) || size!=needed) return 3;
    MapperNo=(data[6]>>4)|(data[7]&0xf0);
    if(MapperNo!=0 && MapperNo!=1 && MapperNo!=2 && MapperNo!=3 && MapperNo!=4 && MapperNo!=5 && MapperNo!=7 && MapperNo!=11 && MapperNo!=40 && MapperNo!=66 && MapperNo!=71 && MapperNo!=74 && MapperNo!=117 && MapperNo!=33) return 4;
    if(chr>((MapperNo==5||MapperNo==4||MapperNo==74||MapperNo==117||MapperNo==33||MapperNo==16)?262144u:131072u))return 3;
    if(MapperNo==5 && (data[4]>32 || !power2(data[5]) || data[8]>1 || size>896u*1024u))return 3;
    if(MapperNo==2 && (data[4]>32 || chr)) return 3;
    if((MapperNo==0 || MapperNo==3) && data[4]>2) return 3;
    if(MapperNo==1 && (data[4]>16 || data[8]>1 ||
       (data[5] && (!power2(data[5]) || data[5]>16)))) return 3;
    if(MapperNo==7 && (data[4]<2 || data[4]>16 || chr || data[8] || (data[6]&2)))return 3;
    if((MapperNo==11 || MapperNo==66) && (data[4]<2 || data[4]>8 ||
       !power2(data[5]) || data[5]>(MapperNo==11?16:4) || data[8] || (data[6]&2)))return 3;
    if(MapperNo==71 && (data[4]<2 || data[4]>16 || chr || data[8] || (data[6]&2)))return 3;
    if(MapperNo==4 && (data[4]<2 || data[4]>32 ||
       (data[5] && (!power2(data[5]) || data[5]>32)))) return 3;
    if(MapperNo==0 && data[5]>1) return 3;
    if(MapperNo==3 && (!power2(data[5]) || data[5]>16)) return 3;
    if(MapperNo==40 && (data[4]>4 || !data[5] || !power2(data[5]) || data[5]>8)) return 3;
    if((MapperNo==74 || MapperNo==117) && (data[4]<2 || data[4]>32 || !data[5] ||
       !power2(data[5]) || data[5]>32 || data[8])) return 3;
    if(MapperNo==16 && (data[4]<2 || data[4]>16 || !data[5] ||
       !power2(data[5]) || data[5]>32 || data[8]>1)) return 3;
    if(MapperNo==33 && (data[4]<2 || data[4]>32 || !data[5] ||
       !power2(data[5]) || data[5]>32 || data[8])) return 3;
    /* Every mapper we support maps PRG at $8000-$FFFF, so the reset vector has
     * to point into that window. Raw FDS dumps wrapped in an iNES header leave
     * $FFFC pointing at $6000-$7FFF (the FDS RAM window), which would just run
     * zeros and show a black screen - reject them instead. */
    {
        const u8 *vec=data+16+((MapperNo==7 || MapperNo==11 || MapperNo==66)?32768:prg)-4;
        u32 reset=(u32)vec[0]|((u32)vec[1]<<8);
        if(reset<0x8000) return 5;
    }
    fds_restore_dispatch();
    FdsDrive_Unmount();
    memcpy(&header,data,16);romfile=(u8*)data;
    /* Mapper 40 games are FDS conversions: the 8 KiB "CHR ROM" is really CHR
     * RAM that the game fills at run time through $2007, so keep the image as
     * the power-on contents but leave it writable. */
    if(MapperNo==40) header.num_8k_vrom_banks=0;
    memset(cpu_ram,0,sizeof(cpu_ram));memset(save_ram,0,sizeof(save_ram));
    memset(oam,0xff,sizeof(oam));memset(ppu,0,sizeof(*ppu));memset(&mapper,0,sizeof(mapper));
    VROM_banks=(u8*)0x6c000000;VROM_tiles=(u8*)0x6c020000;chr_large=0;
    if(MapperNo==5) {
        VROM_banks=(u8*)data+16+prg;VROM_tiles=(u8*)0x6c000000;
    } else if(chr>131072) {
        /* Big CHR stays in the ROM image; tile_ptr decodes 1 KiB banks into
         * the first 8 KiB of VROM_tiles on demand. */
        VROM_banks=(u8*)data+16+prg;VROM_tiles=(u8*)0x6c020000;
        memset(VROM_tiles,0,8192);chr_large=1;
    } else {
        memset(VROM_banks,0,131072);memset(VROM_tiles,0,131072);
        if(chr) memcpy(VROM_banks,data+16+prg,chr);
        if(chr) compile(chr/16,VROM_banks,VROM_tiles);
    }
    VROM_8K_SIZE=data[5]?data[5]:(MapperNo==1 || MapperNo==4 || MapperNo==7 || MapperNo==71);
    VROM_1K_SIZE=VROM_8K_SIZE*8;
    PPU_reset();cpu6502_init();Mapper_Init();cpu_reset_now();
    clocks=0;nes_apu_queue_drops=0;apu_init();
    PADdata=PADdata1=0;nes_faults=0;
    return 0;
}

/* ---------------------------------------------------------------------------
 * FDS style image: a 32 KiB snapshot of the disk system's PRG RAM plus the
 * 8 KiB BIOS.  $6000-$DFFF becomes writable PRG RAM and $E000-$FFFF the BIOS,
 * This experimental loader has timer I/O but does not implement a disk drive
 * or transfers. A wrapped iNES file is not necessarily a valid snapshot.
 * ------------------------------------------------------------------------- */
extern void prgram_R(void),prgram_W(void),cpu_reset_now(void),cpu_start_fds(u32);
/* $6000-$DFFF is writable on an FDS, so it cannot live in Flash. Internal SRAM
 * keeps the per-access cost the same as the cartridge RAM path. */
static _Alignas(32) u8 fds_storage[32784];
#define fds_prgram (fds_storage+16)
static u32 saved_reads[4],saved_writes[4];
static u8 fds_map_active;
static void fds_restore_dispatch(void)
{
    unsigned i;
    if(!fds_map_active)return;
    for(i=0;i<4;i++) {
        cpu_data[1+3+i]=saved_reads[i];
        cpu_data[9+3+i]=saved_writes[i];
    }
    fds_map_active=0;
}

static void fds_install_map(u8 *prgram,const u8 *bios)
{
    /* cpu_data layout: opz, readmem_tbl[8], writemem_tbl[8], memmap_tbl[8] ... */
    u32 *read_tbl=cpu_data+1,*write_tbl=cpu_data+9,*map=cpu_data+17;
    u32 base=(u32)prgram,rom=(u32)bios;
    int i;
    if(!fds_map_active)for(i=3;i<=6;i++) {
        saved_reads[i-3]=read_tbl[i];saved_writes[i-3]=write_tbl[i];
    }
    fds_map_active=1;
    for(i=3;i<=6;i++) {
        read_tbl[i]=(u32)prgram_R;
        write_tbl[i]=(u32)prgram_W;
    }
    for(i=3;i<=6;i++)map[i]=base-0x6000; /* one contiguous 32KiB RAM window */
    map[7]=rom-0xE000;              /* $E000-$FFFF reads the BIOS, writes hit void */
}
int Nes_LoadFds(const u8 *data,u32 size,const u8 *bios,u32 bios_size)
{
    u8 *prgram=fds_prgram;
    u32 prg,chr;
    if(!data || !bios || bios_size!=8192 || size<16 || memcmp(data,"NES\x1a",4)) return 6;
    prg=(u32)data[4]*16384u;chr=(u32)data[5]*8192u;
    if(prg!=32768u || size!=16+prg+chr || chr>8192u ||
       (data[6]&0x0c) || (data[7]&0x0f) || (data[9]&1)) return 6;
    /* Require an explicit in-RAM entry before changing any live core state. */
    {
        u32 entry=(u32)data[16+0x7FFC]|((u32)data[16+0x7FFD]<<8);
        if(entry<0x6000 || entry>=0xE000) return 6;
    }
    MapperNo=20;
    FdsDrive_Unmount();
    memset(&header,0,sizeof(header));
    header.num_16k_rom_banks=2;     /* rombase/rommask are overridden by the map */
    header.num_8k_vrom_banks=0;     /* the 8 KiB CHR is CHR RAM, writable at run time */
    romfile=(u8*)data; /* bootstrap CPU with a valid iNES header before remapping */
    memset(cpu_ram,0,sizeof(cpu_ram));memset(save_ram,0,sizeof(save_ram));
    memset(oam,0xff,sizeof(oam));memset(ppu,0,sizeof(*ppu));memset(&mapper,0,sizeof(mapper));
    VROM_banks=(u8*)0x6c000000;VROM_tiles=(u8*)0x6c020000;chr_large=0;
    memset(VROM_banks,0,131072);memset(VROM_tiles,0,131072);
    if(chr) {
        memcpy(VROM_banks,data+16+prg,chr);
        compile(chr/16,VROM_banks,VROM_tiles);
    }
    VROM_1K_SIZE=8;VROM_8K_SIZE=1;
    memset(prgram,0,32768);memcpy(prgram,data+16,32768);
    PPU_reset();Mapper_Init();cpu6502_init();
    fds_install_map(prgram,bios);
    cpu_reset_now();                /* fetch $FFFC again through the new map */
    /* The snapshot is the state the BIOS leaves behind after loading the game
     * file, and its $DFFC pointer is that file's entry point.  Jump straight
     * there instead of letting the BIOS poll a disk drive we do not have:
     * $DFFC sits at image offset $7FFC. */
    {
        u32 entry=(u32)prgram[0x7FFC]|((u32)prgram[0x7FFD]<<8);
        if(entry>=0x6000 && entry<0xE000) cpu_start_fds(entry);
    }
    clocks=0;nes_apu_queue_drops=0;apu_init();
    PADdata=PADdata1=0;nes_faults=0;
    return 0;
}
int Nes_LoadDisk(const u8 *data,u32 size,const u8 *bios,u32 bios_size)
{
    FdsImage disk;
    u32 crc=0xffffffffu,i,bit;
    if(FdsImage_Open(&disk,data,size))return 8;
    if(!bios || bios_size!=8192)return 6;
    for(i=0;i<8192;i++) {
        crc^=bios[i];
        for(bit=0;bit<8;bit++)crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u);
    }
    /* Known corrupt BIOS extracted by the previous conversion: the executable
     * refresh block at $F800 was overwritten with game data. Preserve the file,
     * but do not run this image. Custom/replacement BIOS images remain allowed. */
    if((crc^0xffffffffu)==0x01d8e343u)return 9;
    if(((u32)bios[0x1ffc]|((u32)bios[0x1ffd]<<8))<0xe000)return 6;
    fds_restore_dispatch();FdsDrive_Unmount();
    MapperNo=20;
    memset(&header,0,sizeof(header));header.num_16k_rom_banks=2;
    memset(fds_storage,0,sizeof(fds_storage));
    memcpy(fds_storage,"NES\x1a\x02",5);romfile=fds_storage;
    memset(cpu_ram,0,sizeof(cpu_ram));memset(save_ram,0,sizeof(save_ram));
    memset(oam,0xff,sizeof(oam));memset(ppu,0,sizeof(*ppu));memset(&mapper,0,sizeof(mapper));
    VROM_banks=(u8*)0x6c000000;VROM_tiles=(u8*)0x6c020000;chr_large=0;
    memset(VROM_banks,0,131072);memset(VROM_tiles,0,131072);
    VROM_1K_SIZE=8;VROM_8K_SIZE=1;
    PPU_reset();Mapper_Init();cpu6502_init();fds_install_map(fds_prgram,bios);
    if(FdsDrive_Mount(&disk,0))return 8;
    cpu_reset_now();
    clocks=0;nes_apu_queue_drops=0;apu_init();
    PADdata=PADdata1=0;nes_faults=0;
    return 0;
}
static void nes_run_cycles(u32 cycles)
{
    /* FDS uses <=16 CPU-cycle slices so byte IRQs are serviced before the next
     * byte arrives. This is still not instruction/cycle-accurate FDS timing. */
    if(MapperNo==20) {
        while(cycles) {
            u32 step=cycles>16?16:cycles;
            FdsIo_Tick(step);run6502(step*256);cycles-=step;
        }
    } else {
        if(MapperNo==4||MapperNo==74) MAP4_IRQLevel();
        if(MapperNo==117) MAP117_IRQLevel();
        if(MapperNo==16) MAP16_IRQLevel();
        if(MapperNo==5){Mmc5Audio_Tick(cycles);MAP5_IRQLevel();}
        run6502(cycles*256);
    }
}
void Nes_Frame(int draw)
{
    PPU_start_frame();
    for(NES_scanline=0;NES_scanline<240;NES_scanline++) {
        if(MapperNo==5)MAP5_Line(NES_scanline);
        nes_run_cycles(NES_scanline%3==2?113u:114u);
        if(draw) scanline_draw(NES_scanline); else do_scanline_and_dont_draw(NES_scanline);
        /* Scanline-core approximation: one MMC3 clock per rendered visible line,
         * independent of LCD submission, plus the pre-render line below. */
        if((MapperNo==4 && (bg_enabled() || spr_enabled())) || MapperNo==74 || MapperNo==117 || MapperNo==16)
            NES_Mapper->HSync(NES_scanline);
        if((NES_scanline&7)==0) NesPort_Input();
    }
    NES_scanline=240;if(MapperNo==5)MAP5_Line(240);nes_run_cycles(114);start_vblank();
    if(NMI_enabled()) cpunmi=1;
    for(NES_scanline=241;NES_scanline<262;NES_scanline++) {
        nes_run_cycles(NES_scanline%3==2?113u:114u);
        if(NES_scanline==261 && ((MapperNo==4 && (bg_enabled() || spr_enabled())) ||
           MapperNo==74 || MapperNo==117 || MapperNo==16))
            NES_Mapper->HSync(261);
        if((NES_scanline&7)==0) NesPort_Input();
    }
    end_vblank();
}
void debug_6502(u16 pc,u8 op) {(void)pc;(void)op;++nes_faults;}
/* DMA-side DMC reads use the CPU memory map without the custom ASM ABI. */
u8 Nes_ApuReadDmc(u16 addr)
{
    if(addr<0x2000)return NES_RAM[addr&0x7ff];
    if(addr>=0x6000&&addr<0x8000 && MapperNo!=20) {
        if(MapperNo==7 || MapperNo==11 || MapperNo==66 || MapperNo==71)return 0;
        return NES_SRAM[addr-0x6000];
    }
    if(addr>=0x8000 || (MapperNo==20 && addr>=0x6000)) {
        uintptr_t base=cpu_data[17+(addr>>13)];
        return *(const u8*)(base+addr);
    }
    return 0;
}
