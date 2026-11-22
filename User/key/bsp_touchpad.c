/* Board PA5 / TIM2_CH1 RC touch pad. Based on EmbedFire HAL example
 * 33-TIM—电容按键/User/TouchPad/bsp_touchpad.* (see Reference/board_touchpad).
 * 5ms discharge and +50 capture-tick gate; first edge latched by IRQ.
 * Current APB1 timer clock is 84MHz, /24 gives 3.5MHz (not 9MHz).
 */
#include "bsp_touchpad.h"
#include "stm32f4xx.h"
#include <string.h>
static TouchpadState state;
static uint16_t calibration[10];
static uint8_t phase,count,consecutive;
static uint32_t due,started;
static volatile uint16_t captured_ticks;
static volatile uint8_t capture_done;
volatile uint32_t touchpad_irq_count,touchpad_press_count,touchpad_release_count;

static void sample(uint16_t raw)
{
    unsigned i,j;uint32_t sum=0;
    state.raw=raw;++state.samples;
    if(!raw || raw>32767) {++state.errors;state.pressed=0;consecutive=0;return;}
    if(!state.ready) {
        calibration[count++]=raw;
        if(count<10)return;
        for(i=0;i<9;i++)for(j=i+1;j<10;j++)if(calibration[j]<calibration[i]) {
            uint16_t swap=calibration[i];calibration[i]=calibration[j];calibration[j]=swap;
        }
        for(i=2;i<8;i++)sum+=calibration[i];
        state.baseline=(uint16_t)(sum/6);state.ready=1;return;
    }
    /* Validity is bounded by the timer deadline, not a baseline multiple. */
    /* Immediate press, debounced release. Measured idle noise was within
     * baseline+35 ticks; +50 retains a margin while recognizing lighter touch. */
    if(!state.pressed) {
        if(raw>(uint32_t)state.baseline+50u) {
            state.pressed=1;consecutive=0;++touchpad_press_count;
        }
    } else if(raw<=(uint32_t)state.baseline+25u) {
        if(++consecutive>=2) {
            state.pressed=0;consecutive=0;++touchpad_release_count;
        }
    } else consecutive=0;
}
void Touchpad_Init(void)
{
    uint32_t timer_hz;
    memset(&state,0,sizeof(state));phase=count=consecutive=0;due=0;
    capture_done=0;touchpad_irq_count=touchpad_press_count=touchpad_release_count=0;
    __HAL_RCC_GPIOA_CLK_ENABLE();__HAL_RCC_TIM2_CLK_ENABLE();
    /* PA5 AF1=TIM2_CH1; preserve all neighbouring joystick/KEY1 pins. */
    GPIOA->BSRR=(uint32_t)GPIO_PIN_5<<16;
    GPIOA->OTYPER&=~GPIO_PIN_5;
    GPIOA->OSPEEDR=(GPIOA->OSPEEDR&~(3u<<10))|(2u<<10);
    GPIOA->AFR[0]=(GPIOA->AFR[0]&~(15u<<20))|(1u<<20);
    GPIOA->PUPDR=(GPIOA->PUPDR&~(3u<<10))|(2u<<10);
    GPIOA->MODER=(GPIOA->MODER&~(3u<<10))|(1u<<10);
    timer_hz=HAL_RCC_GetPCLK1Freq();
    if((RCC->CFGR&RCC_CFGR_PPRE1)!=0)timer_hz*=2;
    TIM2->CR1=0;TIM2->DIER=0;TIM2->CCER=0;
    TIM2->PSC=timer_hz/3500000u-1;TIM2->ARR=65535;
    /* 8 stable samples at fDTS/32 (~3 us): suppress threshold chatter. */
    TIM2->CCMR1=TIM_CCMR1_CC1S_0|(15u<<4);TIM2->CCER=0;
    TIM2->EGR=TIM_EGR_UG;TIM2->SR=0;TIM2->CR1=TIM_CR1_CEN;
    HAL_NVIC_SetPriority(TIM2_IRQn,4,0);HAL_NVIC_ClearPendingIRQ(TIM2_IRQn);
    HAL_NVIC_EnableIRQ(TIM2_IRQn);
}
void Touchpad_Poll(uint32_t now_ms)
{
    if(phase==0) {
        if((int32_t)(now_ms-due)<0)return;
        TIM2->DIER=0;TIM2->CCER=0;
        GPIOA->BSRR=(uint32_t)GPIO_PIN_5<<16;
        GPIOA->PUPDR=(GPIOA->PUPDR&~(3u<<10))|(2u<<10);
        GPIOA->MODER=(GPIOA->MODER&~(3u<<10))|(1u<<10);
        started=now_ms;due=now_ms+10;phase=1;return;
    }
    if(phase==1) {
        if((uint32_t)(now_ms-started)<5)return;
        TIM2->CNT=0;TIM2->SR=0;capture_done=0;
        TIM2->CCER=TIM_CCER_CC1E;TIM2->DIER=TIM_DIER_CC1IE|TIM_DIER_UIE;
        GPIOA->PUPDR&=~(3u<<10);
        GPIOA->MODER=(GPIOA->MODER&~(3u<<10))|(2u<<10);
        started=now_ms;phase=2;return;
    }
    if(capture_done) {
        uint8_t done=capture_done;capture_done=0;
        if(done==1)sample(captured_ticks);
        else {++state.errors;state.pressed=0;consecutive=0;}
        phase=0;
    } else if((uint32_t)(now_ms-started)>=20) {
        TIM2->DIER=0;TIM2->CCER=0;
        ++state.errors;state.pressed=0;consecutive=0;phase=0;
    }
}
const TouchpadState *Touchpad_Get(void) {return &state;}

/* Latch exactly the first edge. Foreground PPU work may delay polling for
 * hundreds of us; leaving capture enabled would overwrite CCR1 and set CC1OF. */
void TIM2_IRQHandler(void)
{
    uint32_t flags=TIM2->SR;
    if((flags&TIM_SR_CC1IF) && (TIM2->DIER&TIM_DIER_CC1IE)) {
        captured_ticks=(uint16_t)TIM2->CCR1;
        TIM2->DIER=0;TIM2->CCER=0;TIM2->SR=0;
        ++touchpad_irq_count;capture_done=1;
    } else if((flags&TIM_SR_UIF) && (TIM2->DIER&TIM_DIER_UIE)) {
        TIM2->DIER=0;TIM2->CCER=0;TIM2->SR=0;capture_done=2;
    } else TIM2->SR=0;
}
