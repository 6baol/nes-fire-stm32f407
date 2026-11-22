#ifndef BSP_JOYSTICK_HW_H
#define BSP_JOYSTICK_HW_H
#include "stm32f4xx_hal.h"

/* Batianhu V2 CN3, same-side adjacent pins 21 / 23 / 25.
 * Keep the camera connector empty; power the HW-504 from 3V3.
 */
#define JOYSTICK_X_PORT    GPIOA
#define JOYSTICK_X_PIN     GPIO_PIN_4
#define JOYSTICK_X_CHANNEL ADC_CHANNEL_4
#define JOYSTICK_Y_PORT    GPIOA
#define JOYSTICK_Y_PIN     GPIO_PIN_6
#define JOYSTICK_Y_CHANNEL ADC_CHANNEL_6
#define JOYSTICK_SW_PORT   GPIOB
#define JOYSTICK_SW_PIN    GPIO_PIN_7

#endif
