#include "nes_mmc5_audio.h"
#include "nes_apu.h"

typedef struct {u8 control,length,env,divider,restart,step;u16 period;u32 timer;} M5Pulse;
typedef struct {M5Pulse p[2];u8 enabled,pcm,pcm_mode;u32 quarter,fraction;} M5Sound;
static M5Sound cpu_sound,mix_sound;
static const u8 m5_lengths[32]={10,254,20,2,40,4,80,6,160,8,60,10,14,12,26,14,12,16,24,18,48,20,96,22,192,24,72,26,16,28,32,30};
static void sound_write(M5Sound *s,u16 address,u8 value)
{
    if(address<=0x5007) {
        unsigned ch=(address>>2)&1;M5Pulse *p=&s->p[ch];
        switch(address&3) {
        case 0:p->control=value;break;
        case 2:p->period=(p->period&0x700)|value;break;
        case 3:p->period=(p->period&255)|((u16)(value&7)<<8);p->restart=1;p->step=0;
            if(s->enabled&(1u<<ch))p->length=m5_lengths[value>>3];break;
        default:break;
        }
    } else if(address==0x5015) {
        unsigned ch;s->enabled=value&3;
        for(ch=0;ch<2;ch++)if(!(value&(1u<<ch)))s->p[ch].length=0;
    } else if(address==0x5010)s->pcm_mode=value;
    else if(address==0x5011 && !(s->pcm_mode&1) && value)s->pcm=value;
}
static void sound_tick(M5Sound *s,u32 cycles)
{
    unsigned ch;
    s->quarter+=cycles*240;
    while(s->quarter>=1789773) {
        s->quarter-=1789773;
        for(ch=0;ch<2;ch++) {
            M5Pulse *p=&s->p[ch];
            if(p->length && !(p->control&32))--p->length;
            if(p->restart){p->restart=0;p->env=15;p->divider=p->control&15;}
            else if(p->divider)--p->divider;
            else {p->divider=p->control&15;if(p->env)--p->env;else if(p->control&32)p->env=15;}
        }
    }
}
void Mmc5Audio_Reset(void){memset(&cpu_sound,0,sizeof(cpu_sound));memset(&mix_sound,0,sizeof(mix_sound));}
void Mmc5Audio_Write(u16 address,u8 value){sound_write(&cpu_sound,address,value);Apu_Write(value,address);}
void Mmc5Audio_Apply(u16 address,u8 value){sound_write(&mix_sound,address,value);}
u8 Mmc5Audio_Read(u16 address)
{
    if(address==0x5015)return (cpu_sound.p[0].length?1:0)|(cpu_sound.p[1].length?2:0);
    return 0; /* PCM read-mode monitoring/IRQ is outside this preview. */
}
void Mmc5Audio_Tick(u32 cycles){sound_tick(&cpu_sound,cycles);}
int Mmc5Audio_Sample(u32 cycles_fixed)
{
    static const u8 duties[4]={0x02,0x06,0x1e,0xf9};
    unsigned ch;int output=(int)mix_sound.pcm*32;u32 cycles;
    mix_sound.fraction+=cycles_fixed;cycles=mix_sound.fraction>>16;mix_sound.fraction&=65535;
    sound_tick(&mix_sound,cycles);
    for(ch=0;ch<2;ch++) {
        M5Pulse *p=&mix_sound.p[ch];unsigned volume=(p->control&16)?(p->control&15):p->env;
        unsigned ticks=(p->period+1u)*2;
        p->timer+=cycles;
        if(p->timer>=ticks){unsigned steps=p->timer/ticks;p->timer%=ticks;p->step=(u8)((p->step+steps)&7);}
        if(p->length && (mix_sound.enabled&(1u<<ch)))
            output+=((duties[p->control>>6]>>p->step)&1)?(int)volume*256:0;
    }
    return output;
}
