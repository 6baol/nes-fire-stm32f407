#ifndef GAME_APP_H
#define GAME_APP_H
#include <stdint.h>
void GameApp_Init(uint8_t touch_ok,uint8_t sram_ok,uint32_t fill_us);
void GameApp_Poll(void);
#endif
