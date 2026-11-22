#ifndef NES_FDS_H
#define NES_FDS_H
#include <stdint.h>
#define FDS_SIDE_SIZE 65500u
#define FDS_MAX_SIDES 8u
typedef struct {
    const uint8_t *data;
    uint32_t size;
    uint8_t sides, header_size;
} FdsImage;
typedef struct {
    const uint8_t *data;
    uint16_t address, size;
    uint8_t number, id, type;
    char name[9];
} FdsFile;
/* Zero means success. No allocations and no modification of the input. */
int FdsImage_Open(FdsImage *out,const uint8_t *data,uint32_t size);
int FdsImage_File(const FdsImage *image,unsigned side,unsigned index,FdsFile *out);
void FdsIo_Reset(void);
void FdsIo_Write(uint16_t address,uint8_t value);
uint8_t FdsIo_Read(uint16_t address);
void FdsIo_Tick(uint32_t cycles);
int FdsDrive_Mount(const FdsImage *image,unsigned side);
void FdsDrive_Unmount(void);
unsigned FdsDrive_Sides(void);
unsigned FdsDrive_Side(void);
int FdsDrive_Changing(void);
/* Eject briefly, then insert another side while CPU/BIOS keep running. */
int FdsDrive_RequestSide(unsigned side);
#endif
