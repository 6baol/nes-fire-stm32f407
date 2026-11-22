#include "renderer.h"
#include "lcd_draw.h"
#include "bsp_lcd_display.h"
#include <stdio.h>
#include <string.h>

#define T GAME_TILE_SIZE
#define COLS (GAME_WIDTH/T)
#define ROWS (GAME_HEIGHT/T)
#define TILE_COUNT (COLS*ROWS)
#define BG 0x0843
#define ACCENT 0x4EFF

typedef struct { int x,y; uint16_t color; uint8_t scale; char value[62]; } Label;
static Game snapshot;
static JoystickState joy_snapshot;
static GameMetrics metric_snapshot;
static Label labels[18];
static Label header_cache[2];
static unsigned label_count;
static uint8_t dirty[TILE_COUNT], valid;
static uint16_t pixels[T*T];
static unsigned cursor;
static int tile_x, tile_y;
static uint8_t world_clip;
/* Per-row object lists: a tile examines only objects that can intersect its row. */
static uint16_t bullet_rows[ROWS][GAME_ENEMY_BULLETS];
static uint8_t shot_rows[ROWS][GAME_PLAYER_BULLETS];
static uint16_t bullet_count[ROWS];
static uint8_t shot_count[ROWS];

static void build_rows(void)
{
    unsigned i;int first,last,row;
    memset(bullet_count,0,sizeof(bullet_count));
    memset(shot_count,0,sizeof(shot_count));
    for(i=0;i<GAME_ENEMY_BULLETS;++i) {
        const GameBullet *b=&snapshot.bullets[i];
        if(!b->active) continue;
        first=((int)b->y-b->radius)/T;last=((int)b->y+b->radius)/T;
        if(first<0) first=0;
        if(last>=ROWS) last=ROWS-1;
        for(row=first;row<=last;++row) bullet_rows[row][bullet_count[row]++]=(uint16_t)i;
    }
    for(i=0;i<GAME_PLAYER_BULLETS;++i) {
        const GameBullet *b=&snapshot.shots[i];
        if(!b->active) continue;
        first=((int)b->y-7)/T;last=((int)b->y+7)/T;
        if(first<0) first=0;
        if(last>=ROWS) last=ROWS-1;
        for(row=first;row<=last;++row) shot_rows[row][shot_count[row]++]=(uint8_t)i;
    }
}

static void mark(int x,int y,int w,int h)
{
    int x0,y0,x1,y1,i,j;
    if (x >= GAME_WIDTH || y >= GAME_HEIGHT || x+w <= 0 || y+h <= 0) return;
    x0 = x < 0 ? 0 : x/T; y0 = y < 0 ? 0 : y/T;
    x1 = (x+w-1)/T; y1 = (y+h-1)/T;
    if (x1 >= COLS) x1=COLS-1;
    if (y1 >= ROWS) y1=ROWS-1;
    for (j=y0;j<=y1;++j) for(i=x0;i<=x1;++i) dirty[j*COLS+i]=1;
}

static void mark_objects(const Game *g)
{
    unsigned i;
    mark((int)g->player_x-16,(int)g->player_y-18,33,37);
    if (g->boss_active) mark((int)g->boss_x-34,112,69,66);
    for(i=0;i<GAME_ENEMIES;++i)
        if(g->enemies[i].active) mark((int)g->enemies[i].x-17,(int)g->enemies[i].y-17,35,35);
    for(i=0;i<GAME_ENEMY_BULLETS;++i) {
        const GameBullet *b=&g->bullets[i]; int r=b->radius;
        if(b->active) mark((int)b->x-r,(int)b->y-r,2*r+1,2*r+1);
    }
    for(i=0;i<GAME_PLAYER_BULLETS;++i) {
        const GameBullet *b=&g->shots[i];
        if(b->active) mark((int)b->x-2,(int)b->y-7,5,15);
    }
}

static Label *label(int x,int y,uint16_t color,unsigned scale,const char *value)
{
    Label *l=&labels[label_count++];
    l->x=x; l->y=y; l->color=color; l->scale=(uint8_t)scale;
    strncpy(l->value,value,sizeof(l->value)-1);
    l->value[sizeof(l->value)-1]=0;
    return l;
}

