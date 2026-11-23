#include <stdio.h>
#include <string.h>
#include "nes_port.h"
#include "nes_main.h"
#include "nes_menu.h"
#include "nes_roms.h"
#include "nes_library.h"
#include "nes_import.h"
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
__attribute__((noinline)) unsigned NesPort_RenderDivisor(unsigned requested,unsigned draw_us,unsigned skip_us)
{
    unsigned need=1;
    /* A display interval of N costs one draw and N-1 logic-only frames.
     * Keep 0.67 ms per frame available for the rest of the foreground loop. */
    if(draw_us>16000u) {
        if(skip_us<16000u)need=1u+(draw_us-skip_us-1u)/(16000u-skip_us);
        else if(draw_us>skip_us)need=8;
    }
    if(requested>need)need=requested;
    return need>8?8:need;
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
/* The F407 has 64 KiB of CPU-only CCM. Link this cache there so it cannot
 * overlap ROMs, decoded tiles or the diagnostic capture in external SRAM. */
static uint8_t displayed_pixels[240][256]
    __attribute__((section(".bss.ARM.__at_0x10000000"),aligned(4)));
static uint8_t displayed_valid[240];
static uint16_t displayed_palette[64];
volatile uint32_t nes_lcd_pixels,nes_lcd_us,nes_lcd_updates_total,nes_lcd_pixels_total;
static uint32_t lcd_frame_pixels,lcd_frame_cycles;
/* SWD diagnostics: one requested RGB565 frame at 0x6c040000. No copy otherwise. */
#define NES_CAPTURE_ADDR 0x6c040000u
#define NES_CAPTURE_BYTES (256u*240u*sizeof(uint16_t))
volatile uint32_t nes_capture_request,nes_capture_ready,nes_capture_rejected;
volatile uint32_t nes_logic_total,nes_draw_total,nes_logic_hz,nes_draw_hz;
volatile uint8_t nes_test_pad;
/* SWD-only opt-in for synthetic snapshot experiments, never inferred from a
 * cartridge's reset vector. Normal menu operation keeps this disabled. */
volatile uint8_t nes_fds_snapshot_test_only;
volatile uint32_t nes_render_divisor=1,nes_draw_frame_us,nes_skip_frame_us,nes_clock_drops;
volatile uint32_t nes_effective_render_divisor=1;
static uint32_t mean_draw_us,mean_skip_us,undrawn_remaining,faster_samples;
volatile uint32_t nes_menu_redraw_us,nes_menu_updates;
volatile uint32_t nes_library_boot_ms,nes_search_ms,nes_load_ms,nes_save_ms;
static uint8_t capturing;
static uint32_t cap_status_due,cap_last_count;
static uint8_t cap_last_pressed=255,cap_last_ready=255;
extern volatile uint32_t touchpad_press_count;

enum {APP_MENU=0,APP_GAME=1,APP_SETTINGS=2,APP_SEARCH=3,APP_LIBRARY=4,APP_SAVE_ERROR=5,APP_LIBRARY_CHECK=6};
static uint32_t settings_due;
static uint8_t settings_axis_armed,settings_center_seen;
static uint8_t settings_y_armed,settings_y_seen;
static uint32_t settings_y_due;
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
static uint32_t menu_repeat_due;
static uint8_t cover_pending;
static uint32_t cover_due;
static uint8_t cap_search_armed=1;
static uint32_t key1_down;
static uint8_t key1_pending;
static NesSearchState search;
static uint8_t search_armed,search_center_seen,search_key_armed,search_ok_armed;
static uint32_t search_center_due;
static uint8_t library_cursor,library_axis_armed,library_centered,library_key_armed;
static uint32_t library_center_due,library_progress_due;
static unsigned library_check_total;
static uint8_t save_error_armed;
static uint8_t stick_shown=255;
static char shown_status[48];
static char load_error[48];
static char notice[48],running_title[57];
static uint32_t notice_until;
volatile uint8_t nes_screen_landscape;
/* Panel scan modes: even = 480x800 portrait, odd = 800x480 rotated. Mode 3 is
 * the 90 degree counter-clockwise view the menus and the game are laid out for. */
uint8_t NesPort_SetLandscape(uint8_t on)
{
    static uint8_t applied;
    on=on?1:0;
    if(on==applied)return applied;
    applied=on;
    nes_screen_landscape=on;
    /* Mode 6 is the panel's native portrait; 7 is the quarter turn the case is
     * meant to be used in (mode 5 mirrors the other way). */
    lcd_gram_scan(on?3:6);
    lcd_fill_color(0,0,(uint16_t)(on?800u:480u),(uint16_t)(on?480u:800u),BLACK);
    return applied;
}
uint8_t NesPort_Landscape(void)
{
    return nes_screen_landscape;
}
static uint8_t disk_combo_latched;
static unsigned disk_shown=~0u;

/* Shield buttons A-F on CN3 18,20,22,24,26,28 - one column, so a single strip
 * reaches all six. K is the stick's push switch and already arrives as
 * JOYSTICK_SW on PB7. Active low against the internal pull-ups. */
typedef struct {GPIO_TypeDef *port;uint16_t pin;} PadPin;
static const PadPin pad_pins[6]={
    {GPIOC,GPIO_PIN_6},  /* A   CN3-18 */
    {GPIOC,GPIO_PIN_7},  /* B   CN3-20 */
    {GPIOE,GPIO_PIN_4},  /* C   CN3-22 */
    {GPIOB,GPIO_PIN_6},  /* D   CN3-24 */
    {GPIOE,GPIO_PIN_5},  /* E   CN3-26 */
    {GPIOE,GPIO_PIN_6}   /* F   CN3-28 */
};
#define PAD_A   0x01u
#define PAD_B   0x02u
#define PAD_C   0x04u
#define PAD_D   0x08u
#define PAD_E   0x10u
#define PAD_F   0x20u
#define PAD_ALL 0x3fu
static uint8_t pad_src,pad_stable;
static uint32_t pad_changed;
static void pad_init(void)
{
    static uint8_t done;
    GPIO_InitTypeDef io={0};
    unsigned i;
    if(done)return;done=1;
    __HAL_RCC_GPIOC_CLK_ENABLE();
    __HAL_RCC_GPIOB_CLK_ENABLE();
    __HAL_RCC_GPIOE_CLK_ENABLE();
    io.Mode=GPIO_MODE_INPUT;io.Pull=GPIO_PULLUP;io.Speed=GPIO_SPEED_FREQ_LOW;
    for(i=0;i<6;i++){io.Pin=pad_pins[i].pin;HAL_GPIO_Init(pad_pins[i].port,&io);}
    pad_src=PAD_ALL;
}
static uint8_t pad_poll(uint32_t now)
{
    uint8_t raw=0;
    unsigned i;
    pad_init();
    for(i=0;i<6;i++)if(HAL_GPIO_ReadPin(pad_pins[i].port,pad_pins[i].pin)==GPIO_PIN_RESET)raw|=(uint8_t)(1u<<i);
    if(raw!=pad_src){pad_src=raw;pad_changed=now;}
    if((uint32_t)(now-pad_changed)>=20)pad_stable=raw;
    return pad_stable;
}
#define SHIELD pad_stable
/* System screens belong to the board keys and the capacitive pad; the shield
 * only plays games (E is Select, F is Start). */
#define SW_PRESSED (HAL_GPIO_ReadPin(JOYSTICK_SW_PORT,JOYSTICK_SW_PIN)==GPIO_PIN_RESET)
#define KEY2_PRESSED (HAL_GPIO_ReadPin(KEY2_GPIO_PORT,KEY2_PIN)==GPIO_PIN_SET)
#define KEY1_PRESSED (HAL_GPIO_ReadPin(KEY1_GPIO_PORT,KEY1_PIN)==GPIO_PIN_SET)

static const char *const view_hints[]={
    "SEARCH RESULTS - HOLD KEY1 FOR LIBRARY", "LOADABLE HEADERS - HOLD KEY1 FOR LIBRARY",
    "UNSUPPORTED - HOLD KEY1 FOR LIBRARY", "FAVORITES - HOLD KEY1 FOR LIBRARY",
    "RECENTLY PLAYED - HOLD KEY1 FOR LIBRARY"
};

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

static void show_notice(const char *msg)
{
    snprintf(notice,sizeof(notice),"%s",msg);
    notice_until=HAL_GetTick()+3500;
    menu_status(notice);
}

static void menu_info(int probe)
{
    char info[56],reason[44];
    NesImportInfo import_info={0};
    unsigned mapper=0xffffu,index=(unsigned)menu.index;
    int result,favorite;
    if(!menu.count){NesMenu_Info("");return;}
    result=NesLibrary_Compatibility(index,probe,&mapper);
    favorite=NesLibrary_IsFavorite(index);
    import_info.mapper=(uint16_t)mapper;
    if(result==NES_LIBRARY_COMPAT_HEADER_OK) {
        if(mapper==20)snprintf(reason,sizeof(reason),"FDS - HEADER OK");
        else snprintf(reason,sizeof(reason),"MAPPER %u - HEADER OK",mapper);
    } else if(result==NES_LIBRARY_COMPAT_UNKNOWN)snprintf(reason,sizeof(reason),"HEADER NOT CHECKED");
    else if(result==NES_LIBRARY_COMPAT_READ_ERROR)snprintf(reason,sizeof(reason),"ROM READ ERROR");
    else NesImport_FormatReason(result,&import_info,reason,sizeof(reason));
    snprintf(info,sizeof(info),"%s%s",favorite?"FAVORITE  ":"",reason);
    NesMenu_Info(info);
}

static void draw_library(void)
{
    NesMenu_Draw(&menu);
    shown_status[0]='\0';
    menu_info(1);
}

static void update_menu_count(int keep_selection)
{
    menu.count=(uint16_t)NesLibrary_Count();
    if(!keep_selection||!menu.count){menu.index=0;menu.first=0;}
    else if((unsigned)menu.index>=menu.count) {
        menu.index=(int16_t)(menu.count-1);
        if(menu.first>(unsigned)menu.index)menu.first=(uint16_t)menu.index;
    }
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
    /* The landscape flag is a plain variable so SWD or the settings page can
     * flip it; the panel scan mode is applied here, once. */
    {
        static uint8_t watched;
        if(nes_screen_landscape!=watched){
            watched=nes_screen_landscape;
            NesPort_SetLandscape(watched);
            if(app_state==APP_MENU)NesMenu_Draw(&menu);
            else if(app_state==APP_SETTINGS){
                NesSettings_Draw(menu.audio_ok);
                NesSettings_Audio((uint8_t)NesAudio_GetOutput(),menu.audio_ok,0);
            }
            else if(app_state==APP_SEARCH)NesSearch_Draw(&search);
        }
    }
    pad_stable=pad_poll(now);
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
    /* Shield face buttons: A/B direct, E is Select, KEY is Start, C/D fire
     * at roughly 6 Hz so the turbo buttons stay usable on rapid-fire games. */
    if(SHIELD&PAD_A)pad|=1;
    if(SHIELD&PAD_B)pad|=2;
    if(SHIELD&PAD_E)pad|=4;
    if(SHIELD&PAD_F)pad|=8;
    if((SHIELD&PAD_C)&&((now/80u)&1u))pad|=1;
    if((SHIELD&PAD_D)&&((now/80u)&1u))pad|=2;
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
void NesPort_InvalidateDisplay(void)
{
    memset(displayed_valid,0,sizeof(displayed_valid));
}

/* Every eight NES pixels span exactly fifteen columns of the 480px LCD.
 * The first seven colors each occupy two columns and the eighth occupies one. */
static void submit_changed_span(unsigned line,unsigned first,unsigned end,
                                const uint8_t *pixels,const uint16_t *palette)
{
    static uint16_t row[480];
    unsigned group,src,out=0,x,y;
    unsigned y0=line*450/240,y1=(line+1)*450/240;
    for(group=first;group<end;group++) {
        src=group*8;
        for(x=0;x<7;x++) {
            uint16_t color=palette[pixels[src+x]&63];
            row[out++]=color;
            row[out++]=color;
        }
        row[out++]=palette[pixels[src+7]&63];
    }
    lcd_open_window((uint16_t)(first*15),(uint16_t)(112+y0),(uint16_t)out,(uint16_t)(y1-y0));
    for(y=y0;y<y1;y++)
        for(x=0;x<out;x++)LCD_WRITE_DATA(row[x]);
    lcd_frame_pixels+=out*(y1-y0);
}

void NesPort_Line(int line,const uint8_t *pixels,const uint16_t *palette)
{
    uint32_t started=DWT->CYCCNT;
    uint8_t *previous=displayed_pixels[line];
    unsigned x,first=0,end=32;
    if(line==0) {
        lcd_frame_pixels=0;
        lcd_frame_cycles=0;
    }
    if(line==0 && nes_capture_request) {
        nes_capture_request=0;
        capturing=(uint8_t)(MapperNo!=5&&Nes_CaptureRangeAvailable(NES_CAPTURE_ADDR,NES_CAPTURE_BYTES));
        if(!capturing)++nes_capture_rejected;
    }
    if(capturing) {
        volatile uint16_t *dest=(volatile uint16_t*)NES_CAPTURE_ADDR+line*256;
        for(x=0;x<256;x++)dest[x]=palette[pixels[x]&63];
        if(line==239){capturing=0;++nes_capture_ready;}
    }
    if(memcmp(displayed_palette,palette,sizeof(displayed_palette))!=0) {
        memcpy(displayed_palette,palette,sizeof(displayed_palette));
        NesPort_InvalidateDisplay();
    }
    if(displayed_valid[line]) {
        while(first<end && !memcmp(previous+first*8,pixels+first*8,8))++first;
        while(end>first && !memcmp(previous+(end-1)*8,pixels+(end-1)*8,8))--end;
    }
    if(first<end) {
        submit_changed_span((unsigned)line,first,end,pixels,palette);
        memcpy(previous+first*8,pixels+first*8,(end-first)*8);
        displayed_valid[line]=1;
    }
    lcd_frame_cycles+=DWT->CYCCNT-started;
    if(line==239) {
        nes_lcd_pixels=lcd_frame_pixels;
        nes_lcd_pixels_total+=lcd_frame_pixels;
        if(lcd_frame_pixels)++nes_lcd_updates_total;
        nes_lcd_us=lcd_frame_cycles/(HAL_RCC_GetHCLKFreq()/1000000u);
    }
}

static void game_chrome(void)
{
    NesPort_InvalidateDisplay();
    text(16,16,"NES FIRE EMULATOR");
    if(strlen(running_title)>28)PixelFont_Text(16,58,running_title,WHITE,BLACK,1);
    else text(16,54,running_title);
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

static void return_to_library(void)
{
    rpg_direction=0;
    if(loaded||app_state==APP_SETTINGS)NesAudio_Mute(1);
    loaded=0;
    capturing=0;nes_capture_request=0;
    NesLibrary_EnterMenu();
    app_state=APP_MENU;
    sw_hold_active=0;
    menu_axis_armed=0;menu_page_armed=0;menu_center_seen=0;menu_page_seen=0;menu_armed=0;key1_pending=0;
    cover_pending=0;load_error[0]='\0';notice[0]='\0';
    draw_library();
}

static void save_and_exit(void)
{
    if(NesLibrary_SavePending()) {
        uint32_t started;
        int result;
        NesAudio_Mute(1);
        lcd_fill_color(16,732,448,36,BLACK);
        text(16,734,"SAVING...");
        started=HAL_GetTick();
        result=NesLibrary_Save();
        nes_save_ms=HAL_GetTick()-started;
        if(result) {
            app_state=APP_SAVE_ERROR;
            save_error_armed=0;
            NesMenu_SaveError(NesLibrary_Error());
            return;
        }
        return_to_library();
        show_notice("SAVE OK");
    } else return_to_library();
}

static void restart_frame_clock(void)
{
    logic_frames=draw_frames=0;
    nes_draw_frame_us=nes_skip_frame_us=0;
    mean_draw_us=mean_skip_us=undrawn_remaining=faster_samples=0;
    nes_effective_render_divisor=NesPort_RenderDivisor(nes_render_divisor,0,0);
    next_frame=DWT->CYCCNT;
    stats_due=HAL_GetTick()+1000;
}

static void record_frame_time(int drew,uint32_t frame_us)
{
    uint32_t *mean=drew?&mean_draw_us:&mean_skip_us;
    /* Smooth scene-to-scene variation. Measure skipped frames independently,
     * since their CPU/PPU work still consumes part of every interval. */
    *mean=*mean?(*mean*3u+frame_us+2u)/4u:frame_us;
    if(drew) {
        unsigned need=NesPort_RenderDivisor(nes_render_divisor,mean_draw_us,mean_skip_us);
        nes_draw_frame_us=frame_us;
        if(need>=nes_effective_render_divisor || ++faster_samples>=3) {
            nes_effective_render_divisor=need;
            faster_samples=0;
        }
        undrawn_remaining=nes_effective_render_divisor-1;
    } else {
        nes_skip_frame_us=frame_us;
        --undrawn_remaining;
    }
}

static void save_error_poll(void)
{
    int retry=KEY2_PRESSED||SW_PRESSED||(nes_test_pad&1);
    int resume=KEY1_PRESSED||(nes_test_pad&2);
    if(!retry&&!resume){save_error_armed=1;return;}
    if(!save_error_armed)return;
    save_error_armed=0;
    if(retry){save_and_exit();return;}
    lcd_fill_color(0,0,480,800,BLACK);
    game_chrome();
    sw_hold_active=0;
    restart_frame_clock();
    app_state=APP_GAME;
    NesAudio_Mute(0);
}

static void start_selected(void)
{
    const NesRomImage *game;
    const uint8_t *data;
    char file[NES_IMPORT_PATH_MAX+1];
    uint32_t started,bytes;
    int result;
    if(menu.count==0) return;
    game=NesLibrary_Game((unsigned)menu.index);
    if(!game){menu_status("ENTRY UNAVAILABLE");return;}
    data=game->data;bytes=game->size;
    snprintf(file,sizeof(file),"%s",game->file);
    snprintf(running_title,sizeof(running_title),"%.56s",game->label);
    load_error[0]='\0';
    lcd_fill_color(0,0,480,800,BLACK);
    text(16,380,"LOADING ...");
    started=HAL_GetTick();
    result=NesLibrary_Load((unsigned)menu.index);
    /* A reset below $8000 does not establish that this is a bootable FDS
     * snapshot. The experimental snapshot loader has no disk drive; keep
     * malformed cartridges out of that path until a real FDS image is loaded. */
    if(nes_fds_snapshot_test_only && result==5)
        result=Nes_LoadFds(data,bytes,nes_fds_bios,nes_fds_bios_size);
    printf("NES load=%d file=%s bytes=%lu mapper=%d\r\n",result,file,
        (unsigned long)bytes,MapperNo);
    if(result) {
        nes_load_ms=HAL_GetTick()-started;
        if(result==10) snprintf(load_error,sizeof(load_error),"%s",NesLibrary_Error());
        else if(result==5) snprintf(load_error,sizeof(load_error),"BOOT ERROR - NEED .FDS");
        else if(result==7) snprintf(load_error,sizeof(load_error),"FDS VALID - DRIVE NOT READY");
        else if(result==8) snprintf(load_error,sizeof(load_error),"INVALID FDS DISK IMAGE");
        else if(result==9) snprintf(load_error,sizeof(load_error),"BAD FDS BIOS - NEED DISKSYS.ROM");
        else snprintf(load_error,sizeof(load_error),"ROM REJECTED rc=%d - SEE UART",result);
        NesLibrary_EnterMenu();
        draw_library();
        menu_status(load_error);
        return;
    }
    if(NesLibrary_RecordPlayed((unsigned)menu.index)<0)
        printf("NES library: recent history write failed\r\n");
    nes_load_ms=HAL_GetTick()-started;
    NesAudio_Mute(0);
    loaded=1;app_state=APP_GAME;
    rpg_direction=0;
    game_chrome();
    restart_frame_clock();
}

static void menu_redraw_selection(void)
{
    uint32_t started=DWT->CYCCNT;
    NesMenu_DrawRows(&menu);
    menu_info(0);
    cover_pending=1;cover_due=HAL_GetTick();
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

static void draw_library_options(void)
{
    int favorite=menu.count&&NesLibrary_IsFavorite((unsigned)menu.index);
    NesMenu_LibraryOptions(library_cursor,NesLibrary_Filter()+1u,favorite,menu.count!=0);
}

static void open_library_options(void)
{
    library_cursor=(uint8_t)(NesLibrary_Filter()+1u);
    library_axis_armed=0;library_centered=0;library_key_armed=0;
    sw_hold_active=0;cover_pending=0;
    app_state=APP_LIBRARY;
    draw_library_options();
}

static void library_check_poll(uint32_t now)
{
    unsigned pending;
    int back=KEY1_PRESSED||(nes_test_pad&2);
    if(!back)library_key_armed=1;
    else if(library_key_armed) {
        (void)NesLibrary_SetFilter(NES_LIBRARY_FILTER_ALL);
        update_menu_count(0);
        return_to_library();
        show_notice("HEADER CHECK CANCELED");
        return;
    }
    NesLibrary_AdvanceFilter();
    pending=NesLibrary_FilterPending();
    if(!pending) {
        update_menu_count(0);
        return_to_library();
        if(NesLibrary_SearchFailed())show_notice("SOME ROM HEADERS COULD NOT BE READ");
        return;
    }
    if((int32_t)(now-library_progress_due)>=0) {
        char progress[29];
        snprintf(progress,sizeof(progress),"%u/%u CHECKED",library_check_total-pending,library_check_total);
        lcd_fill_color(16,418,448,22,BLACK);
        text(16,418,progress);
        library_progress_due=now+150;
    }
}

static void library_options_poll(uint32_t now)
{
    const JoystickState *j=Joystick_Get();
    int dir=0,centered=0;
    int back=KEY1_PRESSED||(nes_test_pad&2);
    int select=KEY2_PRESSED||SW_PRESSED||(nes_test_pad&1);
    if(j->healthy&&j->calibrated) {
        dir=j->y>0.65f?1:(j->y< -0.65f?-1:0);
        centered=j->y<0.25f&&j->y> -0.25f;
    }
    if(nes_test_pad&0x30){dir=(nes_test_pad&0x10)?-1:1;centered=0;}
    if(centered) {
        if(!library_centered){library_centered=1;library_center_due=now+60;}
        if((int32_t)(now-library_center_due)>=0)library_axis_armed=1;
    } else library_centered=0;
    if(dir&&library_axis_armed) {
        library_axis_armed=0;
        library_cursor=(uint8_t)((library_cursor+NES_LIBRARY_OPTIONS+dir)%NES_LIBRARY_OPTIONS);
        draw_library_options();
    }
    if(!select&&!back){library_key_armed=1;return;}
    if(!library_key_armed)return;
    library_key_armed=0;
    if(!back&&library_cursor==0){open_search();return;}
    if(back){return_to_library();return;}
    if(library_cursor==NES_LIBRARY_OPTIONS-1) {
        int result=menu.count?NesLibrary_ToggleFavorite((unsigned)menu.index):-1;
        update_menu_count(1);
        return_to_library();
        show_notice(result==1?"ADDED TO FAVORITES":result==0?"REMOVED FROM FAVORITES":
                    result==-2?"FAVORITES LIST FULL":menu.count?"FAVORITE WRITE FAILED - CHECK SD":"NO GAME SELECTED");
        return;
    }
    NesLibrary_ClearView();
    (void)NesLibrary_SetFilter(library_cursor-1u);
    library_check_total=NesLibrary_FilterPending();
    if(library_check_total) {
        lcd_fill_color(0,0,480,800,BLACK);
        text(16,380,"CHECKING ROM HEADERS...");
        text(16,458,"KEY1 CANCEL");
        library_progress_due=now;
        app_state=APP_LIBRARY_CHECK;
        return;
    }
    update_menu_count(0);
    return_to_library();
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
        if(search_key_armed){search_key_armed=0;return_to_library();return;}
    } else search_key_armed=1;
    if(KEY2_PRESSED||SW_PRESSED||(nes_test_pad&1)) {
        if(search_ok_armed) {
            search_ok_armed=0;
            if(NesSearch_Select(&search)==1) {
                unsigned n;
                uint32_t started=HAL_GetTick();
                n=NesLibrary_Search(search.query);
                nes_search_ms=HAL_GetTick()-started;
                update_menu_count(0);
                return_to_library();
                if(n){char msg[24];snprintf(msg,sizeof(msg),"%u MATCHES",n);show_notice(msg);}
                else if(NesLibrary_SearchFailed())show_notice("SD CATALOG READ ERROR");
                else if(search.query[0])show_notice("NO MATCH - VIEW RESTORED");
                else show_notice("SEARCH CLEARED");
            }
        }
    } else search_ok_armed=1;
}
static void menu_poll(uint32_t now)
{
    const JoystickState *j=Joystick_Get();
    int dir=0,page=0,cy=0,cx=0;
    /* The cover is read from the card only after the stick has settled. */
    if(cover_pending&&(int32_t)(now-cover_due)>=0){cover_pending=0;NesMenu_DrawCover(&menu);menu_info(1);}
    {
        /* Capacitive key flips the panel between portrait and landscape. */
        const TouchpadState *cap=Touchpad_Get();
        if(cap->ready&&cap->pressed){
            if(cap_search_armed){cap_search_armed=0;nes_screen_landscape=nes_screen_landscape?0:1;return;}
        } else cap_search_armed=1;
    }
    {
        /* Select steps down the list without using the stick. */
        static uint8_t select_last;
        uint8_t sel=(SHIELD&PAD_E)?1u:0u;
        if(sel&&!select_last&&NesMenu_Move(&menu,1)){load_error[0]='\0';menu_redraw_selection();}
        select_last=sel;
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
    if(dir && (menu_axis_armed||(int32_t)(now-menu_repeat_due)>=0)) {
        menu_axis_armed=0;
        menu_repeat_due=now+90;
        if(NesMenu_Move(&menu,dir)){load_error[0]='\0';menu_redraw_selection();}
    }
    if(page && menu_page_armed) {
        menu_page_armed=0;
        if(NesMenu_Page(&menu,page,5)){load_error[0]='\0';menu_redraw_selection();}
    }
    if(KEY1_PRESSED||KEY2_PRESSED||SW_PRESSED||SHIELD||(nes_test_pad&3)) {
        int k1=KEY1_PRESSED||(nes_test_pad&2);
        int k2=KEY2_PRESSED;
        int ok=(SHIELD&PAD_A)||(SHIELD&PAD_F)||SW_PRESSED||((nes_test_pad&1)&&!k1&&!k2);
        if(k1) {
            /* Tap KEY1 for Settings; holding it still opens the library actions. */
            if(!key1_pending){key1_pending=1;key1_down=now;}
            else if((uint32_t)(now-key1_down)>=1000){
                key1_pending=0;menu_armed=0;open_library_options();return;
            }
        } else if(k2) {
            /* KEY2 is the library shortcut. */
            if(menu_armed){menu_armed=0;open_library_options();return;}
        } else if(menu_armed) {
            menu_armed=0;
            if(ok){start_selected();return;}
            if(SHIELD&PAD_B)return;          /* B is back; nothing to leave here */
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
    else if(notice[0]&&(int32_t)(now-notice_until)<0)menu_status(notice);
    else if(!strncmp(NesLibrary_Status(),"SD SAVE",7))menu_status(NesLibrary_Status());
    else if(NesLibrary_OverflowCount()) {
        char limit[40];
        snprintf(limit,sizeof(limit),"LIBRARY FULL - %u FILES OUTSIDE LIMIT",NesLibrary_OverflowCount());
        menu_status(limit);
    }
    else if(NesLibrary_ViewActive())menu_status(view_hints[NesLibrary_Filter()]);
    else if(!j->healthy||!j->calibrated) menu_status("CENTER STICK TO CALIBRATE");
    else if(j->errors) menu_status("STICK ERROR - CHECK WIRING");
    else menu_status(load_error[0]?load_error:NesLibrary_Status());
}

void NesApp_Init(uint8_t touch_ok)
{
    int result,library_result;
    uint32_t started;
    touch_available=touch_ok;
    Touchpad_Init();
    __HAL_RCC_CCMDATARAMEN_CLK_ENABLE();
    lcd_fill_color(0,0,480,800,BLACK);
    text(16,16,"NES FIRE EMULATOR");
    text(16,54,"AUDIO: INITIALIZING");
    result=NesAudio_Init();
    printf("Audio init=%d (WM8978 selectable output, 11025Hz)\r\n",result);
    NesAudio_Mute(1);
    text(16,94,"SD: LOADING LIBRARY");
    started=HAL_GetTick();
    library_result=NesLibrary_Boot();
    nes_library_boot_ms=HAL_GetTick()-started;
    printf("SD library=%d\r\n",library_result);
    NesMenu_Init(&menu,(uint16_t)NesLibrary_Count(),result==0,touch_ok);
    printf("Games=%u\r\n",NesLibrary_Count());
    app_state=APP_MENU;
    loaded=0;
    menu_axis_armed=0;menu_page_armed=0;menu_center_seen=0;menu_page_seen=0;menu_armed=0;key1_pending=0;
    draw_library();
    if(result) menu_status("AUDIO OFF - CHECK CODEC");
    else menu_status(NesLibrary_Status());
}
void NesApp_Poll(void)
{
    uint32_t now=HAL_GetTick(),cycles=DWT->CYCCNT,period=HAL_RCC_GetHCLKFreq()/60;
    const TouchpadState *cap=Touchpad_Get();
    NesPort_Input();
    if(app_state==APP_MENU) {menu_poll(now);return;}
    if(app_state==APP_SEARCH) {search_poll(now);return;}
    if(app_state==APP_LIBRARY) {library_options_poll(now);return;}
    if(app_state==APP_LIBRARY_CHECK) {library_check_poll(now);return;}
    if(app_state==APP_SAVE_ERROR) {save_error_poll();return;}
    /* Long press of SW leaves the game and returns to the menu. */
    if(SW_PRESSED) {
        if(!sw_hold_active) {sw_hold_active=1;sw_hold_start=now;}
        else if((uint32_t)(now-sw_hold_start)>=1500) {
            if(app_state==APP_GAME)save_and_exit();
            else return_to_library();
            return;
        }
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
        /* Up/down flips the panel between portrait and the 800x480 layout. */
        {
            int vdir=0,vcentered=0;
            if(j->healthy&&j->calibrated) {
                vdir=j->y>0.65f?1:j->y< -0.65f?-1:0;
                vcentered=j->y<0.25f && j->y> -0.25f;
            }
            if(vcentered) {
                if(!settings_y_seen){settings_y_seen=1;settings_y_due=now+60;}
                if((int32_t)(now-settings_y_due)>=0)settings_y_armed=1;
            } else {
                settings_y_seen=0;
                if(vdir&&settings_y_armed) {
                    settings_y_armed=0;
                    nes_screen_landscape=nes_screen_landscape?0:1;
                }
            }
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
        uint32_t start_cycles=DWT->CYCCNT,frame_us;
        int draw=undrawn_remaining==0;
        Nes_Frame(draw);frame_us=(DWT->CYCCNT-start_cycles)/(HAL_RCC_GetHCLKFreq()/1000000u);
        record_frame_time(draw,frame_us);
        logic_frames++;nes_logic_total++;if(draw){draw_frames++;nes_draw_total++;}
        next_frame+=period;
        /* A costly draw can legitimately borrow its own display interval.
         * Cap longer stalls so resuming after a pause cannot trigger a burst. */
        uint32_t recovery=nes_effective_render_divisor;
        if(recovery<4)recovery=4;
        if((int32_t)(DWT->CYCCNT-next_frame)>(int32_t)(period*recovery)) {
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
