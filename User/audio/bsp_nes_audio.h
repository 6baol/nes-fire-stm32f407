#ifndef BSP_NES_AUDIO_H
#define BSP_NES_AUDIO_H
#include <stdint.h>
typedef enum {
    NES_AUDIO_HEADPHONES=0,
    NES_AUDIO_SPEAKER=1,
    NES_AUDIO_OFF=2
} NesAudioOutput;
uint8_t NesAudio_Init(void);
void NesAudio_Stop(void);
void NesAudio_Mute(uint8_t on);
void NesAudio_Render(int16_t *dest,unsigned frames);
NesAudioOutput NesAudio_GetOutput(void);
/* Main-thread only. Returns zero on success; failed changes fall back to mute. */
uint8_t NesAudio_SetOutput(NesAudioOutput output);
/* 0..100 in software; does not touch the codec gain registers. */
void NesAudio_SetVolume(uint8_t volume);
uint8_t NesAudio_GetVolume(void);
#endif
