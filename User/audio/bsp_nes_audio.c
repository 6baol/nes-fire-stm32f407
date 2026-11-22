/* WM8978 headphone / BTL speaker output, based on EmbedFire 38-I2S audio example.
 * I2C1 PB8/PB9; I2S2 PB12 WS, PB13 CK, PB15 SD, PC6 MCLK.
 * Board schematic page 11: LOUT2/ROUT2 -> SPK-/SPK+. No microphone path. */
#include "bsp_nes_audio.h"
#include "stm32f4xx.h"
#include "nes_apu.h"
#include <string.h>
#define FRAMES 256u
static I2C_HandleTypeDef control;
static int16_t dma_pcm[FRAMES*4];
static uint8_t mono[FRAMES];
static uint8_t audio_output=NES_AUDIO_SPEAKER;
#define HP_VOLUME 40u
#define SPK_VOLUME 36u
volatile uint32_t nes_audio_ready,nes_audio_blocks,nes_audio_dma_errors;
volatile uint32_t nes_audio_nonzero,nes_audio_peak,nes_audio_max_us,nes_audio_codec_error;
volatile uint16_t nes_audio_codec_regs[58];
static uint8_t codec_write(unsigned reg,unsigned value)
{
    uint8_t data[2]={(uint8_t)((reg<<1)|((value>>8)&1)),(uint8_t)value};
    if(HAL_I2C_Master_Transmit(&control,0x34,data,2,20)!=HAL_OK) {
        ++nes_audio_codec_error;return 1;
    }
    nes_audio_codec_regs[reg]=(uint16_t)value;return 0;
}
void NesAudio_Render(int16_t *dest,unsigned frames)
{
    unsigned i;uint32_t peak=0,nonzero=0;
    if(frames>FRAMES)return;
    extern volatile uint8_t nes_audio_suspended;
    if(nes_audio_suspended){for(i=0;i<frames*2;i++)dest[i]=0;return;}
    apu_process(mono,(int)frames);
    /* Silent gameplay still drains the APU queue to keep emulated time. */
    if(audio_output==NES_AUDIO_OFF){for(i=0;i<frames*2;i++)dest[i]=0;return;}
    for(i=0;i<frames;i++) {
        int value=((int)mono[i]-128)*128; /* half scale, mono -> both ears */
        unsigned magnitude=(unsigned)(value<0?-value:value);
        dest[2*i]=dest[2*i+1]=(int16_t)value;
        if(magnitude>peak)peak=magnitude;
        if(value)++nonzero;
    }
    if(peak>nes_audio_peak)nes_audio_peak=peak;
    nes_audio_nonzero+=nonzero;
}
void NesAudio_Stop(void)
{
    DMA1_Stream4->CR&=~DMA_SxCR_EN;
    SPI2->CR2&=~SPI_CR2_TXDMAEN;SPI2->I2SCFGR&=~SPI_I2SCFGR_I2SE;
    nes_audio_ready=0;
}
/* Keep DMA running, but never process an APU while menus/SD loading reuse
 * the ROM arena or reset APU state. A codec-only mute would still read ROM. */
