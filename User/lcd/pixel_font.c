#include "pixel_font.h"
#include "lcd_draw.h"
#include "bsp_lcd_display.h"
#include "pixel_font_data.h"
void PixelFont_Text(uint16_t x,uint16_t y,const char *s,uint16_t fg,uint16_t bg,unsigned scale)
{
    unsigned row,col,side;
    if(!s || scale<1 || scale>3 || y+8u*scale>800u)return;
    while(*s) {
        unsigned char code=(unsigned char)*s++;
        if(x+8u*scale>480u)return;
        if(code>='a' && code<='z')code=(unsigned char)(code-'a'+'A');
        if(code<32 || code>126)code='?';
        lcd_open_window(x,y,(uint16_t)(8u*scale),(uint16_t)(8u*scale));
        side=8u*scale;
        for(row=0;row<side;row++) {
            uint8_t bits=pixel_glyphs[code-32][row/scale];
            for(col=0;col<side;col++)
                LCD_WRITE_DATA((bits&(0x80u>>(col/scale)))?fg:bg);
        }
        x=(uint16_t)(x+8u*scale);
    }
}
