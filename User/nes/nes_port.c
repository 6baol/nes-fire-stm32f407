#include <stdio.h>
#include <string.h>
#include "nes_port.h"
#include "nes_main.h"
#include "nes_menu.h"
#include "nes_roms.h"
#include "nes_library.h"
#include "nes_fds_bios.h"
#include "nes_fds.h"
#include "bsp_nes_audio.h"
#include "lcd_draw.h"
#include "pixel_font.h"
#include "bsp_lcd_display.h"
#include "bsp_joystick.h"
#include "bsp_joystick_hw.h"
#include "bsp_key.h"
#include "bsp_touchpad.h"
#include "lcd_touch.h"
#include "stm32f4xx.h"
extern volatile uint32_t nes_faults;
typedef struct {uint8_t raw,stable;uint32_t changed;} Button;
static Button a,b,start;
static uint8_t rpg_direction;
__attribute__((noinline)) unsigned NesPort_RenderDivisor(unsigned requested,unsigned draw_us,unsigned skip_us,unsigned rpg)
{
    unsigned need;
    if(requested<2)requested=2;if(requested>8)requested=8;
    /* Reserve 0.67 ms per logic frame for audio/input and foreground work.
     * Mean cost = skip + (draw-skip)/divisor. Native games keep their cadence. */
    if(rpg && draw_us>16000u && skip_us<16000u) {
        unsigned budget=16000u-skip_us;
        need=(draw_us-skip_us+budget-1)/budget;
        if(need>requested)requested=need>8?8:need;
    }
    return requested;
}
/* The RPG accepts an action more reliably without a simultaneous held D-pad.
 * Four-way axis hysteresis also avoids adjacent rows from diagonal ADC noise.
 * Releasing A/B/Start resumes a held stick; no recenter/calibration required. */
__attribute__((noinline)) uint8_t NesPort_RpgPad(uint8_t buttons,int x,int y)
{
    int ax=x<0?-x:x,ay=y<0?-y:y;
    uint8_t direction=0;
    buttons&=15;
    if(buttons&11){rpg_direction=0;return buttons;}
    if((rpg_direction==64&&x<=-220)||(rpg_direction==128&&x>=220)) {
        if(ay<ax+160)direction=rpg_direction;
    } else if((rpg_direction==16&&y<=-220)||(rpg_direction==32&&y>=220)) {
        if(ax<ay+160)direction=rpg_direction;
    }
    if(!direction && (ax>=360||ay>=360))
        direction=ax>=ay?(x>0?128:64):(y>0?32:16);
    rpg_direction=direction;
    return buttons|direction;
}
static uint32_t next_frame,touch_due,stats_due,logic_frames,draw_frames;
static uint8_t touch_available,touch_pad,loaded;
static uint16_t xmap[480];
/* SWD diagnostics: one requested RGB565 frame at 0x6c040000. No copy otherwise. */
volatile uint32_t nes_capture_request,nes_capture_ready;
volatile uint32_t nes_logic_total,nes_draw_total,nes_logic_hz,nes_draw_hz;
volatile uint8_t nes_test_pad;
/* SWD-only opt-in for synthetic snapshot experiments, never inferred from a
 * cartridge's reset vector. Normal menu operation keeps this disabled. */
volatile uint8_t nes_fds_snapshot_test_only;
volatile uint32_t nes_render_divisor=3,nes_draw_frame_us,nes_skip_frame_us,nes_clock_drops;
volatile uint32_t nes_effective_render_divisor=3;
volatile uint32_t nes_menu_redraw_us,nes_menu_updates;
static uint8_t capturing;
static uint32_t cap_status_due,cap_last_count;
static uint8_t cap_last_pressed=255,cap_last_ready=255;
extern volatile uint32_t touchpad_press_count;

