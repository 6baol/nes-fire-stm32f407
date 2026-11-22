#ifndef BSP_SDIO_H
#define BSP_SDIO_H

#include "stm32f4xx.h"

/* MicroSD on SDIO: PC8..PC11 data, PC12 clock, PD2 command (V2 schematic p.8).
 * The camera shares PC8/PC9, so the camera must stay disconnected. */

#define SD_BLOCK_SIZE      512u
#define SD_TIMEOUT_MS      2000u

typedef enum {
    SD_BSP_OK = 0,
    SD_BSP_ERR_INIT,      /* HAL_SD_Init failed: no card, bad contact, wrong clock */
    SD_BSP_ERR_BUS,       /* 4-bit bus switch failed */
    SD_BSP_ERR_NOT_READY, /* card left the transfer state */
    SD_BSP_ERR_TIMEOUT,   /* read did not finish inside SD_TIMEOUT_MS */
    SD_BSP_ERR_READ,      /* HAL reported a data/CRC error */
    SD_BSP_ERR_WRITE
} SdBspResult;

extern SD_HandleTypeDef       g_sd_handle;
extern HAL_SD_CardInfoTypeDef g_sd_card_info;
extern volatile uint32_t sd_last_error,sd_init_attempts,sd_read_retries,sd_blocks_read,sd_bus_width;
extern volatile uint32_t sd_write_retries,sd_blocks_written;

/* Brings up SDIO in 1-bit mode, then switches to 4-bit. Safe to call once at boot. */
SdBspResult SDIO_Config(void);

/* 1 when the card answers CMD13 in the transfer state. */
uint8_t BSP_SD_IsReady(void);

/* Blocking read; no DMA, no interrupt, so it can run before the game loop starts. */
SdBspResult BSP_SD_ReadBlocks(uint8_t *buf, uint32_t block_addr, uint32_t block_count);
SdBspResult BSP_SD_WriteBlocks(const uint8_t *buf,uint32_t block_addr,uint32_t block_count);
SdBspResult BSP_SD_Sync(void);

void BSP_SD_GetCardInfo(HAL_SD_CardInfoTypeDef *info);

#endif /* BSP_SDIO_H */
