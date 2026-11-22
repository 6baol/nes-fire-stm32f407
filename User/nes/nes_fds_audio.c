/* FDS wavetable/envelopes/modulation, written for this firmware.
 * Register and pitch arithmetic: NESdev FDS_audio. Sampling is per output
 * sample, not a cycle/dot accurate model of the 2C33 multiplier or analog RC. */
#include "nes_fds_audio.h"
#include "nes_apu.h"
#include <string.h>
typedef struct {uint8_t control,gain;uint32_t timer;} FdsEnvelope;
typedef struct {
    uint8_t wave[64],modulation[64];
    FdsEnvelope env[2];
    uint32_t wave_phase,mod_phase;
    uint16_t wave_pitch,mod_pitch;
    int16_t held_output;
    uint8_t wave_control,mod_control,master_control,master_speed;
    uint8_t counter,io,volume,clock16;
} FdsSound;
static FdsSound cpu_sound,mix_sound;
static uint32_t cpu_time,sample_fraction;
extern uint32_t clocks;
static const int8_t mod_delta[8]={0,1,2,4,0,-4,-2,-1};
static void step_counter(FdsSound *s,unsigned pos)
{
    unsigned cmd=s->modulation[pos&63];
    s->counter=cmd==4?0:(uint8_t)((s->counter+mod_delta[cmd])&127);
}
static void advance(FdsSound *s,uint32_t cycles)
{
    unsigned i;uint64_t phase;uint32_t steps,start,ticks,pitch;
    phase=(uint64_t)s->clock16+cycles;ticks=(uint32_t)(phase>>4);s->clock16=(uint8_t)(phase&15);
    if(!(s->wave_control&0xc0)&&s->master_speed) {
        for(i=0;i<2;i++)if(!(s->env[i].control&0x80)) {
            FdsEnvelope *e=&s->env[i];
            uint32_t period=8u*((e->control&63u)+1u)*((unsigned)s->master_speed+1u);
            uint32_t elapsed=e->timer+cycles,count;
            /* Normal sample steps fit in 32 bits: use Cortex-M4 UDIV rather
             * than two software 64-bit divisions for every envelope/sample.
             * Keep the wide path for a CPU read after a very long interval. */
            if(elapsed>=cycles){count=elapsed/period;e->timer=elapsed-count*period;}
            else {
                uint64_t wide=(uint64_t)e->timer+cycles;
                count=(uint32_t)(wide/period);e->timer=(uint32_t)(wide%period);
            }
            if(e->control&0x40){if(e->gain<32)e->gain=(uint8_t)(count>32u-e->gain?32:e->gain+count);}
            else e->gain=(uint8_t)(count>e->gain?0:e->gain-count);
        }
    }
    if(!(s->mod_control&0x80)&&s->mod_pitch) {
        start=s->mod_phase>>12;
        phase=(uint64_t)s->mod_phase+(uint64_t)ticks*s->mod_pitch;
        steps=(uint32_t)(phase>>12)-start;s->mod_phase=(uint32_t)phase&0x3ffff;
        /* A lazy CPU register read may span many complete table turns. */
        if(steps>=64) {
            uint32_t turns=steps/64;int sum=0,reset=0;
            for(i=0;i<64;i++){unsigned cmd=s->modulation[i];sum+=mod_delta[cmd];if(cmd==4)reset=1;}
            if(reset){for(i=0;i<64;i++)step_counter(s,start+i);}
            else s->counter=(uint8_t)((s->counter+(uint32_t)(sum*(int32_t)(turns&127)))&127);
            steps%=64;
        }
        for(i=0;i<steps;i++)step_counter(s,start+i);
    }
    {
        int counter=s->counter<64?s->counter:(int)s->counter-128;
        int product=counter*s->env[1].gain;
        if((product&15)&&!(product&0x800))product+=32;
        pitch=((unsigned)s->wave_pitch*(unsigned)(((product+0x400)>>4)&255))&0xfffff;
    }
    if(s->wave_control&0x80)s->wave_phase=0;
    phase=(uint64_t)s->wave_phase+(s->wave_control&0x80?0:(uint64_t)ticks*pitch);
    if((s->wave_phase>>18)==0||(phase>>24))s->volume=s->env[0].gain>32?32:s->env[0].gain;
    s->wave_phase=(uint32_t)phase&0xffffff;
    if(!(s->master_control&0x80))
        s->held_output=(int16_t)(((int)s->wave[s->wave_phase>>18]-32)*s->volume);
}
static void apply(FdsSound *s,uint16_t address,uint8_t value)
{
    if(address==0x4023){s->io=(value>>1)&1;return;}
    if(!s->io)return;
    if(address>=0x4040&&address<0x4080) {
        if(s->master_control&0x80)s->wave[address-0x4040]=value&63;
        return;
    }
    switch(address) {
    case 0x4080:case 0x4084: {
        FdsEnvelope *e=&s->env[address==0x4084];e->control=value;e->timer=0;
        if(value&0x80)e->gain=value&63;
        if(address==0x4080&&(value&0xbf)==0x80){s->volume=0;s->held_output=0;}
        break;
    }
    case 0x4082:s->wave_pitch=(uint16_t)((s->wave_pitch&0xf00)|value);break;
    case 0x4083:
        s->wave_pitch=(uint16_t)((s->wave_pitch&255)|((value&15)<<8));s->wave_control=value;
        if(value&0x80)s->wave_phase=0;
        if(value&0x40)s->env[0].timer=s->env[1].timer=0;
        break;
    case 0x4085:s->counter=value&127;break;
    case 0x4086:s->mod_pitch=(uint16_t)((s->mod_pitch&0xf00)|value);break;
    case 0x4087:
        s->mod_pitch=(uint16_t)((s->mod_pitch&255)|((value&15)<<8));s->mod_control=value;
        if(value&0x80)s->mod_phase&=0x3f000;
        break;
    case 0x4088:
        if(s->mod_control&0x80) {
            unsigned p=s->mod_phase>>12;
            unsigned pair=p&62;
            s->modulation[pair]=s->modulation[pair+1]=value&7;
            s->mod_phase=((p+2)&63)<<12;
        }
        break;
    case 0x4089:s->master_control=value;break;
    case 0x408a:s->master_speed=value;s->env[0].timer=s->env[1].timer=0;break;
    default:break;
    }
    if(s->wave_control&0x80)s->volume=s->env[0].gain>32?32:s->env[0].gain;
}
void FdsAudio_Reset(void)
{
    memset(&cpu_sound,0,sizeof(cpu_sound));
    cpu_sound.env[0].control=cpu_sound.env[1].control=0x80;
    cpu_sound.wave_control=cpu_sound.mod_control=0x80;
    cpu_sound.master_speed=0xff;mix_sound=cpu_sound;cpu_time=clocks;sample_fraction=0;
}
void FdsAudio_Write(uint16_t address,uint8_t value)
{
    uint32_t now=clocks;advance(&cpu_sound,now-cpu_time);cpu_time=now;
    apply(&cpu_sound,address,value);Apu_Write(value,address);
}
uint8_t FdsAudio_Read(uint16_t address)
{
    uint32_t now=clocks;advance(&cpu_sound,now-cpu_time);cpu_time=now;
    if(!cpu_sound.io)return 0;
    if(address>=0x4040&&address<0x4080)
        return cpu_sound.wave[(cpu_sound.master_control&0x80)?address-0x4040:cpu_sound.wave_phase>>18];
    if(address==0x4090)return cpu_sound.env[0].gain|0x40;
    if(address==0x4092)return cpu_sound.env[1].gain|0x40;
    if(address==0x4091)return (uint8_t)(cpu_sound.wave_phase>>12);
    if(address==0x4093)return (uint8_t)((cpu_sound.mod_phase>>5)&127);
    if(address==0x4095) {
        static const uint8_t next_delta[8]={0,1,2,4,12,12,14,15};
        return next_delta[cpu_sound.modulation[cpu_sound.mod_phase>>12]];
    }
    return 0;
}
void FdsAudio_Apply(uint16_t address,uint8_t value){apply(&mix_sound,address,value);}
int FdsAudio_Sample(uint32_t cycles_per_sample_q16)
{
    sample_fraction+=cycles_per_sample_q16;
    advance(&mix_sound,sample_fraction>>16);sample_fraction&=65535;
    return mix_sound.held_output*4/(2+(mix_sound.master_control&3));
}
