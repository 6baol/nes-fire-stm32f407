/**
  ******************************************************************************
  * @file    bsp_sdio.c
  * @brief   MicroSD (SDIO) bring-up for STM32F407 Batianhu V2.
  *          Derived from the vendor example A-2-2 (bsp_sdio.c), reduced to the
  *          blocking path the asset loader needs: no DMA stream, no IRQ.
  ******************************************************************************
  */

#include "bsp_sdio.h"
#include <string.h>

SD_HandleTypeDef       g_sd_handle;
HAL_SD_CardInfoTypeDef g_sd_card_info;

static uint8_t sd_initialised;
/* Polling at 16 MHz/4-bit overflowed the FIFO on the real board (error 0x20).
 * Allow DMA audio IRQ latency, and keep SD FIFO copies off the FSMC bus. */
static uint32_t sd_sector[SD_BLOCK_SIZE/4];
volatile uint32_t sd_last_error,sd_init_attempts,sd_read_retries,sd_blocks_read,sd_bus_width;
volatile uint32_t sd_write_retries,sd_blocks_written;

static uint8_t SD_WaitReady(uint32_t timeout_ms)
{
    uint32_t start = HAL_GetTick();
    while ((HAL_GetTick() - start) < timeout_ms) {
        if (HAL_SD_GetCardState(&g_sd_handle) == HAL_SD_CARD_TRANSFER) return 1;
    }
    return 0;
}

SdBspResult SDIO_Config(void)
{
    unsigned attempt;
    SdBspResult result=SD_BSP_ERR_INIT;
    if (sd_initialised) return SD_BSP_OK;
    for(attempt=0;attempt<3;attempt++) {
        ++sd_init_attempts;
        __HAL_RCC_SDIO_CLK_ENABLE();
        __HAL_RCC_SDIO_FORCE_RESET();__HAL_RCC_SDIO_RELEASE_RESET();
        memset(&g_sd_handle,0,sizeof(g_sd_handle));
        g_sd_handle.Instance = SDIO;
        g_sd_handle.Init.ClockEdge = SDIO_CLOCK_EDGE_RISING;
        g_sd_handle.Init.ClockBypass = SDIO_CLOCK_BYPASS_DISABLE;
        g_sd_handle.Init.ClockPowerSave = SDIO_CLOCK_POWER_SAVE_DISABLE;
        g_sd_handle.Init.BusWide = SDIO_BUS_WIDE_1B;
        g_sd_handle.Init.HardwareFlowControl = SDIO_HARDWARE_FLOW_CONTROL_DISABLE;
        /* 48MHz / (4+2) = 8MHz. The old 16MHz single-block polling overflowed
         * the FIFO; multi-block reads keep the FIFO fed at 8MHz. Retry with
         * 1-bit/400kHz if setup fails. */
        g_sd_handle.Init.ClockDiv = attempt?118:4;
        HAL_Delay(20);
        if(HAL_SD_Init(&g_sd_handle)!=HAL_OK) {
            sd_last_error=g_sd_handle.ErrorCode;result=SD_BSP_ERR_INIT;continue;
        }
        if(HAL_SD_ConfigWideBusOperation(&g_sd_handle,attempt?SDIO_BUS_WIDE_1B:SDIO_BUS_WIDE_4B)!=HAL_OK) {
            sd_last_error=g_sd_handle.ErrorCode;result=SD_BSP_ERR_BUS;
            (void)HAL_SD_Abort(&g_sd_handle);continue;
        }
        HAL_SD_GetCardInfo(&g_sd_handle,&g_sd_card_info);
        sd_bus_width=attempt?1:4;sd_initialised=1;
        return SD_BSP_OK;
    }
    return result;
}

uint8_t BSP_SD_IsReady(void)
{
    if (!sd_initialised) return 0;
    return (HAL_SD_GetCardState(&g_sd_handle) == HAL_SD_CARD_TRANSFER) ? 1u : 0u;
}

