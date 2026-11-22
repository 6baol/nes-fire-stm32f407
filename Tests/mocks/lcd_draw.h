#ifndef TEST_LCD_DRAW_H
#define TEST_LCD_DRAW_H
#include <stdint.h>
#include "fonts.h"
#define WHITE 0xFFFF
#define BLACK 0x0000
#define RED 0xF800
#define GREEN 0x07E0
#define YELLOW 0xFFE0
#define GRAY 0x8430
#define BLUE 0x001F
#define CYAN 0x7FFF
extern void (*lcd_open_window)(uint16_t,uint16_t,uint16_t,uint16_t);
extern void (*lcd_fill_color)(uint16_t,uint16_t,uint16_t,uint16_t,uint16_t);
void LCD_DispString_EN(uint16_t x,uint16_t y,char *s,uint16_t fg,uint16_t bg,sFONT *font);
#endif