static void prepare_labels(void)
{
    Label *l;
    label_count=0;
    l=label(12,6,WHITE,1,"");
    snprintf(l->value,sizeof(l->value),"SCORE %06lu   LIFE %u   BOMB %u",
             (unsigned long)snapshot.score,snapshot.lives,snapshot.bombs);
    l=label(12,27,ACCENT,1,"");
    snprintf(l->value,sizeof(l->value),"FPS %lu  DRAW %luus  BULLET %u",
             (unsigned long)metric_snapshot.fps,(unsigned long)metric_snapshot.render_us,
             GameCore_BulletCount(&snapshot));
    if(snapshot.mode==GAME_TITLE) {
        label(136,210,ACCENT,2,"BULLET GARDEN");
        label(92,262,WHITE,1,"STM32F407 / HW-504 / V0.4");
        label(76,320,joy_snapshot.calibrated?GREEN:YELLOW,1,
              joy_snapshot.calibrated?"STICK READY - PRESS SW TO START":"RELEASE STICK - CALIBRATING...");
        label(92,362,WHITE,1,"KEY1: INPUT DIAGNOSTICS");
        label(92,398,WHITE,1,"KEY2: START / PAUSE / RESUME");
        label(92,434,WHITE,1,"IN GAME: HOLD KEY1 TO FOCUS");
        label(92,470,WHITE,1,"PRESS SW TO USE A BOMB");
        label(92,506,WHITE,1,"TAP SCREEN TO PAUSE / RESUME");
        l=label(76,590,GRAY,1,"");
        snprintf(l->value,sizeof(l->value),"SRAM %s  TOUCH %s  FILL %luus",
                 metric_snapshot.sram_ok?"OK":"FAIL",metric_snapshot.touch_ok?"OK":"OFF",
                 (unsigned long)metric_snapshot.fill_us);
        label(92,626,YELLOW,1,"PA4 / PA6 / PB7 - POWER 3V3");
    } else if(snapshot.mode==GAME_DIAGNOSTIC) {
        label(136,124,ACCENT,2,"INPUT MONITOR");
        l=label(64,190,WHITE,1,"");
        snprintf(l->value,sizeof(l->value),"RAW X %4u   Y %4u",joy_snapshot.raw_x,joy_snapshot.raw_y);
        l=label(64,220,WHITE,1,"");
        snprintf(l->value,sizeof(l->value),"CENTER X %4u   Y %4u",joy_snapshot.center_x,joy_snapshot.center_y);
        l=label(64,250,WHITE,1,"");
        snprintf(l->value,sizeof(l->value),"VECTOR X %+4d   Y %+4d / 1000",
                 (int)(joy_snapshot.x*1000),(int)(joy_snapshot.y*1000));
        l=label(64,280,joy_snapshot.calibrated?GREEN:YELLOW,1,"");
        snprintf(l->value,sizeof(l->value),"%s   ADC ERR %lu",joy_snapshot.calibrated?"READY":"RELEASE STICK",
                 (unsigned long)joy_snapshot.errors);
        label(64,600,WHITE,1,"KEY1: RECALIBRATE (RELEASE STICK)");
        label(64,636,WHITE,1,"SW / KEY2: RETURN TO TITLE");
        label(64,680,GRAY,1,"MOVE STICK TO CHECK BOTH AXES");
    } else if(snapshot.mode==GAME_PAUSED) {
        label(192,340,YELLOW,2,"PAUSED");
        label(68,400,WHITE,1,"KEY2 OR TAP SCREEN TO RESUME");
        if(!joy_snapshot.calibrated) label(68,436,RED,1,"RELEASE STICK / CHECK ADC WIRING");
    } else if(snapshot.mode==GAME_WON || snapshot.mode==GAME_LOST) {
        label(snapshot.mode==GAME_WON?152:168,330,snapshot.mode==GAME_WON?GREEN:RED,2,
              snapshot.mode==GAME_WON?"STAGE CLEAR":"GAME OVER");
        label(92,404,WHITE,1,"SW / KEY2: RETURN TO TITLE");
    }
}

