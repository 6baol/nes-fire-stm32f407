#include "game_app.h"
#include "game_core.h"
#include "renderer.h"
#include "bsp_joystick.h"
#include "bsp_joystick_hw.h"
#include "bsp_key.h"
#include "bsp_beep.h"
#include "bsp_uart1.h"
#include "lcd_touch.h"
#include <stdio.h>
#include <string.h>

typedef struct { uint8_t raw,stable;uint32_t changed; } Button;
static Game game;
static GameInput input;
static GameMetrics metrics;
static Button sw,key1,key2;
static uint32_t last_cycles,accumulator,step_cycles,cycles_per_us;
static uint32_t render_start,frame_due,touch_due,stats_due,frames,beep_until;
static char serial_line[192];
static unsigned serial_pos,serial_size;
static uint8_t touching;

static uint8_t button(Button *b,uint8_t raw,uint32_t now)
{
    if(raw!=b->raw) { b->raw=raw;b->changed=now; }
    if(b->stable!=raw && (uint32_t)(now-b->changed)>=20) {
        b->stable=raw;return raw;
    }
    return 0;
}

void GameApp_Init(uint8_t touch_ok,uint8_t sram_ok,uint32_t fill_us)
{
    GameCore_Init(&game);Renderer_Init();memset(&input,0,sizeof(input));
    metrics.touch_ok=touch_ok;metrics.sram_ok=sram_ok;metrics.fill_us=fill_us;
    cycles_per_us=HAL_RCC_GetHCLKFreq()/1000000u;
    step_cycles=HAL_RCC_GetHCLKFreq()/GAME_TICK_HZ;
    last_cycles=DWT->CYCCNT;
    stats_due=HAL_GetTick()+1000;frame_due=DWT->CYCCNT;
}

static void poll_input(uint32_t now)
{
    uint8_t a,b,c;
    const JoystickState *joy;
    Joystick_Poll(now);joy=Joystick_Get();
    a=button(&sw,HAL_GPIO_ReadPin(JOYSTICK_SW_PORT,JOYSTICK_SW_PIN)==GPIO_PIN_RESET,now);
    b=button(&key1,HAL_GPIO_ReadPin(KEY1_GPIO_PORT,KEY1_PIN)==GPIO_PIN_SET,now);
    c=button(&key2,HAL_GPIO_ReadPin(KEY2_GPIO_PORT,KEY2_PIN)==GPIO_PIN_SET,now);
    input.x=joy->x;input.y=joy->y;input.ready=joy->calibrated && joy->healthy;
    input.slow=key1.stable;
    input.confirm|=a||c;input.bomb|=a;input.pause|=c;input.diagnostic|=b;
    if(b && game.mode==GAME_DIAGNOSTIC) Joystick_Calibrate();
    if(metrics.touch_ok && (int32_t)(now-touch_due)>=0) {
        uint8_t result;touch_due=now+20;
        result=LCD_Touch_Get_Points_Data(touch_points,&touch_points_num);
        if(result==0) {
            if(touch_points_num>0 && !touching) { input.confirm=1;input.pause=1; }
            touching=touch_points_num>0;
        } else if(result!=3) touching=0;
    }
}

static void poll_log(uint32_t now)
{
    if(serial_pos<serial_size && __HAL_UART_GET_FLAG(&Uart1Handle,UART_FLAG_TXE)) {
        Uart1Handle.Instance->DR=(uint8_t)serial_line[serial_pos++];
    }
    if((int32_t)(now-stats_due)<0) return;
    metrics.fps=frames;frames=0;stats_due=now+1000;
    if(serial_pos>=serial_size) {
        const JoystickState *j=Joystick_Get();
        int size=snprintf(serial_line,sizeof(serial_line),
            "fps=%lu draw=%lu max=%lu logic=%lu over=%lu adc=%u,%u ready=%u err=%lu bullets=%u drop=%lu\r\n",
            (unsigned long)metrics.fps,(unsigned long)metrics.render_us,
            (unsigned long)metrics.render_max_us,(unsigned long)metrics.logic_max_us,
            (unsigned long)metrics.overruns,j->raw_x,j->raw_y,j->calibrated,
            (unsigned long)j->errors,GameCore_BulletCount(&game),(unsigned long)game.dropped_bullets);
        serial_size=size>0?(unsigned)size:0;
        if(serial_size>=sizeof(serial_line)) serial_size=sizeof(serial_line)-1;
        serial_pos=0;
    }
}

void GameApp_Poll(void)
{
    uint32_t now=HAL_GetTick(),cycles=DWT->CYCCNT,elapsed=cycles-last_cycles;
    unsigned steps=0;
    last_cycles=cycles;
    /* CYCCNT subtraction is wrap safe when called at least once per 25 seconds. */
    if(elapsed>step_cycles*4) { elapsed=step_cycles*4;++metrics.overruns; }
    accumulator+=elapsed;
    poll_input(now);
    while(accumulator>=step_cycles && steps<4) {
        uint32_t start=DWT->CYCCNT,us;
        uint8_t lives=game.lives,bombs=game.bombs;
        GameMode previous_mode=game.mode;
        GameCore_Update(&game,&input);
        input.confirm=input.bomb=input.pause=input.diagnostic=0;
        us=(DWT->CYCCNT-start)/cycles_per_us;
        if(us>metrics.logic_max_us) metrics.logic_max_us=us;
        if(previous_mode==GAME_PLAYING && (lives>game.lives || bombs>game.bombs)) {
            BEEP_ON;beep_until=now+60;
        }
        accumulator-=step_cycles;++steps;
    }
    if(accumulator>=step_cycles) { accumulator%=step_cycles;++metrics.overruns; }
    if(beep_until && (int32_t)(now-beep_until)>=0) { BEEP_OFF;beep_until=0; }
    if(!Renderer_Busy() && (int32_t)(DWT->CYCCNT-frame_due)>=0) {
        uint32_t period=HAL_RCC_GetHCLKFreq()/(game.mode==GAME_PLAYING?GAME_RENDER_HZ:5u);
        Renderer_Begin(&game,Joystick_Get(),&metrics);
        render_start=DWT->CYCCNT;
        frame_due+=period;
        if((int32_t)(render_start-frame_due)>=0) frame_due=render_start+period;
    }
    if(Renderer_Busy()) {
        uint32_t batch_start=DWT->CYCCNT;
        do {
            Renderer_Poll();
        } while(Renderer_Busy() &&
                DWT->CYCCNT-batch_start < GAME_RENDER_BUDGET_US*cycles_per_us);
        if(!Renderer_Busy()) {
            metrics.render_us=(DWT->CYCCNT-render_start)/cycles_per_us;
            if(metrics.render_us>metrics.render_max_us) metrics.render_max_us=metrics.render_us;
            ++frames;
        }
    }
    poll_log(now);
}