enum {APP_MENU=0,APP_GAME=1,APP_SETTINGS=2,APP_SEARCH=3};
static uint32_t settings_due;
static uint8_t settings_axis_armed,settings_center_seen;
static uint32_t settings_center_due;
static uint8_t app_state=APP_MENU;
static NesMenuState menu;
static uint8_t sw_hold_active;
static uint32_t sw_hold_start;
/* One deliberate deflection per selection. Re-arm only after a stable centre;
 * neither holding the stick nor bouncing across the threshold repeats it. */
static uint8_t menu_axis_armed;
static uint8_t menu_page_armed;
static uint8_t menu_center_seen;
static uint32_t menu_center_due;
static uint8_t menu_page_seen;
static uint32_t menu_page_due;
static uint8_t menu_armed;
static uint8_t cover_pending;
static uint32_t cover_due;
static uint8_t cap_search_armed=1;
static uint32_t key1_down;
static uint8_t key1_pending;
static NesSearchState search;
static uint8_t search_armed,search_center_seen,search_key_armed,search_ok_armed;
static uint32_t search_center_due;
static uint8_t stick_shown=255;
static char shown_status[48];
static char load_error[48];
static uint8_t disk_combo_latched;
static unsigned disk_shown=~0u;

#define SW_PRESSED (HAL_GPIO_ReadPin(JOYSTICK_SW_PORT,JOYSTICK_SW_PIN)==GPIO_PIN_RESET)
#define KEY2_PRESSED (HAL_GPIO_ReadPin(KEY2_GPIO_PORT,KEY2_PIN)==GPIO_PIN_SET)
#define KEY1_PRESSED (HAL_GPIO_ReadPin(KEY1_GPIO_PORT,KEY1_PIN)==GPIO_PIN_SET)