void Renderer_Init(void) { valid=0;cursor=TILE_COUNT; }
uint8_t Renderer_Busy(void) { return cursor<TILE_COUNT; }

void Renderer_Begin(const Game *g,const JoystickState *joy,const GameMetrics *metrics)
{
    uint8_t header_due;
    if(Renderer_Busy()) return;
    header_due=!valid || snapshot.mode!=g->mode || g->mode!=GAME_PLAYING ||
               snapshot.tick/12!=g->tick/12;
    memset(dirty,0,sizeof(dirty));
    if(!valid || snapshot.mode!=g->mode || g->mode==GAME_DIAGNOSTIC ||
       ((snapshot.bomb_flash!=0)!=(g->bomb_flash!=0))) memset(dirty,1,sizeof(dirty));
    else if(g->mode==GAME_PLAYING || g->mode==GAME_PAUSED) {
        mark_objects(&snapshot); mark_objects(g);
        if(header_due) mark(0,0,GAME_WIDTH,48);
        if(snapshot.boss_hp!=g->boss_hp || snapshot.boss_active!=g->boss_active)
            mark(0,48,GAME_WIDTH,16);
        if(g->mode==GAME_PAUSED) mark(48,320,400,150);
    } else if(g->mode==GAME_TITLE &&
              (snapshot.mode!=g->mode || joy_snapshot.calibrated!=joy->calibrated))
        mark(48,310,400,40);
    else mark(0,0,GAME_WIDTH,GAME_TOP);
    snapshot=*g; joy_snapshot=*joy; metric_snapshot=*metrics;
    build_rows();prepare_labels();
    if(header_due) { header_cache[0]=labels[0];header_cache[1]=labels[1]; }
    else { labels[0]=header_cache[0];labels[1]=header_cache[1]; }
    valid=1;cursor=0;
}

static void rect(int x,int y,int w,int h,uint16_t color)
{
    int x0=x>tile_x?x:tile_x, y0=y>tile_y?y:tile_y;
    int x1=x+w<tile_x+T?x+w:tile_x+T, y1=y+h<tile_y+T?y+h:tile_y+T;
    int i,j;
    if(world_clip) {
        if(y0<GAME_TOP) y0=GAME_TOP;
        if(y1>GAME_BOTTOM) y1=GAME_BOTTOM;
    }
    for(j=y0;j<y1;++j) for(i=x0;i<x1;++i) pixels[(j-tile_y)*T+i-tile_x]=color;
}

static void circle(int x,int y,int r,uint16_t color)
{
    int dx,dy,px,py,x0,x1,y0,y1;
    if(x+r<tile_x || x-r>=tile_x+T || y+r<tile_y || y-r>=tile_y+T) return;
    x0=x-r>tile_x?x-r:tile_x;x1=x+r<tile_x+T-1?x+r:tile_x+T-1;
    y0=y-r>tile_y?y-r:tile_y;y1=y+r<tile_y+T-1?y+r:tile_y+T-1;
    if(world_clip) {
        if(y0<GAME_TOP) y0=GAME_TOP;
        if(y1>=GAME_BOTTOM) y1=GAME_BOTTOM-1;
    }
    /* Clip before rasterization; never rasterize the entire Boss for each tile. */
    for(py=y0;py<=y1;++py) {
        dy=py-y;
        for(px=x0;px<=x1;++px) {
            dx=px-x;
            if(dx*dx+dy*dy<=r*r) pixels[(py-tile_y)*T+px-tile_x]=color;
        }
    }
}

static void text(const Label *l)
{
    unsigned n,row,col; int x,y; uint8_t bits;
    if(l->y+16*l->scale<=tile_y || l->y>=tile_y+T) return;
    for(n=0;l->value[n];++n) {
        unsigned c=(unsigned char)l->value[n];
        x=l->x+(int)n*8*l->scale;
        if(x+8*l->scale<=tile_x || x>=tile_x+T || c<32 || c>126) continue;
        for(row=0;row<16;++row) {
            bits=Font8x16.table[(c-32)*16+row]; y=l->y+(int)row*l->scale;
            for(col=0;col<8;++col) if(bits&(0x80u>>col))
                rect(x+(int)col*l->scale,y,l->scale,l->scale,l->color);
        }
    }
}

