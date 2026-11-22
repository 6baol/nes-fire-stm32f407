#ifndef NES_FDS_AUDIO_H
#define NES_FDS_AUDIO_H
#include <stdint.h>
void FdsAudio_Reset(void);
void FdsAudio_Write(uint16_t address,uint8_t value);
uint8_t FdsAudio_Read(uint16_t address);
/* Audio consumer: ordered writes from the existing timestamped APU queue. */
void FdsAudio_Apply(uint16_t address,uint8_t value);
int FdsAudio_Sample(uint32_t cycles_per_sample_q16);
#endif
