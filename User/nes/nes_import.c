/* Cartridge header validation for ROMs copied straight onto the SD card.
 * This is the C counterpart of tools/embed_roms.py::normalize/validate: the
 * same NES 2.0 subset is accepted, the same per-mapper limits apply, and the
 * same files are rejected. Keep both sides in step when adding a mapper. */
#include <stdio.h>
#include <string.h>
#include "nes_import.h"
#include "nes_library.h"

#define FDS_SIDE_SIZE 65500u
#define FDS_MAX_SIDES 8u

static int power2(uint32_t v){return v && !(v & (v - 1));}

static int fds_header(const uint8_t *h, uint32_t size, uint32_t cap, NesImportInfo *out)
{
    unsigned sides;
    if (size < 4) return NES_IMPORT_BAD_HEADER;
    if (!memcmp(h, "FDS\x1a", 4)) {
        out->mapper = 20; out->fds = 1;
        if (size < 16) return NES_IMPORT_SIZE_MISMATCH;
        sides = h[4];
        if (!sides || sides > FDS_MAX_SIDES) return NES_IMPORT_BAD_LAYOUT;
        if (size != 16u + sides * FDS_SIDE_SIZE) return NES_IMPORT_SIZE_MISMATCH;
    } else if (size >= 15 && h[0] == 1 && !memcmp(h + 1, "*NINTENDO-HVC*", 14)) {
        out->mapper = 20; out->fds = 1;
        sides = (unsigned)(size / FDS_SIDE_SIZE);
        if (!sides || sides > FDS_MAX_SIDES) return NES_IMPORT_BAD_LAYOUT;
        if (size % FDS_SIDE_SIZE) return NES_IMPORT_SIZE_MISMATCH;
    } else {
        return NES_IMPORT_BAD_HEADER;
    }
    if (size > cap) return NES_IMPORT_TOO_LARGE;
    return NES_IMPORT_OK;
}

int NesImport_Header(const uint8_t *header, uint32_t size, NesImportInfo *out)
{
    uint8_t h[16];
    uint32_t prg, chr, cap, expected;
    unsigned mapper, nes2, ram_ok;
    int fds_result;

    if (!out) return NES_IMPORT_BAD_HEADER;
    memset(out, 0, sizeof(*out));
    out->mapper = NES_IMPORT_UNKNOWN_MAPPER;
    out->size = size;
    if (!header) return NES_IMPORT_BAD_HEADER;
    fds_result = fds_header(header, size, NES_ROM_ARENA_BYTES, out);
    if (out->fds) return fds_result;
    if (size < 16 || memcmp(header, "NES\x1a", 4)) return NES_IMPORT_BAD_HEADER;

    memcpy(h, header, sizeof(h));
    mapper = (h[6] >> 4) | (h[7] & 0xf0);
    nes2 = (h[7] & 0x0c) == 8;
    if (nes2) {
        mapper |= (unsigned)(h[8] & 15) << 8;
        out->submapper = h[8] >> 4;
    }
    out->mapper = (uint16_t)mapper;
    if (h[6] & 4) return NES_IMPORT_TRAINER;
    if (h[6] & 8) return NES_IMPORT_FOUR_SCREEN;
    if (h[7] & 3) return NES_IMPORT_BAD_CONSOLE;
    if (nes2 ? (h[12] != 0 && h[12] != 2) : (h[9] & 1)) return NES_IMPORT_BAD_REGION;
    if (!nes2 && (h[7] & 0x0c)) return NES_IMPORT_BAD_HEADER;
    if (mapper == 20) return NES_IMPORT_BAD_MAPPER;
    if (mapper != 0 && mapper != 1 && mapper != 2 && mapper != 3 && mapper != 4 &&
        mapper != 5 && mapper != 7 && mapper != 11 && mapper != 16 && mapper != 40 &&
        mapper != 66 && mapper != 71 && mapper != 74 && mapper != 117 && mapper != 33)
        return NES_IMPORT_BAD_MAPPER;
    if (mapper == 16 && ((h[6] & 2) || (nes2 ? (h[10] || (out->submapper &&
        out->submapper != 4 && out->submapper != 5)) : h[8])))
        return NES_IMPORT_BAD_BOARD;
    if (nes2) {
        ram_ok = (h[10] == 0) || (mapper == 5 && (h[10] == 7 || h[10] == 0x70));
        if ((out->submapper && mapper != 16) || h[9] || !ram_ok || h[11] || h[13] || h[14] ||
            (h[15] != 0 && h[15] != 1))
            return NES_IMPORT_NES2_LAYOUT;
        h[7] &= (uint8_t)0xf3;
        memset(h + 8, 0, 8);
        if (mapper == 5 && header[10]) h[8] = 1;  /* 8 KiB MMC5 WRAM */
        out->rewrite = 1;
    }
    memcpy(out->header, h, sizeof(h));

    prg = h[4]; chr = h[5];
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
    if ((mapper == 0 || mapper == 3) && prg > 2) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 0 && chr > 1) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 3 && (!chr || !power2(chr) || chr > 16)) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 4 && (prg < 2 || prg > 32 || chr > 32 || (chr && !power2(chr))))
        return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 40 && (prg > 4 || !chr || !power2(chr) || chr > 8))
        return NES_IMPORT_BAD_LAYOUT;
    if ((mapper == 74 || mapper == 117 || mapper == 33) && (prg < 2 || prg > 32 ||
        !chr || !power2(chr) || chr > 32 || h[8])) return NES_IMPORT_BAD_LAYOUT;
    if (mapper == 16 && (prg < 2 || prg > 16 || !chr || !power2(chr) || chr > 32))
        return NES_IMPORT_BAD_LAYOUT;

    expected = 16u + prg * 16384u + chr * 8192u;
    if (size != expected) return NES_IMPORT_SIZE_MISMATCH;
    cap = (mapper == 5) ? NES_MMC5_ARENA_BYTES
        : (chr > 16 ? NES_LARGE_ARENA_BYTES : NES_ROM_ARENA_BYTES);
    if (size > cap) return NES_IMPORT_TOO_LARGE;
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

