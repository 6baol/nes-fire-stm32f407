#ifndef BSP_JOYSTICK_H
#define BSP_JOYSTICK_H
#include <stdint.h>
typedef struct {
    uint16_t raw_x, raw_y, center_x, center_y;
    float x, y;
    uint8_t calibrated, healthy;
    uint32_t errors;
    uint32_t pairs, max_pair_gap_ms;
} JoystickState;
uint8_t Joystick_Init(void);
void Joystick_Poll(uint32_t now_ms);
void Joystick_Calibrate(void);
const JoystickState *Joystick_Get(void);
#endif
