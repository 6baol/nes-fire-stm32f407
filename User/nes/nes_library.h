#ifndef NES_LIBRARY_H
#define NES_LIBRARY_H
#include "nes_roms.h"
#include "nes_posters.h"

/* The listing lives on the card (NES/CATALOG.IDX); RAM keeps a record window. */
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
enum {
    NES_LIBRARY_FILTER_ALL,
    NES_LIBRARY_FILTER_COMPATIBLE,
    NES_LIBRARY_FILTER_UNSUPPORTED,
    NES_LIBRARY_FILTER_FAVORITES,
    NES_LIBRARY_FILTER_RECENT
};
enum {
    NES_LIBRARY_COMPAT_UNKNOWN = 0,
    NES_LIBRARY_COMPAT_HEADER_OK = 1,
    NES_LIBRARY_COMPAT_READ_ERROR = -10
};
/* Search includes the current view. An empty query or no hits clears the query
 * and restores that view. ASCII folds case; UTF-8 compares exactly. */
unsigned NesLibrary_Search(const char *needle);
int NesLibrary_SearchFailed(void);
void NesLibrary_ClearView(void);
unsigned NesLibrary_ViewActive(void);
unsigned NesLibrary_Filter(void);
unsigned NesLibrary_SetFilter(unsigned filter);
/* Compatibility filters can scan missing metadata in bounded calls. */
unsigned NesLibrary_FilterPending(void);
void NesLibrary_AdvanceFilter(void);
/* Returns a compatibility state or NES_IMPORT_* rejection for a view entry.
 * Without probe, an unclassified entry never causes a ROM read. */
int NesLibrary_Compatibility(unsigned index, int probe, unsigned *mapper);
unsigned NesLibrary_OverflowCount(void);
int NesLibrary_IsFavorite(unsigned index);
/* 1 added, 0 removed, -1 unavailable/write error, -2 full. */
int NesLibrary_ToggleFavorite(unsigned index);
/* Call only after a successful load. Returns 0 if recorded, -1 on failure. */
int NesLibrary_RecordPlayed(unsigned index);
/* The arena is shared with cover loading only while no game is executing. */
void NesLibrary_EnterMenu(void);
const NesPoster *NesLibrary_Poster(const NesRomImage *game);
/* Runtime poster capture. CoverExists returns 1 when a .COV is already
 * present, or when there is no card (nothing to capture). SaveCover writes a
 * 256x240 8-bit NCV1 from the live NES frame: palette is the 64-entry RGB565
 * table, pixels are 0..63 indices. Returns 0 on success, 1 when the cover
 * already exists, negative on I/O failure. Never rebuilds the catalog. */
int NesLibrary_CoverExists(const char *rom_path);
int NesLibrary_SaveCover(const char *rom_path,const uint8_t *pixels,const uint16_t *palette);
int NesLibrary_Load(unsigned index);
/* 0=native controls, 1=known Just Breed RPG stick/confirmation profile. */
unsigned NesLibrary_InputProfile(void);
/* Battery-backed cartridge SRAM. No card I/O from Nes_Frame(). */
int NesLibrary_Save(void);
int NesLibrary_SavePending(void);
/* Device settings live in NES/SETTINGS.BIN: version, orientation, volume,
 * output, CRC32. Load returns 1 when a valid record was applied to *settings;
 * save returns 0 on success. Storage errors never affect runtime behaviour. */
typedef struct {
    uint8_t version;
    uint8_t landscape;
    uint8_t volume;
    uint8_t output;
} NesLibrarySettings;
int NesLibrary_LoadSettings(NesLibrarySettings *settings);
int NesLibrary_SaveSettings(const NesLibrarySettings *settings);
const char *NesLibrary_Status(void);
const char *NesLibrary_Error(void);
extern volatile uint32_t nes_sd_file_reads;
extern volatile uint32_t nes_sd_save_writes,nes_sd_save_restores;
#endif
