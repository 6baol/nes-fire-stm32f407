#ifndef NES_LIBRARY_H
#define NES_LIBRARY_H
#include "nes_roms.h"
#include "nes_posters.h"

/* The listing lives on the card (NES/CATALOG.IDX); RAM only keeps a window.
 * NES_CATALOG_MAX is a count limit, not a memory cost. */
#define NES_CATALOG_MAX 2048u
#define NES_ROM_ARENA_ADDR 0x6c060000u
#define NES_ROM_ARENA_BYTES 0x000a0000u
/* CHR ROM above 128 KiB is decoded on demand, so VROM_banks (0x6c000000) is
 * free. The tile cache keeps the first 8 KiB of VROM_tiles, and the arena
 * starts after it: 0x6c022000..0x6c100000 holds a 768 KiB image plus header. */
#define NES_LARGE_ARENA_ADDR 0x6c022000u
#define NES_LARGE_ARENA_BYTES 0x000de000u
#define NES_MMC5_ARENA_ADDR 0x6c020000u
#define NES_MMC5_ARENA_BYTES 0x000e0000u

int NesLibrary_Boot(void);
unsigned NesLibrary_Count(void);
/* Fills a static scratch entry and returns it. The pointer stays valid until
 * the next NesLibrary_Game/NesLibrary_Load call, so use it immediately. */
const NesRomImage *NesLibrary_Game(unsigned index);
/* Search builds a filtered view over the catalog; Count/Game/Load then only see
 * matching entries. ASCII matching is case-insensitive; UTF-8 bytes compare
 * exactly. Returns the number of matches (0 restores the full list). */
unsigned NesLibrary_Search(const char *needle);
void NesLibrary_ClearView(void);
unsigned NesLibrary_ViewActive(void);
/* The arena is shared with cover loading only while no game is executing. */
void NesLibrary_EnterMenu(void);
const NesPoster *NesLibrary_Poster(const NesRomImage *game);
int NesLibrary_Load(unsigned index);
/* 0=native controls, 1=known Just Breed RPG stick/confirmation profile. */
unsigned NesLibrary_InputProfile(void);
/* Battery-backed cartridge SRAM. No card I/O from Nes_Frame(). */
int NesLibrary_Save(void);
int NesLibrary_SavePending(void);
const char *NesLibrary_Status(void);
const char *NesLibrary_Error(void);
extern volatile uint32_t nes_sd_file_reads;
extern volatile uint32_t nes_sd_save_writes,nes_sd_save_restores;
#endif
