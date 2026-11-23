#ifndef NES_MENU_H
#define NES_MENU_H
#include <stdint.h>
#include "nes_roms.h"

/* Visible rows on the 480x800 panel; the list scrolls when there are more. */
#define NES_MENU_ROWS 3

typedef struct {
    int16_t index;      /* selected game */
    uint16_t count;     /* games in the table */
    uint16_t first;     /* first visible row */
    uint8_t audio_ok;   /* WM8978 codec came up */
    uint8_t touch_ok;   /* touch panel responded */
} NesMenuState;

void NesMenu_Init(NesMenuState *m, uint16_t count, uint8_t audio_ok, uint8_t touch_ok);
/* Move the selection by dir (+1 next, -1 previous). Returns 1 if it changed. */
int  NesMenu_Move(NesMenuState *m, int dir);
/* Jump by step entries without wrapping. Returns 1 if it changed. */
int  NesMenu_Page(NesMenuState *m, int dir, unsigned step);
/* Full repaint: chrome, every visible row, info line, hints. */
void NesMenu_Draw(const NesMenuState *m);
/* Repaint only the selection-dependent parts after a move. */
void NesMenu_DrawSelection(const NesMenuState *m);
/* Rows and name only; the cover can follow once the stick settles. */
void NesMenu_DrawRows(const NesMenuState *m);
void NesMenu_DrawCover(const NesMenuState *m);
/* Selected game's compatibility and favorite status. */
void NesMenu_Info(const char *msg);
/* One-line message below the hints (ROM rejected, stick calibration, ...). */
void NesMenu_Status(const char *msg);
#define NES_DETAILS_FDS 1u
typedef struct {
    const char *label;      /* full UTF-8 catalog label, Chinese kept */
    const char *file;       /* relative path on the card */
    const char *status;     /* ASCII compatibility text */
    uint32_t size;          /* file size in bytes */
    unsigned index, count;  /* 0-based index and view size */
    unsigned mapper;        /* 0xffff when the header was not readable */
    int favorite;
    unsigned flags;         /* NES_DETAILS_FDS */
} NesDetails;
void NesDetails_Draw(const NesDetails *details);
void NesMenu_SaveError(const char *reason);
/* Settings centre: one hierarchical list with view, search and device pages. */
enum {
    NES_SETTINGS_ALL=0, NES_SETTINGS_LOADABLE, NES_SETTINGS_UNSUPPORTED,
    NES_SETTINGS_FAVORITES, NES_SETTINGS_RECENT, NES_SETTINGS_SEARCH,
    NES_SETTINGS_CONTROL, NES_SETTINGS_AUDIO, NES_SETTINGS_SCREEN,
    NES_SETTINGS_FAVORITE, NES_SETTINGS_ITEMS
};
enum {
    NES_SETTINGS_PAGE_ROOT=0, NES_SETTINGS_PAGE_CONTROL,
    NES_SETTINGS_PAGE_AUDIO, NES_SETTINGS_PAGE_SCREEN
};
void NesSettings_Root(unsigned cursor,unsigned view,int favorite,int has_game,
                      uint8_t volume,uint8_t output,const char *status);
void NesSettings_Control(void);
void NesSettings_Audio(unsigned cursor,uint8_t volume,uint8_t output,
                       uint8_t audio_ok,uint8_t failed,uint8_t save_failed);
void NesSettings_Screen(uint8_t landscape,uint8_t save_failed);
unsigned NesMenu_Rows(void);
/* Live controller test drawn on the CONTROL page. */
void NesSettings_Update(uint8_t pad,uint16_t raw_x,uint16_t raw_y,
                        uint8_t stick_ready,uint8_t cap_ready,uint16_t cap_raw);

/* On-screen search: 8x5 character grid, joystick moves, KEY2 selects. */
#define NES_SEARCH_QUERY 12
typedef struct {
    char query[NES_SEARCH_QUERY + 1];
    uint8_t length;
    uint8_t cursor;     /* 0..39 grid cell */
} NesSearchState;
void NesSearch_Init(NesSearchState *s);
void NesSearch_Draw(const NesSearchState *s);
int  NesSearch_Move(NesSearchState *s, int dx, int dy);
/* 0 = editing, 1 = run the search, 2 = leave without searching. */
int  NesSearch_Select(NesSearchState *s);
#endif