static void text(unsigned x,unsigned y,const char *s) {PixelFont_Text((uint16_t)x,(uint16_t)(y+4),s,WHITE,BLACK,2);}
/* Redraw the status line only when the message actually changes. */
static void menu_status(const char *msg)
{
    if(!msg) msg="";
    if(!strcmp(msg,shown_status)) return;
    strncpy(shown_status,msg,sizeof(shown_status)-1);
    shown_status[sizeof(shown_status)-1]='\0';
    NesMenu_Status(msg);
}
static uint8_t held(Button *b,uint8_t raw,uint32_t now)
{
    if(raw!=b->raw) {b->raw=raw;b->changed=now;}
    if((uint32_t)(now-b->changed)>=20) b->stable=raw;
    return b->stable;
}
void NesPort_Input(void)
{
    uint32_t now=HAL_GetTick();uint8_t pad=0,aa,bb,ss;
    const JoystickState *j;
    Joystick_Poll(now);j=Joystick_Get();
    Touchpad_Poll(now);
    if(Touchpad_Get()->pressed)pad|=4;
    aa=held(&a,HAL_GPIO_ReadPin(KEY2_GPIO_PORT,KEY2_PIN)==GPIO_PIN_SET,now);
    bb=held(&b,HAL_GPIO_ReadPin(KEY1_GPIO_PORT,KEY1_PIN)==GPIO_PIN_SET,now);
    ss=held(&start,SW_PRESSED,now);
    /* A and B are independent: Mario needs B held while A is pressed. */
    if(aa)pad|=1;
    if(bb)pad|=2;
    if(ss)pad|=8;
    if(j->healthy&&j->calibrated) {
        if(j->x>0.35f)pad|=128;if(j->x< -0.35f)pad|=64;
        if(j->y>0.35f)pad|=32;if(j->y< -0.35f)pad|=16;
    }
    if(touch_available && (int32_t)(now-touch_due)>=0) {
        unsigned i;uint8_t result;touch_due=now+20;
        result=LCD_Touch_Get_Points_Data(touch_points,&touch_points_num);
        if(result!=3) {
            touch_pad=0;
            if(result==0) for(i=0;i<(unsigned)(touch_points_num>0?touch_points_num:0)&&i<5;i++) {
                /* Portrait-coordinate mapping needs confirmation on the physical panel. */
                if(touch_points[i].y>=620 && touch_points[i].y<780 && touch_points[i].x<480)
                    touch_pad |= touch_points[i].x<240?4:8;
            }
        }
    }
    PADdata=pad|touch_pad|nes_test_pad;PADdata1=0;
    if(app_state==APP_GAME&&NesLibrary_InputProfile()==1) {
        if(j->healthy&&j->calibrated)PADdata=NesPort_RpgPad(PADdata,(int)(j->x*1024),(int)(j->y*1024));
        else PADdata=NesPort_RpgPad(PADdata,0,0);
    }
    if(app_state==APP_GAME&&MapperNo==20&&FdsDrive_Sides()>1) {
        uint8_t combo=PADdata&0xc4;
        if((combo&4)&&(combo&0xc0)) {
            if(!disk_combo_latched) {
                unsigned side=FdsDrive_Side(),count=FdsDrive_Sides();
                side=(combo&0x40)?(side?side-1:count-1):(side+1)%count;
                (void)FdsDrive_RequestSide(side);disk_combo_latched=1;
            }
            PADdata&=(uint8_t)~0xc4u;
        } else if(!(combo&0xc0))disk_combo_latched=0;
    } else disk_combo_latched=0;
}
void NesPort_Line(int line,const uint8_t *pixels,const uint16_t *palette)
{
    unsigned x,y,y0=(unsigned)line*450/240,y1=(unsigned)(line+1)*450/240;
    /* 256x240 -> 480x450, preserves aspect ratio and includes all pixels. */
    /* MMC5 borrows the diagnostic framebuffer for its larger ROM arena. */
    if(MapperNo==5){capturing=0;nes_capture_request=0;}
    if(line==0 && nes_capture_request) {capturing=1;nes_capture_request=0;}
    if(capturing) {
        volatile uint16_t *dest=(volatile uint16_t*)0x6c040000+line*256;
        for(x=0;x<256;x++)dest[x]=palette[pixels[x]&63];
        if(line==239){capturing=0;++nes_capture_ready;}
    }
    lcd_open_window(0,(uint16_t)(112+y0),480,(uint16_t)(y1-y0));
    /* 240 source lines cover 450 LCD rows, so convert the row once and repeat
     * the store instead of redoing 480 palette lookups for every output row. */
    {
        static uint16_t row[480];
        unsigned i;
        for(i=0;i<480;i++)row[i]=palette[pixels[xmap[i]]&63];
        for(y=y0;y<y1;y++){
            const uint16_t *src=row;
            for(x=0;x<480;x++)LCD_WRITE_DATA(*src++);
        }
    }
}

static void game_chrome(void)
{
    text(16,16,"NES FIRE EMULATOR");
    if(strlen(NesLibrary_Game((unsigned)menu.index)->label)>28)
        PixelFont_Text(16,58,NesLibrary_Game((unsigned)menu.index)->label,WHITE,BLACK,1);
    else text(16,54,NesLibrary_Game((unsigned)menu.index)->label);
    text(16,590,"STICK: D-PAD  SW: START");
    text(16,630,"KEY1: B       KEY2: A");
    text(16,670,"CAP KEY: SELECT");
    if(MapperNo==20&&FdsDrive_Sides()>1)text(16,734,"SELECT + L/R: DISK SIDE");
    else text(16,734,"TOUCH: SELECT | START");
    disk_shown=~0u;
    text(16,776,"HOLD SW 1.5S: MENU        ");
    cap_status_due=0;cap_last_pressed=255;cap_last_ready=255;
    stick_shown=255;
}

static void enter_menu(void)
{
    rpg_direction=0;
    NesAudio_Mute(1);
    if(NesLibrary_SavePending()) {
        lcd_fill_color(16,732,448,36,BLACK);
        text(16,734,"SAVING...");
    }
    (void)NesLibrary_Save();
    loaded=0;
    NesLibrary_EnterMenu();
    app_state=APP_MENU;
    sw_hold_active=0;
    menu_axis_armed=0;menu_page_armed=0;menu_center_seen=0;menu_page_seen=0;menu_armed=0;key1_pending=0;
    shown_status[0]='\0';
    load_error[0]='\0';
    NesMenu_Draw(&menu);
}