SdBspResult BSP_SD_ReadBlocks(uint8_t *buf, uint32_t block_addr, uint32_t block_count)
{
    unsigned attempt;
    if (!sd_initialised) return SD_BSP_ERR_INIT;
    if ((buf == NULL) || (block_count == 0u)) return SD_BSP_ERR_READ;

    if(block_addr>=g_sd_card_info.LogBlockNbr || block_count>g_sd_card_info.LogBlockNbr-block_addr)return SD_BSP_ERR_READ;
    for(attempt=0;attempt<2;attempt++) {
        if(SD_WaitReady(SD_TIMEOUT_MS) &&
           HAL_SD_ReadBlocks(&g_sd_handle,(uint8_t*)buf,block_addr,block_count,SD_TIMEOUT_MS)==HAL_OK &&
           SD_WaitReady(SD_TIMEOUT_MS))break;
        sd_last_error=g_sd_handle.ErrorCode;++sd_read_retries;
        (void)HAL_SD_Abort(&g_sd_handle);
        SDIO->DCTRL=0;SDIO->ICR=SDIO_STATIC_DATA_FLAGS;
    }
    if(attempt==2)return SD_BSP_ERR_READ;
    sd_blocks_read+=block_count;
    return SD_BSP_OK;
}

SdBspResult BSP_SD_WriteBlocks(const uint8_t *buf,uint32_t block_addr,uint32_t block_count)
{
    uint32_t block;unsigned attempt;
    if(!sd_initialised)return SD_BSP_ERR_INIT;
    if(!buf||!block_count||block_addr>=g_sd_card_info.LogBlockNbr||
       block_count>g_sd_card_info.LogBlockNbr-block_addr)return SD_BSP_ERR_WRITE;
    for(block=0;block<block_count;block++) {
        memcpy(sd_sector,buf+block*SD_BLOCK_SIZE,SD_BLOCK_SIZE);
        for(attempt=0;attempt<2;attempt++) {
            if(SD_WaitReady(SD_TIMEOUT_MS)&&
               HAL_SD_WriteBlocks(&g_sd_handle,(uint8_t*)sd_sector,block_addr+block,1,SD_TIMEOUT_MS)==HAL_OK&&
               SD_WaitReady(SD_TIMEOUT_MS))break;
            sd_last_error=g_sd_handle.ErrorCode;++sd_write_retries;
            (void)HAL_SD_Abort(&g_sd_handle);
            SDIO->DCTRL=0;SDIO->ICR=SDIO_STATIC_DATA_FLAGS;
        }
        if(attempt==2)return SD_BSP_ERR_WRITE;
        ++sd_blocks_written;
    }
    return SD_BSP_OK;
}
SdBspResult BSP_SD_Sync(void)
{
    if(!sd_initialised)return SD_BSP_ERR_INIT;
    return SD_WaitReady(SD_TIMEOUT_MS)?SD_BSP_OK:SD_BSP_ERR_TIMEOUT;
}
void BSP_SD_GetCardInfo(HAL_SD_CardInfoTypeDef *info)
{
    if (info == NULL) return;
    HAL_SD_GetCardInfo(&g_sd_handle, info);
}

void HAL_SD_MspInit(SD_HandleTypeDef *hsd)
{
    GPIO_InitTypeDef GPIO_InitStruct = {0};

    if (hsd->Instance != SDIO) return;

    __HAL_RCC_SDIO_CLK_ENABLE();
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOD_CLK_ENABLE();

    /* PC8 D0, PC9 D1, PC10 D2, PC11 D3, PC12 CK */
    GPIO_InitStruct.Pin = GPIO_PIN_8 | GPIO_PIN_9 | GPIO_PIN_10 | GPIO_PIN_11 | GPIO_PIN_12;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF12_SDIO;
    HAL_GPIO_Init(GPIOC, &GPIO_InitStruct);

    /* PD2 CMD */
    GPIO_InitStruct.Pin = GPIO_PIN_2;
    GPIO_InitStruct.Mode = GPIO_MODE_AF_PP;
    GPIO_InitStruct.Pull = GPIO_NOPULL;
    GPIO_InitStruct.Speed = GPIO_SPEED_FREQ_VERY_HIGH;
    GPIO_InitStruct.Alternate = GPIO_AF12_SDIO;
    HAL_GPIO_Init(GPIOD, &GPIO_InitStruct);
}

/*********************************************END OF FILE**********************/
