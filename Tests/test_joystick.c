#include "bsp_joystick.h"
#include "stm32f4xx_hal.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
static uint32_t now,channel;
static uint16_t raw_x=2048,raw_y=2048;
static uint8_t eoc=1,fail_init;
static ADC_HandleTypeDef *mock_adc;
static unsigned init_calls;
void HAL_GPIO_Init(void *p,GPIO_InitTypeDef *c) { (void)p;(void)c; }
uint32_t HAL_GetTick(void) { return now; }
uint8_t MockADC_EOC(void) { return eoc; }
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef *a)
{
    mock_adc=a;++init_calls;
    a->State=fail_init?HAL_ADC_STATE_ERROR_INTERNAL:0;
    return fail_init?HAL_ERROR:HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef *a,ADC_ChannelConfTypeDef *c)
{
    (void)a;
    assert(c->Channel==ADC_CHANNEL_4 || c->Channel==ADC_CHANNEL_6);
    channel=c->Channel;return HAL_OK;
}
HAL_StatusTypeDef HAL_ADC_Start(ADC_HandleTypeDef *a) { (void)a;return HAL_OK; }
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef *a) { (void)a;return HAL_OK; }
uint32_t HAL_ADC_GetValue(ADC_HandleTypeDef *a) { (void)a;return channel==ADC_CHANNEL_4?raw_x:raw_y; }
static void pairs(unsigned count)
{
    for(unsigned i=0;i<count;++i) {
        Joystick_Poll(now);Joystick_Poll(now);Joystick_Poll(now);now+=2;
    }
}
int main(void)
{
    const JoystickState *s=Joystick_Get();
    assert(!Joystick_Init());pairs(255);assert(!s->calibrated);
    pairs(1);assert(s->calibrated && s->healthy && s->center_x==2048);
    assert(s->x==0 && s->y==0);
    raw_x=3500;raw_y=2048;pairs(60);
    assert(s->x>0.5f && s->y==0);
    raw_x=2048;raw_y=3500;pairs(60);
    assert(fabsf(s->x)<0.001f && s->y>0.5f);
    raw_x=4095;raw_y=4095;pairs(60);
    assert(s->x>0.7f && s->y>0.7f && hypotf(s->x,s->y)<=1.00001f);
    raw_x=raw_y=2068;pairs(60);assert(s->x==0 && s->y==0);
    raw_x=3500;raw_y=2048;pairs(30);
    assert(s->x>0.5f);
    uint16_t saved_x=s->center_x,saved_y=s->center_y;
    float held=s->x;
    eoc=0;Joystick_Poll(now);now+=10;Joystick_Poll(now);
    assert(s->healthy && s->calibrated && s->errors==1 && s->x==held);
    /* A single fresh pair resumes while still pushed: no re-centring required. */
    eoc=1;now+=2;pairs(2);
    assert(s->calibrated && s->healthy && s->x>0.5f);
    assert(s->center_x==saved_x && s->center_y==saved_y);
    /* Prolonged loss stops movement, but never learns a new centre. */
    eoc=0;Joystick_Poll(now);now+=40;Joystick_Poll(now);
    assert(!s->healthy && s->calibrated && s->x==0 && s->y==0);
    eoc=1;raw_x=500;now+=2;pairs(1);
    assert(s->healthy && s->calibrated && s->x< -0.5f);
    assert(s->center_x==saved_x && s->center_y==saved_y);
    /* Internal ADC errors reinitialise automatically with the same centre. */
    unsigned before=init_calls;
    mock_adc->State|=HAL_ADC_STATE_ERROR_INTERNAL;raw_x=3500;now+=2;pairs(3);
    assert(init_calls>before && s->calibrated && s->healthy);
    fail_init=1;mock_adc->State|=HAL_ADC_STATE_ERROR_INTERNAL;now+=40;pairs(3);
    assert(!s->healthy && s->calibrated && s->x==0 && s->y==0);
    fail_init=0;pairs(3);
    assert(s->healthy && s->calibrated && s->x>0.5f);
    assert(s->center_x==saved_x && s->center_y==saved_y);
    Joystick_Calibrate();raw_x=4095;pairs(300);assert(!s->calibrated);
    raw_x=2048;pairs(256);assert(s->calibrated);
    /* Full-scale/raw-centre safety remains, while bounded AC pickup can be
     * averaged out before applying the unchanged stability threshold. */
    Joystick_Calibrate();
    for(unsigned i=0;i<256;i++) {
        raw_x=(uint16_t)(2048+(i&1?30:-30));
        raw_y=(uint16_t)(2048+(i&1?220:-220));pairs(1);
    }
    assert(s->calibrated && s->center_x==2048 && s->center_y==2048);
    Joystick_Calibrate();
    for(unsigned i=0;i<256;i++) {raw_x=(uint16_t)(2048+(i/8)*12);raw_y=2048;pairs(1);}
    assert(!s->calibrated); /* Moving mean still must not become a centre. */
    fail_init=1;assert(Joystick_Init());pairs(2);assert(!s->healthy && !s->calibrated);
    puts("PASS: ADC pair sequencing, calibration, radial deadzone, diagonal limit,");
    puts("      transient hold, stale neutral, automatic ADC recovery without re-centering,");
    puts("      noisy calibration and off-center/moving-centre rejection.");
    return 0;
}
