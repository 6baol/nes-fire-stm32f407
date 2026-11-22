/*-----------------------------------------------------------------------*/
/* FatFs low level disk I/O for the SDIO microSD slot                    */
/* Blocking single-sector bounce-buffer I/O for game loading/saves.     */
/* so no DMA stream or SDIO interrupt is required.                       */
/*-----------------------------------------------------------------------*/

#include "ff.h"
#include "diskio.h"
#include "bsp_sdio.h"

#define DEV_MMC 0 /* the card is the only physical drive in this build */

DSTATUS disk_status(BYTE pdrv)
{
    if (pdrv != DEV_MMC) return STA_NOINIT;
    if (!BSP_SD_IsReady()) return STA_NOINIT;
    return 0;
}

DSTATUS disk_initialize(BYTE pdrv)
{
    if (pdrv != DEV_MMC) return STA_NOINIT;
    /* SDIO_Config() already ran in the boot sequence; verify the card answers. */
    if (!BSP_SD_IsReady()) return STA_NOINIT;
    return 0;
}

DRESULT disk_read(BYTE pdrv, BYTE *buff, LBA_t sector, UINT count)
{
    if (pdrv != DEV_MMC) return RES_PARERR;
    if ((buff == NULL) || (count == 0u)) return RES_PARERR;

    switch (BSP_SD_ReadBlocks(buff, (uint32_t)sector, (uint32_t)count)) {
    case SD_BSP_OK:          return RES_OK;
    case SD_BSP_ERR_NOT_READY:
    case SD_BSP_ERR_INIT:    return RES_NOTRDY;
    default:                 return RES_ERROR;
    }
}

DRESULT disk_write(BYTE pdrv,const BYTE *buff,LBA_t sector,UINT count)
{
    if(pdrv!=DEV_MMC||!buff||!count)return RES_PARERR;
    switch(BSP_SD_WriteBlocks(buff,(uint32_t)sector,(uint32_t)count)) {
    case SD_BSP_OK:return RES_OK;
    case SD_BSP_ERR_INIT:case SD_BSP_ERR_NOT_READY:return RES_NOTRDY;
    default:return RES_ERROR;
    }
}
DRESULT disk_ioctl(BYTE pdrv, BYTE cmd, void *buff)
{
    if (pdrv != DEV_MMC) return RES_PARERR;

    switch (cmd) {
    case CTRL_SYNC:
        return BSP_SD_Sync()==SD_BSP_OK?RES_OK:RES_NOTRDY;

    case GET_SECTOR_COUNT:
        BSP_SD_GetCardInfo(&g_sd_card_info);
        *(DWORD *)buff = g_sd_card_info.LogBlockNbr;
        return RES_OK;

    case GET_SECTOR_SIZE:
        *(WORD *)buff = SD_BLOCK_SIZE;
        return RES_OK;

    case GET_BLOCK_SIZE:
        *(DWORD *)buff = 1;
        return RES_OK;

    default:
        return RES_PARERR;
    }
}
