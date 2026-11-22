#ifndef CJK_FONT_H
#define CJK_FONT_H

#include <stdint.h>

/* On-card CJK font: NES/FONT.MAP (Unicode -> glyph slot) and NES/FONT.HZK
 * (16x16 bitmaps in GB2312 order). The map is loaded into external SRAM on
 * first use; the ROM arena may hold a game later, so callers must invalidate. */
void CjkFont_Invalidate(void);
int  CjkFont_Ready(void);

/* UTF-8 helpers. Draw advances one cell per character; the cell size comes from
 * FONT.MAP (16 or 24 px), and ASCII uses the Flash font at cell/8 scale. */
unsigned CjkFont_Cell(void);
unsigned Utf8_Length(const char *utf8);
unsigned Utf8_Draw(uint16_t x, uint16_t y, const char *utf8, uint16_t fg, uint16_t bg);

#endif
