#include "nes_mapper.h"
#include "nes_fds.h"
#include "nes_fds_audio.h"

/* Read-only disk byte stream, timer I/O and expansion-audio register dispatch.
 * NESdev User:TakuikaNinja/FDS_Registers, timer IRQ acknowledgement semantics. */
static uint16_t fds_reload;
static uint32_t fds_counter;
static uint8_t fds_enable,fds_repeat,fds_pending,fds_io_enable;
/* Synthesized gaps/sync/CRC live outside CHR, decoded tiles and capture RAM. */
#ifdef NES_SD_LIBRARY
/* The source disk now lives in SRAM too. Keep its synthesized byte stream
 * disjoint from the source (8 FDS sides plus header fit below 0x6c0e0000).
 * Cartridge ROMs may reuse this region after FdsDrive_Unmount(). */
#define FDS_STREAM ((uint8_t*)0x6c0e0000)
#else
#define FDS_STREAM ((uint8_t*)0x6c060000)
#endif
#define FDS_STREAM_CAPACITY 0x20000u
static uint32_t disk_length,disk_position,disk_delay;
static uint8_t disk_control,disk_scanning,disk_gap,disk_byte,disk_transfer,disk_irq;
static FdsImage disk_image;
static uint8_t disk_side;
static uint32_t disk_insert_delay;
volatile uint32_t nes_fds_bytes,nes_fds_reads;
static void fds_irq_level(void) {cpuirq=(fds_pending||disk_irq)?1:0;}
void FdsDrive_Unmount(void)
{
    disk_length=0;disk_irq=0;disk_transfer=0;disk_insert_delay=0;
    memset(&disk_image,0,sizeof(disk_image));disk_side=0;fds_irq_level();
}
static uint16_t fds_crc(uint16_t crc,uint8_t byte)
{
    unsigned i;
    for(i=0;i<8;i++) {
        unsigned carry=crc&1u;crc>>=1;
        if(carry)crc^=0x8408;
        if(byte&(1u<<i))crc^=0x8000;
    }
    return crc;
}
static int fds_block(const uint8_t *p,uint32_t length,uint32_t *offset)
{
    uint32_t i,n=*offset;
    uint16_t crc=0;
    if(n>FDS_STREAM_CAPACITY-125u || length>FDS_STREAM_CAPACITY-n-125u)return 1;
    FDS_STREAM[n++]=0x80;crc=fds_crc(crc,0x80);
    for(i=0;i<length;i++) {FDS_STREAM[n++]=p[i];crc=fds_crc(crc,p[i]);}
    crc=fds_crc(fds_crc(crc,0),0);
    FDS_STREAM[n++]=(uint8_t)crc;FDS_STREAM[n++]=(uint8_t)(crc>>8);
    memset(FDS_STREAM+n,0,122);n+=122;*offset=n;
    return 0;
}
static int fds_insert(const FdsImage *image,unsigned side)
{
    const uint8_t *p;
    uint32_t offset=3537;
    unsigned i;
    FdsFile file;
    if(!image || side>=image->sides)return 1;
    disk_length=0;disk_irq=disk_transfer=0;fds_irq_level();
    p=image->data+image->header_size+side*FDS_SIDE_SIZE;
    memset(FDS_STREAM,0,3537);
    if(fds_block(p,56,&offset) || fds_block(p+56,2,&offset))return 1;
    for(i=0;i<p[57];i++) {
        if(FdsImage_File(image,side,i,&file))return 1;
        if(fds_block(file.data-17,16,&offset) || fds_block(file.data-1,(uint32_t)file.size+1,&offset))return 1;
    }
    disk_length=offset;disk_position=0;disk_delay=50000;
    disk_scanning=disk_gap=disk_transfer=disk_irq=0;
    nes_fds_bytes=nes_fds_reads=0;
    return 0;
}
int FdsDrive_Mount(const FdsImage *image,unsigned side)
{
    FdsImage copy;
    if(!image||side>=image->sides)return 1;
    copy=*image;
    FdsDrive_Unmount();disk_control=0;
    if(fds_insert(&copy,side))return 1;
    disk_image=copy;disk_side=(uint8_t)side;return 0;
}
unsigned FdsDrive_Sides(void){return disk_image.sides;}
unsigned FdsDrive_Side(void){return disk_side;}
int FdsDrive_Changing(void){return disk_insert_delay!=0;}
int FdsDrive_RequestSide(unsigned side)
{
    if(!disk_image.data||side>=disk_image.sides||disk_insert_delay)return 1;
    if(side==disk_side)return 0;
    /* About half a second in emulated NTSC CPU time gives the BIOS an
     * observable disk-removed status; no CPU/RAM/APU reset and no SD access. */
    disk_side=(uint8_t)side;disk_length=0;disk_irq=disk_transfer=disk_scanning=0;
    disk_position=0;disk_insert_delay=894887u;fds_irq_level();return 0;
}

