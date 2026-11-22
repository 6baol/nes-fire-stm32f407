/* Host test for the game menu: navigation, scrolling and paint behaviour.
 * The LCD API is stubbed so the real nes_menu.c layout code runs unmodified. */
#include <assert.h>
#include <stdio.h>
#include <string.h>
#include "nes_menu.h"
#include "nes_library.h"
#include "fonts.h"

void (*lcd_open_window)(uint16_t, uint16_t, uint16_t, uint16_t);
void (*lcd_fill_color)(uint16_t, uint16_t, uint16_t, uint16_t, uint16_t);

sFONT Font8x16 = {0, 8, 16}, Font16x24 = {0, 16, 24}, Font24x32 = {0, 24, 32};

static const uint8_t blob[16];
const NesRomImage nes_rom_images[8] = {
    {"GAME A", "a.nes", blob, 40976, 0},
    {"GAME B", "b.nes", blob, 73744, 40},
    {"GAME C", "c.nes", blob, 24592, 0},
    {"GAME D", "d.nes", blob, 32784, 0},
    {"GAME E", "e.nes", blob, 40976, 2},
    {"GAME F", "f.nes", blob, 131088, 3},
    {"GAME G", "g.nes", blob, 40976, 0},
    {"GAME H", "h.nes", blob, 40976, 0},
};
const uint32_t nes_rom_image_count = 8;
const NesRomImage *NesLibrary_Game(unsigned i){return i<8?&nes_rom_images[i]:0;}
const NesPoster *NesLibrary_Poster(const NesRomImage *g){return NesPoster_Find(g->file);}

static char painted[64][64];
static unsigned painted_count;
static unsigned full_clear;
static unsigned fills;
void MockLCD_Write(uint16_t pixel) {(void)pixel;}

void LCD_DispString_EN(uint16_t x, uint16_t y, char *s, uint16_t fg, uint16_t bg, sFONT *font)
{
    (void)x; (void)y; (void)fg; (void)bg;
    assert(font == &Font8x16 || font == &Font16x24 || font == &Font24x32);
    assert(strlen(s) < 64);
    if (painted_count < 64) snprintf(painted[painted_count], 64, "%s", s);
    ++painted_count;
}
void PixelFont_Text(uint16_t x,uint16_t y,const char *s,uint16_t fg,uint16_t bg,unsigned scale)
{
    assert(scale>=1 && scale<=3);
    assert(x+strlen(s)*8*scale<=480 && y+8*scale<=800);
    LCD_DispString_EN(x,y,(char*)s,fg,bg,scale==1?&Font8x16:scale==2?&Font16x24:&Font24x32);
}

/* These fixtures contain ASCII only; glyph rasterization has its own ARM test. */
unsigned CjkFont_Cell(void) { return 16; }
unsigned Utf8_Length(const char *text) { return (unsigned)strlen(text); }
unsigned Utf8_Draw(uint16_t x,uint16_t y,const char *text,uint16_t fg,uint16_t bg)
{
    PixelFont_Text(x,y,text,fg,bg,2);
    return Utf8_Length(text)*CjkFont_Cell();
}

static void stub_open(uint16_t x, uint16_t y, uint16_t w, uint16_t h) { (void)x; (void)y; (void)w; (void)h; }
static void stub_fill(uint16_t x, uint16_t y, uint16_t w, uint16_t h, uint16_t c)
{
    (void)c;
    ++fills;
    if (x == 0 && y == 0 && w == 480 && h == 800) ++full_clear;
}

static int painted_has(const char *s)
{
    unsigned i;
    for (i = 0; i < painted_count && i < 64; i++) if (!strcmp(painted[i], s)) return 1;
    return 0;
}

static void reset_paint(void) { painted_count = 0; fills = 0; full_clear = 0; }

int main(void)
{
    NesMenuState m;
    lcd_open_window = stub_open;
    lcd_fill_color = stub_fill;

    NesMenu_Init(&m, 8, 1, 1);
    assert(m.index == 0 && m.first == 0 && m.count == 8 && m.audio_ok == 1);

    /* Wrap in both directions. */
    assert(NesMenu_Move(&m, -1) == 1 && m.index == 7);
    assert(NesMenu_Move(&m, 1) == 1 && m.index == 0);
    assert(NesMenu_Move(&m, 0) == 0 && m.index == 0);

    /* Window follows the selection and never runs past the end. */
    NesMenu_Init(&m, 8, 1, 1);
    for (int i = 1; i <= 5; i++) assert(NesMenu_Move(&m, 1) == 1);
    assert(m.index == 5 && m.first == 3);
    for (int i = 0; i < 2; i++) NesMenu_Move(&m, 1);
    assert(m.index == 7 && m.first == 5);
    NesMenu_Move(&m, 1);
    assert(m.index == 0 && m.first == 0);
    NesMenu_Move(&m, -1);
    assert(m.index == 7 && m.first == 5);

    /* Single-entry list cannot move. */
    NesMenu_Init(&m, 1, 0, 0);
    assert(NesMenu_Move(&m, 1) == 0 && m.index == 0);
    assert(NesMenu_Move(&m, -1) == 0 && m.index == 0);

    /* A full repaint clears the panel once and paints every visible label. */
    NesMenu_Init(&m, 8, 1, 1);
    reset_paint();
    NesMenu_Draw(&m);
    assert(full_clear == 1);
    assert(painted_has("NES FIRE"));
    assert(!painted_has("YOUR COLLECTION"));
    for (int i = 0; i < NES_MENU_ROWS; i++) assert(painted_has(nes_rom_images[i].label));
    assert(!painted_has(nes_rom_images[NES_MENU_ROWS].label));
    assert(!painted_has("AUDIO READY"));

    /* Selecting the last row scrolls the window and paints the new tail. */
    NesMenu_Init(&m, 8, 1, 1);
    for (int i = 0; i < 7; i++) NesMenu_Move(&m, 1);
    reset_paint();
    NesMenu_DrawSelection(&m);
    assert(full_clear == 0);
    assert(painted_has(nes_rom_images[7].label));
    assert(!painted_has(nes_rom_images[0].label));

    /* Audio failure is visible, not silently ignored. */
    NesMenu_Init(&m, 3, 0, 0);
    reset_paint();
    NesMenu_Draw(&m);
    assert(painted_has("AUDIO OFF"));
    assert(painted_has("TOUCH OFF"));

    /* Status line repaint clears its own row first. */
    reset_paint();
    NesMenu_Status("ROM REJECTED rc=4 - SEE UART");
    assert(fills == 1);
    assert(painted_has("ROM REJECTED rc=4 - SEE UART"));

    reset_paint();
    NesMenu_LibraryOptions(6,4,1,1);
    assert(full_clear == 1);
    assert(painted_has("LOADABLE HEADERS"));
    assert(painted_has("RECENTLY PLAYED"));
    assert(painted_has("REMOVE FAVORITE"));

    reset_paint();
    NesMenu_SaveError("SD SAVE FAILED - CHECK CARD");
    assert(full_clear == 1);
    assert(painted_has("SD SAVE FAILED - CHECK CARD"));
    assert(painted_has("KEY2/SW RETRY SAVE"));
    assert(painted_has("KEY1 RESUME GAME"));

    puts("PASS: menu wrap-around, scrolling window, full repaint coverage,");
    puts("      selection-only repaint, audio/touch status and status line clearing.");
    return 0;
}