volatile uint8_t nes_audio_suspended;
void NesAudio_Mute(uint8_t on)
{
    if(on)nes_audio_suspended=1;
    if(nes_audio_ready)codec_write(10,(on||audio_output==NES_AUDIO_OFF)?0x40u:0u);
    if(!on)nes_audio_suspended=0;
}
NesAudioOutput NesAudio_GetOutput(void) {return (NesAudioOutput)audio_output;}
static uint8_t output_quiet(void)
{
    uint8_t failed=0;
    /* Attempt every mute/disable even when an earlier I2C write failed. */
    failed|=codec_write(10,0x40);
    failed|=codec_write(52,0x40|HP_VOLUME);
    failed|=codec_write(53,0x140|HP_VOLUME);
    failed|=codec_write(54,0x40|SPK_VOLUME);
    failed|=codec_write(55,0x140|SPK_VOLUME);
    failed|=codec_write(2,0);
    failed|=codec_write(3,0x00f);
    return failed;
}
uint8_t NesAudio_SetOutput(NesAudioOutput output)
{
    uint8_t hp=(output==NES_AUDIO_HEADPHONES),spk=(output==NES_AUDIO_SPEAKER);
    if((unsigned)output>NES_AUDIO_OFF || !nes_audio_ready)return 1;
    if(audio_output==(uint8_t)output)return 0;
    if(output_quiet())goto failed;
    /* Keep VMID/bias and the unused-output tie-off buffer enabled. No boost:
     * both speaker legs have the same DC level and equal, conservative gain.
     * R43 INVROUT2 makes mono PCM differential across SPK+ and SPK-. */
    if(codec_write(1,0x00f)||codec_write(43,spk?0x10:0)||
       codec_write(49,2)||codec_write(2,hp?0x180:0)||
       codec_write(3,spk?0x06f:0x00f))goto failed;
    HAL_Delay(5);
    if(hp && (codec_write(52,HP_VOLUME)||codec_write(53,0x100|HP_VOLUME)))goto failed;
    if(spk && (codec_write(54,SPK_VOLUME)||codec_write(55,0x100|SPK_VOLUME)))goto failed;
    if(codec_write(10,(nes_audio_suspended||output==NES_AUDIO_OFF)?0x40:0))goto failed;
    audio_output=(uint8_t)output;
    return 0;
failed:
    (void)output_quiet();audio_output=NES_AUDIO_OFF;
    return 1;
}
uint8_t NesAudio_Init(void)
{
    GPIO_InitTypeDef gpio={0};uint32_t begin;
    nes_audio_suspended=1;audio_output=NES_AUDIO_SPEAKER;
    nes_audio_ready=nes_audio_blocks=nes_audio_dma_errors=0;
    nes_audio_codec_error=nes_audio_peak=nes_audio_nonzero=nes_audio_max_us=0;
    __HAL_RCC_GPIOB_CLK_ENABLE();__HAL_RCC_GPIOC_CLK_ENABLE();__HAL_RCC_I2C1_CLK_ENABLE();
    gpio.Pin=GPIO_PIN_8|GPIO_PIN_9;gpio.Mode=GPIO_MODE_AF_OD;
    gpio.Pull=GPIO_PULLUP;gpio.Speed=GPIO_SPEED_FREQ_HIGH;gpio.Alternate=GPIO_AF4_I2C1;
    HAL_GPIO_Init(GPIOB,&gpio);
    __HAL_RCC_I2C1_FORCE_RESET();__HAL_RCC_I2C1_RELEASE_RESET();
    control.Instance=I2C1;control.Init.ClockSpeed=100000;
    control.Init.DutyCycle=I2C_DUTYCYCLE_2;control.Init.AddressingMode=I2C_ADDRESSINGMODE_7BIT;
    control.Init.DualAddressMode=I2C_DUALADDRESS_DISABLE;
    control.Init.GeneralCallMode=I2C_GENERALCALL_DISABLE;control.Init.NoStretchMode=I2C_NOSTRETCH_DISABLE;
    if(HAL_I2C_Init(&control)!=HAL_OK)return 1;
    if(codec_write(0,0))return 2;
    HAL_Delay(5);
    /* Codec slave, I2S 16 bit, MCLK=256fs, soft mute during power-up. */
    if(codec_write(4,0x10)||codec_write(6,0)||codec_write(10,0x40)||
       codec_write(1,0x0f)||codec_write(2,0)||codec_write(3,0x06f)||codec_write(43,0x10)||
       codec_write(44,0)||codec_write(47,0)||codec_write(48,0)||
       codec_write(49,2)||codec_write(50,1)||codec_write(51,1)||
       codec_write(11,255)||codec_write(12,511)||
       codec_write(52,0x40|HP_VOLUME)||codec_write(53,0x140|HP_VOLUME)||
       codec_write(54,SPK_VOLUME)||codec_write(55,0x100|SPK_VOLUME)||
       codec_write(56,0x40)||codec_write(57,0x40))return 3;
    gpio.Mode=GPIO_MODE_AF_PP;gpio.Pull=GPIO_NOPULL;gpio.Alternate=GPIO_AF5_SPI2;
    gpio.Pin=GPIO_PIN_12|GPIO_PIN_13|GPIO_PIN_15;HAL_GPIO_Init(GPIOB,&gpio);
    gpio.Pin=GPIO_PIN_6;HAL_GPIO_Init(GPIOC,&gpio);
    /* HSE 25MHz / PLLM 25 = 1MHz; PLLI2S=429/4 MHz.
     * / (256*38) gives 11024.8766 stereo frames/s. */
    RCC->CR&=~RCC_CR_PLLI2SON;
    begin=HAL_GetTick();while(RCC->CR&RCC_CR_PLLI2SRDY)if(HAL_GetTick()-begin>20)return 4;
    RCC->PLLI2SCFGR=(429u<<6)|(4u<<28);RCC->CFGR&=~RCC_CFGR_I2SSRC;
    RCC->CR|=RCC_CR_PLLI2SON;
    begin=HAL_GetTick();while(!(RCC->CR&RCC_CR_PLLI2SRDY))if(HAL_GetTick()-begin>20)return 5;
    __HAL_RCC_SPI2_CLK_ENABLE();__HAL_RCC_DMA1_CLK_ENABLE();
    __HAL_RCC_SPI2_FORCE_RESET();__HAL_RCC_SPI2_RELEASE_RESET();
    SPI2->I2SCFGR=SPI_I2SCFGR_I2SMOD|SPI_I2SCFGR_I2SCFG_1;
    SPI2->I2SPR=SPI_I2SPR_MCKOE|19;
    DMA1_Stream4->CR=0;begin=HAL_GetTick();
    while(DMA1_Stream4->CR&DMA_SxCR_EN)if(HAL_GetTick()-begin>20)return 6;
    memset(dma_pcm,0,sizeof(dma_pcm));DMA1->HIFCR=0x3d;
    DMA1_Stream4->PAR=(uint32_t)&SPI2->DR;DMA1_Stream4->M0AR=(uint32_t)dma_pcm;
    DMA1_Stream4->NDTR=FRAMES*4;DMA1_Stream4->FCR=0;
    DMA1_Stream4->CR=DMA_SxCR_MINC|DMA_SxCR_CIRC|DMA_SxCR_DIR_0|
      DMA_SxCR_PSIZE_0|DMA_SxCR_MSIZE_0|DMA_SxCR_PL_1|
      DMA_SxCR_TCIE|DMA_SxCR_HTIE|DMA_SxCR_TEIE|DMA_SxCR_DMEIE;
    HAL_NVIC_SetPriority(DMA1_Stream4_IRQn,6,0);HAL_NVIC_ClearPendingIRQ(DMA1_Stream4_IRQn);
    HAL_NVIC_EnableIRQ(DMA1_Stream4_IRQn);
    HAL_Delay(40);
    DMA1_Stream4->CR|=DMA_SxCR_EN;SPI2->CR2=SPI_CR2_TXDMAEN;
    SPI2->I2SCFGR|=SPI_I2SCFGR_I2SE;
    if(codec_write(10,0)) {NesAudio_Stop();return 7;}
    nes_audio_ready=1;return 0;
}
void DMA1_Stream4_IRQHandler(void)
{
    uint32_t flags=DMA1->HISR&0x3d,begin=DWT->CYCCNT,us;
    DMA1->HIFCR=flags;
    if(flags&0x0d) {++nes_audio_dma_errors;NesAudio_Stop();return;}
    if(flags&0x10) {NesAudio_Render(dma_pcm,FRAMES);++nes_audio_blocks;}
    if(flags&0x20) {NesAudio_Render(dma_pcm+FRAMES*2,FRAMES);++nes_audio_blocks;}
    us=(DWT->CYCCNT-begin)/(HAL_RCC_GetHCLKFreq()/1000000u);
    if(us>nes_audio_max_us)nes_audio_max_us=us;
}
