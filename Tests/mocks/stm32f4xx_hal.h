#ifndef TEST_STM32_HAL_H
#define TEST_STM32_HAL_H
#include <stdint.h>
typedef enum { HAL_OK=0,HAL_ERROR=1 } HAL_StatusTypeDef;
typedef struct { uint32_t Pin,Mode,Pull; } GPIO_InitTypeDef;
typedef struct {
    uint32_t ClockPrescaler,Resolution,ScanConvMode,ContinuousConvMode;
    uint32_t DiscontinuousConvMode,ExternalTrigConvEdge,ExternalTrigConv;
    uint32_t DataAlign,NbrOfConversion,DMAContinuousRequests,EOCSelection;
} ADC_InitTypeDef;
typedef struct { void *Instance;ADC_InitTypeDef Init;uint32_t State; } ADC_HandleTypeDef;
typedef struct { uint32_t Channel,Rank,SamplingTime; } ADC_ChannelConfTypeDef;
#define GPIOA ((void*)1)
#define GPIOB ((void*)2)
#define GPIOC ((void*)3)
#define ADC1 ((void*)4)
#define GPIO_PIN_4 16u
#define GPIO_PIN_6 64u
#define GPIO_PIN_7 128u
#define GPIO_MODE_ANALOG 1u
#define GPIO_MODE_INPUT 0u
#define GPIO_NOPULL 0u
#define GPIO_PULLUP 1u
#define ADC_CLOCK_SYNC_PCLK_DIV4 0u
#define ADC_RESOLUTION_12B 0u
#define DISABLE 0u
#define ADC_EXTERNALTRIGCONVEDGE_NONE 0u
#define ADC_SOFTWARE_START 0u
#define ADC_DATAALIGN_RIGHT 0u
#define ADC_EOC_SINGLE_CONV 0u
#define ADC_SAMPLETIME_144CYCLES 0u
#define ADC_CHANNEL_4 4u
#define ADC_CHANNEL_6 6u
#define HAL_ADC_STATE_ERROR_INTERNAL 0x10u
#define ADC_FLAG_EOC 2u
#define __HAL_RCC_GPIOA_CLK_ENABLE() ((void)0)
#define __HAL_RCC_GPIOB_CLK_ENABLE() ((void)0)
#define __HAL_RCC_GPIOC_CLK_ENABLE() ((void)0)
#define __HAL_RCC_ADC1_CLK_ENABLE() ((void)0)
#define __HAL_ADC_GET_FLAG(adc,flag) MockADC_EOC()
uint8_t MockADC_EOC(void);
void HAL_GPIO_Init(void*,GPIO_InitTypeDef*);
uint32_t HAL_GetTick(void);
HAL_StatusTypeDef HAL_ADC_Init(ADC_HandleTypeDef*);
HAL_StatusTypeDef HAL_ADC_ConfigChannel(ADC_HandleTypeDef*,ADC_ChannelConfTypeDef*);
HAL_StatusTypeDef HAL_ADC_Start(ADC_HandleTypeDef*);
HAL_StatusTypeDef HAL_ADC_Stop(ADC_HandleTypeDef*);
uint32_t HAL_ADC_GetValue(ADC_HandleTypeDef*);
#endif