static void start_selected(void)
{
    const NesRomImage *g;
    int result;
    if(menu.count==0) return;
    g=NesLibrary_Game((unsigned)menu.index);
    load_error[0]='\0';
    lcd_fill_color(0,0,480,800,BLACK);
    text(16,380,"LOADING ...");
    result=NesLibrary_Load((unsigned)menu.index);
    /* A reset below $8000 does not establish that this is a bootable FDS
     * snapshot. The experimental snapshot loader has no disk drive; keep
     * malformed cartridges out of that path until a real FDS image is loaded. */
    if(nes_fds_snapshot_test_only && result==5)
        result=Nes_LoadFds(g->data,g->size,nes_fds_bios,nes_fds_bios_size);
    printf("NES load=%d file=%s bytes=%lu mapper=%d\r\n",result,g->file,
        (unsigned long)g->size,MapperNo);
    if(result) {
        NesLibrary_EnterMenu();
        NesMenu_Draw(&menu);
        shown_status[0]='\0';
        if(result==10) snprintf(load_error,sizeof(load_error),"%s",NesLibrary_Error());
        else if(result==5) snprintf(load_error,sizeof(load_error),"BOOT ERROR - NEED .FDS");
        else if(result==7) snprintf(load_error,sizeof(load_error),"FDS VALID - DRIVE NOT READY");
        else if(result==8) snprintf(load_error,sizeof(load_error),"INVALID FDS DISK IMAGE");
        else if(result==9) snprintf(load_error,sizeof(load_error),"BAD FDS BIOS - NEED DISKSYS.ROM");
        else snprintf(load_error,sizeof(load_error),"ROM REJECTED rc=%d - SEE UART",result);
        menu_status(load_error);
        return;
    }
    NesAudio_Mute(0);
    loaded=1;app_state=APP_GAME;
    rpg_direction=0;
    game_chrome();
    logic_frames=draw_frames=0;
    next_frame=DWT->CYCCNT;stats_due=HAL_GetTick()+1000;
}

