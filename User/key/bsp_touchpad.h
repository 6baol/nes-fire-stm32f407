#ifndef BSP_TOUCHPAD_H
#define BSP_TOUCHPAD_H
#include <stdint.h>
typedef struct {
    uint16_t raw,baseline;
    uint8_t ready,pressed;
    uint32_t samples,errors;
} TouchpadState;
void Touchpad_Init(void);
void Touchpad_Poll(uint32_t now_ms);
const TouchpadState *Touchpad_Get(void);
#endif
