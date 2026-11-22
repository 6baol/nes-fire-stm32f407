#ifndef NES_PIXEL_FONT_H
#define NES_PIXEL_FONT_H
#include <stdint.h>
/* 8x8 Press Start 2P (OFL). Lowercase is rendered as uppercase. Scale 1..3. */
void PixelFont_Text(uint16_t x,uint16_t y,const char *s,uint16_t fg,uint16_t bg,unsigned scale);
#endif