static void menu_redraw_selection(void)
{
    uint32_t started=DWT->CYCCNT;
    NesMenu_DrawRows(&menu);
    cover_pending=1;cover_due=HAL_GetTick()+60;
    nes_menu_redraw_us=(DWT->CYCCNT-started)/(HAL_RCC_GetHCLKFreq()/1000000u);
    ++nes_menu_updates;
}
static void open_search(void)
{
    NesSearch_Init(&search);
    search_armed=0;search_center_seen=0;
    /* The key that opened this page may still be held: arm on release. */
    search_key_armed=0;search_ok_armed=0;
    sw_hold_active=0;cover_pending=0;
    app_state=APP_SEARCH;
    NesSearch_Draw(&search);
}
static void search_poll(uint32_t now)
{
    const JoystickState *j=Joystick_Get();
    int dx=0,dy=0,centered=0;
    if(j->healthy&&j->calibrated) {
        dx=j->x>0.65f?1:(j->x< -0.65f?-1:0);
        dy=j->y>0.65f?1:(j->y< -0.65f?-1:0);
        centered=j->x<0.25f&&j->x> -0.25f&&j->y<0.25f&&j->y> -0.25f;
    }
    if(nes_test_pad&0x30){dy=(nes_test_pad&0x10)?-1:1;centered=0;}
    if(nes_test_pad&0xc0){dx=(nes_test_pad&0x40)?-1:1;centered=0;}
    if(centered) {
        if(!search_center_seen){search_center_seen=1;search_center_due=now+60;}
        if((int32_t)(now-search_center_due)>=0)search_armed=1;
    } else search_center_seen=0;
    if((dx||dy)&&search_armed){
        search_armed=0;
        NesSearch_Move(&search,dx,dy);
        NesSearch_Draw(&search);
    }
    if(KEY1_PRESSED||(nes_test_pad&2)) {
        if(search_key_armed){search_key_armed=0;app_state=APP_MENU;NesMenu_Draw(&menu);return;}
    } else search_key_armed=1;
    if(KEY2_PRESSED||SW_PRESSED||(nes_test_pad&1)) {
        if(search_ok_armed) {
            search_ok_armed=0;
            if(NesSearch_Select(&search)==1) {
                unsigned n=NesLibrary_Search(search.query);
                menu.count=(uint16_t)n;
                menu.index=0;menu.first=0;
                app_state=APP_MENU;
                NesMenu_Draw(&menu);
                if(n){char msg[24];snprintf(msg,sizeof(msg),"%u MATCHES",n);menu_status(msg);}
                else menu_status("NO MATCH - FULL LIST");
            }
        }
    } else search_ok_armed=1;
}
static void menu_poll(uint32_t now)
{
    const JoystickState *j=Joystick_Get();
    int dir=0,page=0,cy=0,cx=0;
    /* The cover is read from the card only after the stick has settled. */
    if(cover_pending&&(int32_t)(now-cover_due)>=0){cover_pending=0;NesMenu_DrawCover(&menu);}
    {
        /* Capacitive key is free in the menu and opens search directly. */
        const TouchpadState *cap=Touchpad_Get();
        if(cap->ready&&cap->pressed){
            if(cap_search_armed){cap_search_armed=0;open_search();return;}
        } else cap_search_armed=1;
    }
    if(j->healthy&&j->calibrated) {
        if(j->y>0.65f) dir=1; else if(j->y< -0.65f) dir=-1;
        if(j->x>0.65f) page=1; else if(j->x< -0.65f) page=-1;
        cy=j->y<0.25f && j->y> -0.25f;
        cx=j->x<0.25f && j->x> -0.25f;
        /* A diagonal push must not both move and page. */
        if(dir&&page){if((j->y<0?-j->y:j->y)>=(j->x<0?-j->x:j->x))page=0;else dir=0;}
    }
    if(nes_test_pad&0x30){dir=(nes_test_pad&0x10)?-1:1;cy=0;}
    if(nes_test_pad&0xc0){page=(nes_test_pad&0x40)?-1:1;cx=0;}
    /* Each axis arms on its own stable centre, so paging and selecting never
     * block each other and holding a direction never repeats. */
    if(cy) {
        if(!menu_center_seen){menu_center_seen=1;menu_center_due=now+60;}
        if((int32_t)(now-menu_center_due)>=0)menu_axis_armed=1;
    } else menu_center_seen=0;
    if(cx) {
        if(!menu_page_seen){menu_page_seen=1;menu_page_due=now+60;}
        if((int32_t)(now-menu_page_due)>=0)menu_page_armed=1;
    } else menu_page_seen=0;
    if(dir && menu_axis_armed) {
        menu_axis_armed=0;
        if(NesMenu_Move(&menu,dir)){load_error[0]='\0';menu_redraw_selection();}
    }
    if(page && menu_page_armed) {
        menu_page_armed=0;
        if(NesMenu_Page(&menu,page,5)){load_error[0]='\0';menu_redraw_selection();}
    }
    if(KEY1_PRESSED||KEY2_PRESSED||SW_PRESSED||(nes_test_pad&3)) {
        int k1=KEY1_PRESSED||(nes_test_pad&2);
        if(k1) {
            /* Short press opens Settings; holding for one second opens Search. */
            if(!key1_pending){key1_pending=1;key1_down=now;}
            else if((uint32_t)(now-key1_down)>=1000){
                key1_pending=0;menu_armed=0;open_search();return;
            }
        } else if(menu_armed) {
            menu_armed=0;
            if(KEY2_PRESSED||SW_PRESSED||(nes_test_pad&1)) start_selected();
            return;
        }
    } else {
        menu_armed=1;
        if(key1_pending){
            key1_pending=0;
            if((uint32_t)(now-key1_down)<1000){
                app_state=APP_SETTINGS;sw_hold_active=0;settings_due=now;
                settings_axis_armed=settings_center_seen=0;
                NesSettings_Draw(menu.audio_ok);
                NesSettings_Audio((uint8_t)NesAudio_GetOutput(),menu.audio_ok,0);
                return;
            }
        }
    }
    if(load_error[0])menu_status(load_error);
    else if(NesLibrary_ViewActive())menu_status("FILTERED - HOLD KEY1 TO SEARCH");
    else if(!strncmp(NesLibrary_Status(),"SD SAVE",7))menu_status(NesLibrary_Status());
    else if(!j->healthy||!j->calibrated) menu_status("CENTER STICK TO CALIBRATE");
    else if(j->errors) menu_status("STICK ERROR - CHECK WIRING");
    else menu_status(load_error[0]?load_error:NesLibrary_Status());
}

