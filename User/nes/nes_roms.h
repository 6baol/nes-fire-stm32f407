#ifndef NES_ROMS_H
#define NES_ROMS_H
#include <stdint.h>
/* One embedded game. label is short ASCII for the 480x800 menu. */
typedef struct {
    const char *label;
    const char *file;
    const uint8_t *data;
    uint32_t size;
    uint8_t mapper;
} NesRomImage;
extern const NesRomImage nes_rom_images[];
extern const uint32_t nes_rom_image_count;
/* Default game, kept for single-ROM tools and tests. */
extern const uint8_t nes_rom[];
extern const uint32_t nes_rom_size;
#endif