unsigned NesImport_Mapper16Submapper(uint32_t payload_crc)
{
    /* Board identity for ambiguous iNES dumps. Compare the PRG/CHR CRC, not
     * a filename or legacy battery flag. See NESdev Bandai FCG board table. */
    switch (payload_crc) {
    case 0x2c4421b2u: /* Akuma-kun */
    case 0x33b899c9u: /* Dragon Ball: Daimaou Fukkatsu */
    case 0x6e68e31au: case 0xbfc7a2e9u: /* Dragon Ball 3, both revisions */
    case 0xd343c66au: /* Famicom Jump */
    case 0x7b5206afu: /* Meimon! Dai-3 Yakyuu-bu */
    case 0xa851cae9u: /* Nishimura Kyoutarou Mystery */
    case 0x9c04c8d5u: /* Sakigake!! Otoko Juku */
        return 4;
    case 0xdb05106eu: /* Crayon Shin-chan */
        return 5;
    default:
        return 0;
    }
}

int NesImport_Extension(const char *name, uint8_t *fds)
{
    const char *dot = strrchr(name, '.');
    if (!dot) return 0;
    if (strlen(dot) != 4) return 0;
    if ((dot[1] | 32) == 'n' && (dot[2] | 32) == 'e' && (dot[3] | 32) == 's') { *fds = 0; return 1; }
    if ((dot[1] | 32) == 'f' && (dot[2] | 32) == 'd' && (dot[3] | 32) == 's') { *fds = 1; return 1; }
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
    case NES_IMPORT_BAD_REGION: return "UNSUPPORTED REGION";
    case NES_IMPORT_TRAINER: return "UNSUPPORTED TRAINER";
    case NES_IMPORT_FOUR_SCREEN: return "UNSUPPORTED FOUR-SCREEN";
    case NES_IMPORT_BAD_CONSOLE: return "UNSUPPORTED CONSOLE";
    case NES_IMPORT_NES2_LAYOUT: return "UNSUPPORTED NES 2.0 CONFIG";
    case NES_IMPORT_BAD_VECTOR: return "BAD RESET VECTOR";
    case NES_IMPORT_BAD_BOARD: return "UNSUPPORTED CARTRIDGE BOARD";
    case NES_IMPORT_SIZE_MISMATCH: return "ROM SIZE MISMATCH";
    default: return "ROM REJECTED";
    }
}

void NesImport_FormatReason(int code, const NesImportInfo *info, char *dst, size_t capacity)
{
    if (!dst || !capacity) return;
    if (code == NES_IMPORT_BAD_MAPPER && info && info->mapper != NES_IMPORT_UNKNOWN_MAPPER)
        snprintf(dst, capacity, "MAPPER %u UNSUPPORTED", (unsigned)info->mapper);
    else if (code == NES_IMPORT_BAD_BOARD && info && info->mapper == 16)
        snprintf(dst, capacity, "MAPPER 16 BOARD NOT CONFIRMED");
    else
        snprintf(dst, capacity, "%s", NesImport_Reason(code));
}