void NesApp_Init(uint8_t touch_ok)
{
    unsigned x;int result;
    touch_available=touch_ok;
    Touchpad_Init();
    for(x=0;x<480;x++)xmap[x]=(uint16_t)(x*256/480);
    lcd_fill_color(0,0,480,800,BLACK);
    text(16,16,"NES FIRE EMULATOR");
    text(16,54,"AUDIO: INITIALIZING");
    result=NesAudio_Init();
    printf("Audio init=%d (WM8978 selectable output, 11025Hz)\r\n",result);
    NesAudio_Mute(1);
    text(16,94,"SD: LOADING LIBRARY");
    printf("SD library=%d\r\n",NesLibrary_Boot());
    NesMenu_Init(&menu,(uint16_t)NesLibrary_Count(),result==0,touch_ok);
    printf("Games=%u\r\n",NesLibrary_Count());
    app_state=APP_MENU;
    loaded=0;
    menu_axis_armed=0;menu_page_armed=0;menu_center_seen=0;menu_page_seen=0;menu_armed=0;key1_pending=0;
    shown_status[0]='\0';
    NesMenu_Draw(&menu);
    if(result) menu_status("AUDIO OFF - CHECK CODEC");
    else menu_status(NesLibrary_Status());
}
void NesApp_Poll(void)
{
    uint32_t now=HAL_GetTick(),cycles=DWT->CYCCNT,period=HAL_RCC_GetHCLKFreq()/60;
    static uint32_t total;
    const TouchpadState *cap=Touchpad_Get();
    NesPort_Input();
    if(app_state==APP_MENU) {menu_poll(now);return;}
    if(app_state==APP_SEARCH) {search_poll(now);return;}
    /* Long press of SW leaves the game and returns to the menu. */
    if(SW_PRESSED) {
        if(!sw_hold_active) {sw_hold_active=1;sw_hold_start=now;}
        else if((uint32_t)(now-sw_hold_start)>=1500) {enter_menu();return;}
    } else sw_hold_active=0;
    if(app_state==APP_SETTINGS) {
        const JoystickState *j=Joystick_Get();
        int dir=0,centered=0;
        if(j->healthy&&j->calibrated) {
            dir=j->x>0.65f?1:j->x< -0.65f?-1:0;
            centered=j->x<0.25f && j->x> -0.25f;
        }
        if(nes_test_pad&0xc0){dir=(nes_test_pad&0x40)?-1:1;centered=0;}
        if(centered) {
            if(!settings_center_seen){settings_center_seen=1;settings_center_due=now+60;}
            if((int32_t)(now-settings_center_due)>=0)settings_axis_armed=1;
        } else {
            settings_center_seen=0;
            if(dir&&settings_axis_armed) {
                int output=(int)NesAudio_GetOutput()+dir;
                uint8_t failed;
                settings_axis_armed=0;
                if(output<0)output=NES_AUDIO_OFF;if(output>NES_AUDIO_OFF)output=0;
                failed=NesAudio_SetOutput((NesAudioOutput)output);
                NesSettings_Audio((uint8_t)NesAudio_GetOutput(),menu.audio_ok,failed);
            }
        }
        if((int32_t)(now-settings_due)>=0) {
            settings_due=now+50;
            NesSettings_Update(PADdata,j->raw_x,j->raw_y,j->healthy&&j->calibrated,cap->ready,cap->raw);
        }
        return;
    }
    {
        const JoystickState *joy=Joystick_Get();
        uint8_t status=!joy->calibrated?0:joy->healthy?1:2;
        if(stick_shown!=status) {
            stick_shown=status;
            text(16,776,status==1?"HOLD SW 1.5S: MENU        ":
                status==2?"STICK RECONNECTING        ":"CENTER STICK TO CALIBRATE ");
        }
    }
    if((int32_t)(now-cap_status_due)>=0 || cap->pressed!=cap_last_pressed ||
       cap->ready!=cap_last_ready || touchpad_press_count!=cap_last_count) {
        char status[30];
        cap_last_pressed=cap->pressed;cap_last_ready=cap->ready;cap_last_count=touchpad_press_count;
        cap_status_due=now+200;
        snprintf(status,sizeof(status),"CAP:%s %u/%u N:%lu  ",
            !cap->ready?"CAL":cap->pressed?"ON ":"OFF",cap->raw,cap->baseline,
            (unsigned long)(touchpad_press_count%1000));
        text(16,700,status);
    }
    if(!loaded)return;
    if(MapperNo==20&&FdsDrive_Sides()>1) {
        unsigned side=FdsDrive_Side(),changing=(unsigned)FdsDrive_Changing();
        unsigned missing=FdsIo_Read(0x4032)&1;
        unsigned shown=side|(changing<<8)|(missing<<9);
        if(shown!=disk_shown) {
            char label[40];disk_shown=shown;
            snprintf(label,sizeof(label),"DISK %u%c  %s",side/2+1,'A'+side%2,
                     changing?"INSERTING...":missing?"INSERT FAILED":"INSERTED");
            lcd_fill_color(16,758,448,12,BLACK);
            PixelFont_Text(16,758,label,WHITE,BLACK,1);
        }
    }
    if((int32_t)(cycles-next_frame)>=0) {
        uint32_t divisor=nes_render_divisor,start_cycles=DWT->CYCCNT,frame_us;
        int draw;
        divisor=NesPort_RenderDivisor(divisor,nes_draw_frame_us,nes_skip_frame_us,NesLibrary_InputProfile());
        nes_effective_render_divisor=divisor;
        draw=(total++%divisor)==0;
        Nes_Frame(draw);frame_us=(DWT->CYCCNT-start_cycles)/(HAL_RCC_GetHCLKFreq()/1000000u);
        if(draw)nes_draw_frame_us=frame_us;else nes_skip_frame_us=frame_us;
        logic_frames++;nes_logic_total++;if(draw){draw_frames++;nes_draw_total++;}
        next_frame+=period;
        /* Carry the debt from an expensive LCD frame into subsequent cheap
         * logic frames instead of discarding virtual NES time every draw. */
        if((int32_t)(DWT->CYCCNT-next_frame)>(int32_t)(period*4)) {
            next_frame=DWT->CYCCNT;++nes_clock_drops;
        }
    }
    if((int32_t)(now-stats_due)>=0) {
        nes_logic_hz=logic_frames;nes_draw_hz=draw_frames;
        printf("NES logic=%lu draw=%lu faults=%lu pad=%02x adc=%u,%u ready=%u\r\n",
          (unsigned long)logic_frames,(unsigned long)draw_frames,(unsigned long)nes_faults,
          PADdata,Joystick_Get()->raw_x,Joystick_Get()->raw_y,Joystick_Get()->calibrated);
        logic_frames=draw_frames=0;stats_due=HAL_GetTick()+1000;
    }
}
