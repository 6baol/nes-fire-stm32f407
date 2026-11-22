#ifndef GAME_RENDERER_H
#define GAME_RENDERER_H
#include "game_core.h"
#include "bsp_joystick.h"
typedef struct {
    uint32_t fps, render_us, render_max_us, logic_max_us, overruns, fill_us;
    uint8_t sram_ok, touch_ok;
} GameMetrics;
void Renderer_Init(void);
void Renderer_Begin(const Game *g, const JoystickState *joy, const GameMetrics *metrics);
uint8_t Renderer_Busy(void);
/* Compose and send at most GAME_RENDER_BATCH tiles per call. */
void Renderer_Poll(void);
#endif
