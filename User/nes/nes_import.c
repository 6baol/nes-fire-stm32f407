/* Cartridge header validation for ROMs copied straight onto the SD card.
 * This is the C counterpart of tools/embed_roms.py::normalize/validate: the
 * same NES 2.0 subset is accepted, the same per-mapper limits apply, and the
 * same files are rejected. Keep both sides in step when adding a mapper. */
#include <string.h>
#include "nes_import.h"
#include "nes_library.h"

#define FDS_SIDE_SIZE 65500u
#define FDS_MAX_SIDES 8u

static int power2(uint32_t v){return v && !(v & (v - 1));}

static int fds_header(const uint8_t *h, uint32_t size, uint32_t cap, NesImportInfo *out)
{
    unsigned sides;
    if (size < 16) return NES_IMPORT_BAD_HEADER;
    if (!memcmp(h, "FDS\x1a", 4)) {
        sides = h[4];
        if (!sides || sides > FDS_MAX_SIDES || size != 16u + sides * FDS_SIDE_SIZE)
            return NES_IMPORT_BAD_LAYOUT;
    } else if (h[0] == 1 && !memcmp(h + 1, "*NINTENDO-HVC*", 14)) {
        sides = (unsigned)(size / FDS_SIDE_SIZE);
        if (!sides || sides > FDS_MAX_SIDES || size % FDS_SIDE_SIZE)
            return NES_IMPORT_BAD_LAYOUT;
    } else {
        return NES_IMPORT_BAD_HEADER;
    }
    if (size > cap) return NES_IMPORT_TOO_LARGE;
    memset(out, 0, sizeof(*out));
    out->size = size; out->mapper = 20; out->fds = 1;
    return NES_IMPORT_OK;
}

int NesImport_Header(const uint8_t *header, uint32_t size, NesImportInfo *out)
{
    uint8_t h[16];
    uint32_t prg, chr, cap, expected;
    unsigned mapper, ram_ok;

    if (!header || !out) return NES_IMPORT_BAD_HEADER;
    if (fds_header(header, size, NES_ROM_ARENA_BYTES, out) == NES_IMPORT_OK) return NES_IMPORT_OK;
    if (size < 16 || memcmp(header, "NES\x1a", 4)) return NES_IMPORT_BAD_HEADER;

    memcpy(h, header, sizeof(h));
    mapper = (h[6] >> 4) | (h[7] & 0xf0);
    if (h[7] & 0x0c) {                        /* NES 2.0 marker: bits 2-3 == 8 */
        if ((h[7] & 0x0c) != 8) return NES_IMPORT_BAD_HEADER;
        ram_ok = (h[10] == 0) || (mapper == 5 && (h[10] == 7 || h[10] == 0x70));
        if ((h[7] & 3) || h[8] || h[9] || !ram_ok || h[11] ||
            (h[12] != 0 && h[12] != 2) || h[13] || h[14] ||
            (h[15] != 0 && h[15] != 1) || (h[6] & 0x0c))
            return NES_IMPORT_BAD_HEADER;
        h[7] &= (uint8_t)0xf3;
        memset(h + 8, 0, 8);
        if (mapper == 5 && header[10]) h[8] = 1;  /* 8 KiB MMC5 WRAM */
        memcpy(out->header, h, sizeof(h));
        out->rewrite = 1;
    } else {
        memcpy(out->header, h, sizeof(h));
        out->rewrite = 0;
    }

    if ((h[7] & 15) || (h[6] & 0x0c) || (h[9] & 1)) return NES_IMPORT_BAD_HEADER;
    mapper = (h[6] >> 4) | (h[7] & 0xf0);
    prg = h[4]; chr = h[5];
    if (mapper == 20) return NES_IMPORT_BAD_MAPPER;
    if (mapper != 0 && mapper != 1 && mapper != 2 && mapper != 3 && mapper != 4 &&
        mapper != 5 && mapper != 7 && mapper != 11 && mapper != 40 &&
        mapper != 66 && mapper != 71 && mapper != 74 && mapper != 117 && mapper != 33)
        return NES_IMPORT_BAD_MAPPER;
    if (!prg || !power2(prg)) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 2 && (prg > 32 || chr)) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 5 && (prg > 32 || !chr || !power2(chr) || chr > 32 || h[8] > 1))
        return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 1 && (prg > 16 || h[8] > 1 || (chr && (!power2(chr) || chr > 16))))
        return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 7 && (prg < 2 || prg > 16 || chr || h[8] || (h[6] & 2)))
        return NES_IMPORT_BAD_LAYOUT;
    if ((mapper == 11 || mapper == 66) && (prg < 2 || prg > 8 || !chr ||
        !power2(chr) || chr > (mapper == 11 ? 16 : 4) || h[8] || (h[6] & 2)))
        return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 71 && (prg < 2 || prg > 16 || chr || h[8] || (h[6] & 2)))
        return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 0 && prg > 2) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 0 && chr > 1) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 3 && (!chr || !power2(chr) || chr > 16)) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 4 && (prg < 2 || prg > 32 || chr > 32 || (chr && !power2(chr))))
        return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 40 && (prg > 4 || !chr || !power2(chr) || chr > 8))
        return NES_IMPORT_BAD_LAYOUT;
    if ((mapper == 74 || mapper == 117 || mapper == 33) && (prg < 2 || prg > 32 ||
        !chr || !power2(chr) || chr > 32 || h[8])) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 16 && (prg < 2 || prg > 16 || !chr || !power2(chr) ||
        chr > 32 || h[8] > 1)) return NES_IMPORT_BAD_LAYOUT;

    expected = 16u + prg * 16384u + chr * 8192u;
    if (size != expected) return NES_IMPORT_BAD_LAYOUT;
    cap = (mapper == 5) ? NES_MMC5_ARENA_BYTES
        : (chr > 16 ? NES_LARGE_ARENA_BYTES : NES_ROM_ARENA_BYTES);
    if (size > cap) return NES_IMPORT_TOO_LARGE;
    out->size = size; out->mapper = (uint8_t)mapper; out->fds = 0;
    out->chr_large = (uint8_t)(chr > 16 && mapper != 5);
    return NES_IMPORT_OK;
}

