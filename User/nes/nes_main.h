#ifndef NES_MAIN_H
#define NES_MAIN_H
#include <stdint.h>
#include <string.h>
#include <stdio.h>
typedef uint8_t u8; typedef uint16_t u16; typedef uint32_t u32;
#define uint8 uint8_t
#define uint16 uint16_t
#define uint32 uint32_t
#define int8 int8_t
#define int16 int16_t
#define int32 int32_t
#define boolean uint8_t
#define INLINE static inline
#define NES_RAM_SPEED 0
#define CPU_NMI cpunmi=1
#define CPU_IRQ cpuirq=1
typedef struct {u8 id[3],ctrl_z,num_16k_rom_banks,num_8k_vrom_banks,flags_1,flags_2,reserved[8];} NES_header;
extern int MapperNo,NES_scanline,VROM_1K_SIZE,VROM_8K_SIZE;
extern NES_header *RomHeader;
extern u8 cpunmi,cpuirq,PADdata,PADdata1,*romfile;
extern u8 *NES_RAM,*NES_SRAM,*spr_ram;
void cpu6502_init(void);
void run6502(u32 cycles256);
int Nes_Load(const u8 *data, uint32_t size);
/* Experimental preloaded PRG-RAM snapshot only. Does not emulate an FDS drive
 * or load .fds disk files; the menu must not infer this format from a vector. */
int Nes_LoadFds(const u8 *data, uint32_t size, const u8 *bios, uint32_t bios_size);
int Nes_LoadDisk(const u8 *data,uint32_t size,const u8 *bios,uint32_t bios_size);
void Nes_Frame(int draw);
void debug_6502(u16 pc,u8 op);
/* Read the currently mapped CPU byte, shared by DMC and mapper bus conflicts. */
u8 Nes_ApuReadDmc(u16 addr);
#endif
