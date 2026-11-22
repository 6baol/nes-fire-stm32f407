/**
  ******************************************************************************
  * @file    main.c
  * @author  embedfire
  * @brief   
  ******************************************************************************
  * @attention
  *
  ******************************************************************************
  */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "main.h"
#include "stm32f4xx.h"
#include "bsp_led.h"
#include "bsp_key.h"
#include "bsp_beep.h"  
#include "bsp_uart1.h"
#include "bsp_dwt.h"
#include "lcd_draw.h"
#include "lcd_touch.h"
#include "bsp_sram.h"
#include "bsp_joystick.h"
#include "nes_port.h"


static void SystemClock_Config(void);
void Delay( uint32_t nCount);

/**
  * @brief  主函数
  * @param  
  * @retval 
  */
int main(void)
{
    uint8_t touch_ok, sram_ok = 0;
    uint32_t begin, fill_us;
    HAL_Init();
    SystemClock_Config();
    Key_GPIO_Config();
    LED_GPIO_Config();
    BEEP_GPIO_Config();
    BEEP_OFF;
    UART1_Config();
    DWT_Init();
    printf("\r\nNES Fire Emulator v0.17 / HCLK=%lu Hz\r\n", (unsigned long)HAL_RCC_GetHCLKFreq());
    printf("HW-504: 3V3 GND VRx=PA4 VRy=PA6 SW=PB7; camera disconnected.\r\n");
    if (LCD_Draw_Config() != 0) {
        printf("FATAL: LCD ID not supported. Check screen and reset.\r\n");
        while (1) { LED1_TOGGLE; HAL_Delay(250); }
    }
    if (LCD_X_LENGTH != 480 || LCD_Y_LENGTH != 800) {
        printf("FATAL: expected 480x800 portrait.\r\n");
        while (1) { LED1_TOGGLE; HAL_Delay(250); }
    }
    touch_ok = LCD_Touch_Config() == 0;
#if 1
    SRAM_Config();
    sram_ok = SRAM_Test();
#endif
    /* Startup benchmark only; gameplay never clears the whole LCD per frame. */
    begin = DWT->CYCCNT;
    lcd_fill_color(0, 0, LCD_X_LENGTH, LCD_Y_LENGTH, BLACK);
    fill_us = (DWT->CYCCNT-begin) / (HAL_RCC_GetHCLKFreq()/1000000u);
    printf("LCD fill=%lu us, SRAM=%u, touch=%u\r\n", (unsigned long)fill_us,sram_ok,touch_ok);
    if (Joystick_Init() != 0) printf("ADC init failed; check input diagnostics.\r\n");
    if (!sram_ok) {
        LCD_DispString_EN(16,80,"SRAM FAIL - NES STOPPED",RED,BLACK,&Font16x24);
        while(1) HAL_Delay(100);
    }
    NesApp_Init(touch_ok);
    while (1) NesApp_Poll();
}


/**
  * @brief  System Clock Configuration
  *         The system Clock is configured as follow : 
  *            System Clock source            = PLL (HSE)
  *            SYSCLK(Hz)                     = 168000000
  *            HCLK(Hz)                       = 168000000
  *            AHB Prescaler                  = 1
  *            APB1 Prescaler                 = 4
  *            APB2 Prescaler                 = 2
  *            HSE Frequency(Hz)              = 25000000
  *            PLL_M                          = 25
  *            PLL_N                          = 336
  *            PLL_P                          = 2
  *            PLL_Q                          = 7
  *            VDD(V)                         = 3.3
  *            Main regulator output voltage  = Scale1 mode
  *            Flash Latency(WS)              = 5
  * @param  None
  * @retval None
  */
static void SystemClock_Config(void)
{
  RCC_ClkInitTypeDef RCC_ClkInitStruct;
  RCC_OscInitTypeDef RCC_OscInitStruct;

  /* Enable Power Control clock */
  __HAL_RCC_PWR_CLK_ENABLE();
  
  /* The voltage scaling allows optimizing the power consumption when the device is 
     clocked below the maximum system frequency, to update the voltage scaling value 
     regarding system frequency refer to product datasheet.  */
  __HAL_PWR_VOLTAGESCALING_CONFIG(PWR_REGULATOR_VOLTAGE_SCALE1);
  
  /* Enable HSE Oscillator and activate PLL with HSE as source */
  RCC_OscInitStruct.OscillatorType = RCC_OSCILLATORTYPE_HSE;
  RCC_OscInitStruct.HSEState = RCC_HSE_ON;
  RCC_OscInitStruct.PLL.PLLState = RCC_PLL_ON;
  RCC_OscInitStruct.PLL.PLLSource = RCC_PLLSOURCE_HSE;
  RCC_OscInitStruct.PLL.PLLM = 25;
  RCC_OscInitStruct.PLL.PLLN = 336;
  RCC_OscInitStruct.PLL.PLLP = RCC_PLLP_DIV2;
  RCC_OscInitStruct.PLL.PLLQ = 7;
  if(HAL_RCC_OscConfig(&RCC_OscInitStruct) != HAL_OK)
  {
    while(1) {};
  }
  
  /* Select PLL as system clock source and configure the HCLK, PCLK1 and PCLK2 
     clocks dividers */
  RCC_ClkInitStruct.ClockType = (RCC_CLOCKTYPE_SYSCLK | RCC_CLOCKTYPE_HCLK | RCC_CLOCKTYPE_PCLK1 | RCC_CLOCKTYPE_PCLK2);
  RCC_ClkInitStruct.SYSCLKSource = RCC_SYSCLKSOURCE_PLLCLK;
  RCC_ClkInitStruct.AHBCLKDivider = RCC_SYSCLK_DIV1;
  RCC_ClkInitStruct.APB1CLKDivider = RCC_HCLK_DIV4;  
  RCC_ClkInitStruct.APB2CLKDivider = RCC_HCLK_DIV2;  
  if(HAL_RCC_ClockConfig(&RCC_ClkInitStruct, FLASH_LATENCY_5) != HAL_OK)
  {
    while(1) {};
  }

  /* STM32F405x/407x/415x/417x Revision Z devices: prefetch is supported  */
  if (HAL_GetREVID() == 0x1001)
  {
    /* Enable the Flash prefetch */
    __HAL_FLASH_PREFETCH_BUFFER_ENABLE();
  }
}


/**
  * @brief  模拟不精确延时函数
  * @param  空指令数
  */
void Delay(uint32_t nCount)	
{
	for(uint32_t i = nCount; i != 0; i--)
    {
        __ASM("NOP"); //需要空指令占位，否则在高优化等级失效
    }
}


/* 勾选Use MicroLIB情况下，重定向c库函数printf到串口DEBUG_USART，重定向后可使用printf函数*/
int fputc(int ch, FILE *f)
{
    (void)f;
	HAL_UART_Transmit(&Uart1Handle, (uint8_t *)&ch, 1, 1000);		
	return (ch);
}