uint32_t NesImport_VectorOffset(const uint8_t *header)
{
    uint32_t prg = header[4];
    unsigned mapper = (header[6] >> 4) | (header[7] & 0xf0);
    uint32_t boot = (mapper == 7 || mapper == 11 || mapper == 66) ? 32768u : prg * 16384u;
    return 16u + boot - 4u;
}

int NesImport_VectorOk(const uint8_t *vector)
{
    return ((uint32_t)vector[0] | ((uint32_t)vector[1] << 8)) >= 0x8000u;
}

int NesImport_Extension(const char *name, uint8_t *fds)
{
    const char *dot = strrchr(name, '.');
    if (!dot) return 0;
    if (!strcmp(dot, ".NES") || !strcmp(dot, ".nes")) { *fds = 0; return 1; }
    if (!strcmp(dot, ".FDS") || !strcmp(dot, ".fds")) { *fds = 1; return 1; }
    return 0;
}

void NesImport_Label(const char *name, char *label)
{
    const char *dot = strrchr(name, '.');
    unsigned i, j = 0, last = 0;
    unsigned len = dot ? (unsigned)(dot - name) : (unsigned)strlen(name);
    for (i = 0; i < len; i++) {
        unsigned char c = (unsigned char)name[i];
        if (c < 32) continue;                 /* drop control bytes */
        if (c >= 'a' && c <= 'z') c = (unsigned char)(c - 0x20);
        label[j++] = (char)c;                 /* UTF-8 bytes pass through */
        if (c != ' ') last = j;
        if (j >= NES_IMPORT_LABEL_MAX) break;
    }
    label[last] = 0;
}

const char *NesImport_Reason(int code)
{
    switch (code) {
    case NES_IMPORT_BAD_HEADER: return "BAD ROM HEADER";
    case NES_IMPORT_BAD_MAPPER: return "UNSUPPORTED MAPPER";
    case NES_IMPORT_BAD_LAYOUT: return "BAD ROM LAYOUT";
    case NES_IMPORT_TOO_LARGE:  return "ROM TOO LARGE";
    default: return "ROM REJECTED";
    }
}