static void compose(void)
{
    unsigned i,row=(unsigned)tile_y/T; int x,y,dx;
    world_clip=0;
    for(i=0;i<T*T;++i) pixels[i]=BG;
    /* The background is deterministic, so erased areas reconstruct exactly. */
    if(tile_y>=GAME_TOP && tile_y<GAME_BOTTOM) {
        unsigned hash=(unsigned)(tile_x*31+tile_y*17);
        if(hash%7==0) rect(tile_x+(int)(hash%13),tile_y+(int)((hash/7)%13),1,2,0x528C);
    }
    rect(0,0,GAME_WIDTH,GAME_TOP,0x1086);
    rect(0,GAME_TOP-2,GAME_WIDTH,2,ACCENT);
    rect(0,GAME_BOTTOM,GAME_WIDTH,16,0x1086);
    if(snapshot.mode>=GAME_PLAYING) {
        uint16_t colors[3]={0xFC9F,0xFFE0,0x6FFF};
        if(snapshot.boss_active)
            rect(12,49,(GAME_WIDTH-24)*snapshot.boss_hp/900,7,0xFACA);
        world_clip=1;
        if(snapshot.bomb_flash) rect(0,GAME_TOP,GAME_WIDTH,GAME_BOTTOM-GAME_TOP,0x2108);
        for(i=0;i<shot_count[row];++i) {
            const GameBullet *b=&snapshot.shots[shot_rows[row][i]];
            rect((int)b->x-2,(int)b->y-7,5,15,GREEN);
        }
        for(i=0;i<GAME_ENEMIES;++i) if(snapshot.enemies[i].active) {
            x=(int)snapshot.enemies[i].x;y=(int)snapshot.enemies[i].y;
            circle(x,y,15,0xBA1F);rect(x-5,y-5,11,11,WHITE);
        }
        if(snapshot.boss_active) {
            x=(int)snapshot.boss_x;
            circle(x,145,28,0xB99F);circle(x,145,15,WHITE);
        }
        for(i=0;i<bullet_count[row];++i) {
            const GameBullet *b=&snapshot.bullets[bullet_rows[row][i]];
            circle((int)b->x,(int)b->y,b->radius,colors[b->kind%3]);
            circle((int)b->x,(int)b->y,1,WHITE);
        }
        if((!snapshot.invincible || (snapshot.tick/5)%2==0) &&
           snapshot.player_x+16>=tile_x && snapshot.player_x-16<tile_x+T &&
           snapshot.player_y+18>=tile_y && snapshot.player_y-18<tile_y+T) {
            x=(int)snapshot.player_x;y=(int)snapshot.player_y;
            for(dx=0;dx<16;++dx) rect(x-dx,y-16+dx*2,dx*2+1,2,ACCENT);
            rect(x-3,y-9,7,22,WHITE);
        }
        if(snapshot.slow) { circle((int)snapshot.player_x,(int)snapshot.player_y,5,RED);
                           circle((int)snapshot.player_x,(int)snapshot.player_y,2,WHITE); }
        world_clip=0;
        if(snapshot.mode!=GAME_PLAYING) rect(48,320,384,150,0x1086);
    }
    if(snapshot.mode==GAME_DIAGNOSTIC) {
        rect(120,340,240,240,0x1086);
        rect(120,459,240,1,GRAY);rect(239,340,1,240,GRAY);
        circle(240+(int)(joy_snapshot.x*112),460+(int)(joy_snapshot.y*112),6,ACCENT);
    }
    for(i=0;i<label_count;++i) text(&labels[i]);
}

void Renderer_Poll(void)
{
    unsigned done=0,i;
    while(cursor<TILE_COUNT && done<GAME_RENDER_BATCH) {
        unsigned index=cursor++;
        if(!dirty[index]) continue;
        tile_x=(int)(index%COLS)*T;tile_y=(int)(index/COLS)*T;
        compose();
        lcd_open_window((uint16_t)tile_x,(uint16_t)tile_y,T,T);
        for(i=0;i<T*T;++i) LCD_WRITE_DATA(pixels[i]);
        ++done;
    }
}
