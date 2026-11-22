#ifndef NES_IMPORT_H
#define NES_IMPORT_H

#include <stddef.h>
#include <stdint.h>

/* UTF-8 names and labels: Chinese titles need 3 bytes per glyph. */
#define NES_IMPORT_NAME_MAX 128
#define NES_IMPORT_PATH_MAX 160
#define NES_IMPORT_LABEL_MAX 96
#define NES_IMPORT_UNKNOWN_MAPPER UINT16_MAX

enum {
    NES_IMPORT_OK = 0,
    NES_IMPORT_BAD_HEADER = -1,
    NES_IMPORT_BAD_MAPPER = -2,
    NES_IMPORT_BAD_LAYOUT = -3,
    NES_IMPORT_TOO_LARGE = -4,
    NES_IMPORT_BAD_REGION = -5,
    NES_IMPORT_TRAINER = -6,
    NES_IMPORT_FOUR_SCREEN = -7,
    NES_IMPORT_BAD_CONSOLE = -8,
    NES_IMPORT_NES2_LAYOUT = -9,
    NES_IMPORT_BAD_VECTOR = -11,
    NES_IMPORT_BAD_BOARD = -12,
    NES_IMPORT_SIZE_MISMATCH = -13
};

typedef struct {
    uint32_t size;      /* whole file in bytes */
    uint16_t mapper;    /* NES 2.0 carries a 12-bit mapper */
    uint8_t submapper;  /* zero for unspecified/legacy headers */
    uint8_t fds;        /* disk image; Nes_Load detects it from the payload */
    uint8_t rewrite;    /* NES 2.0 header must be normalised before Nes_Load */
    uint8_t chr_large;  /* CHR ROM > 128 KiB: needs the 768 KiB arena */
    uint8_t header[16]; /* normalised iNES header */
} NesImportInfo;

/* Validates a 16-byte header plus the file size, mirroring tools/embed_roms.py.
 * The reset vector lives in the PRG payload, so the caller checks it separately. */
int NesImport_Header(const uint8_t *header, uint32_t size, NesImportInfo *out);

/* Byte offset of the 4-byte reset vector inside the file; 0 when not applicable. */
uint32_t NesImport_VectorOffset(const uint8_t *header);
int NesImport_VectorOk(const uint8_t *vector);

/* Resolve ambiguous Mapper 16 headers by CRC-32 of the PRG + CHR payload. */
unsigned NesImport_Mapper16Submapper(uint32_t payload_crc);

/* 1 when the name ends in .NES or .FDS (case-insensitive); *fds reports which. */
int NesImport_Extension(const char *name, uint8_t *fds);

/* Display label: extension stripped, ASCII upper case, control chars removed.
 * UTF-8 bytes are preserved so Chinese names stay readable. */
void NesImport_Label(const char *name, char *label);

const char *NesImport_Reason(int code);
void NesImport_FormatReason(int code, const NesImportInfo *info, char *dst, size_t capacity);

#endif
