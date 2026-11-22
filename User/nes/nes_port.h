#ifndef NES_PORT_H
#define NES_PORT_H
#include <stdint.h>
void NesPort_Line(int line,const uint8_t *pixels,const uint16_t *palette);
void NesPort_InvalidateDisplay(void);
void NesPort_Input(void);
uint8_t NesPort_RpgPad(uint8_t buttons,int x,int y);
unsigned NesPort_RenderDivisor(unsigned requested,unsigned draw_us,unsigned skip_us);
void NesApp_Init(uint8_t touch_ok);
void NesApp_Poll(void);
#endif