__attribute__((noinline)) void FdsIo_Reset(void)
{
    fds_reload=0;fds_counter=0;fds_enable=fds_repeat=fds_pending=fds_io_enable=0;
    cpuirq=0;
    disk_control=disk_scanning=disk_gap=disk_transfer=disk_irq=0;
    disk_position=0;disk_delay=50000;
}
void FdsIo_Write(uint16_t address,uint8_t value)
{
    if(address==0x4023||(address>=0x4040&&address<=0x408a))FdsAudio_Write(address,value);
    switch(address) {
    case 0x4020: fds_reload=(uint16_t)((fds_reload&0xff00u)|value);break;
    case 0x4021: fds_reload=(uint16_t)((fds_reload&0x00ffu)|((unsigned)value<<8));break;
    case 0x4022:
        if(!(fds_io_enable&1))break;
        fds_repeat=value&1;fds_enable=value&2;
        if(fds_enable)fds_counter=(uint32_t)fds_reload+1u;
        else {fds_pending=0;fds_irq_level();}
        break;
    case 0x4023:
        fds_io_enable=value;
        if(!(value&1)) {fds_enable=0;fds_pending=0;disk_irq=0;fds_irq_level();}
        break;
    case 0x4024:
        if(fds_io_enable&1) {disk_irq=disk_transfer=0;fds_irq_level();}
        break; /* Read-only medium: no mutation of the embedded disk image. */
    case 0x4025:
        if(fds_io_enable&1) {
            disk_irq=0;disk_control=value;fds_irq_level();
            if(value&8)set_mirroring(0,0,1,1);
            else set_mirroring(0,1,0,1);
        }
        break;
    default:break;
    }
}
uint8_t FdsIo_Read(uint16_t address)
{
    if(address>=0x4040&&address<=0x4097)return FdsAudio_Read(address);
    if(address==0x4030) {
        uint8_t result=(uint8_t)(fds_pending|(disk_transfer?2:0));
        fds_pending=disk_irq=disk_transfer=0;fds_irq_level();return result;
    }
    if(address==0x4031) {
        disk_irq=disk_transfer=0;fds_irq_level();++nes_fds_reads;return disk_byte;
    }
    if(address==0x4032)return disk_length?(uint8_t)(4|(disk_scanning?0:2)):7;
    if(address==0x4033)return 0x80;
    return 0;
}
__attribute__((noinline)) void FdsIo_Tick(uint32_t cycles)
{
    if(disk_insert_delay) {
        if(cycles<disk_insert_delay)disk_insert_delay-=cycles;
        else {disk_insert_delay=0;(void)fds_insert(&disk_image,disk_side);}
    }
    if(fds_enable && cycles) {
        if(cycles<fds_counter)fds_counter-=cycles;
        else {
            uint32_t remaining=cycles-fds_counter;
            fds_pending=1;
            if(fds_repeat)fds_counter=(uint32_t)fds_reload+1u-remaining%((uint32_t)fds_reload+1u);
            else {fds_enable=0;fds_counter=0;}
        }
    }
    if(!disk_length || !(disk_control&1)) {
        disk_scanning=0;disk_position=0;disk_delay=50000;disk_gap=0;
    } else if(!(disk_control&2) || disk_scanning) {
        uint32_t elapsed=cycles;
        while(elapsed>=disk_delay && disk_position<disk_length) {
            uint8_t byte;
            elapsed-=disk_delay;disk_delay=150;disk_scanning=1;
            byte=FDS_STREAM[disk_position++];++nes_fds_bytes;
            if(!(disk_control&0x40))disk_gap=0;
            else if(!disk_gap && byte) {disk_gap=1;disk_byte=byte;disk_transfer=1;}
            else if(disk_gap && (disk_control&4)) {
                disk_byte=byte;disk_transfer=1;
                if(disk_control&0x80)disk_irq=1;
            }
            if(disk_position==disk_length)disk_control&=(uint8_t)~1u;
        }
        if(elapsed<disk_delay)disk_delay-=elapsed;
    }
    fds_irq_level();
}

/* Mapper 20 - FDS style memory layout.
 * The layout itself ($6000-$DFFF = 32 KiB writable PRG RAM, $E000-$FFFF = the
 * 8 KiB BIOS) is installed by Nes_LoadFds() in nes_main.c, because it needs to
 * rewrite memmap_tbl and the read/write dispatch tables.  This mapper only has
 * to leave CHR RAM pointed at its single 8 KiB bank and swallow writes that the
 * BIOS sends to $8000-$FFFF. */

static void MAP20_Reset()
{
	FdsIo_Reset();
	set_PPU_banks(0,1,2,3,4,5,6,7);
}

static void MAP20_MemoryWrite(uint16 addr, uint8 data)
{
	(void)addr;
	(void)data;
}

void MAP20_Init(void)
{
	NES_Mapper->Reset=MAP20_Reset;
	NES_Mapper->Write=MAP20_MemoryWrite;
	NES_Mapper->ReadLow=FdsIo_Read;
	NES_Mapper->WriteLow=FdsIo_Write;
}
