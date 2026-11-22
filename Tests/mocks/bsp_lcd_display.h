#ifndef TEST_LCD_BUS_H
#define TEST_LCD_BUS_H
#include <stdint.h>
void MockLCD_Write(uint16_t pixel);
#define LCD_WRITE_DATA(v) MockLCD_Write((uint16_t)(v))
#endif
