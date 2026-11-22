#include "game_core.h"
#include "renderer.h"
#include <assert.h>
#include <math.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static Game g;
static GameInput in;
static uint16_t screen[GAME_HEIGHT][GAME_WIDTH];
static unsigned wx,wy,ww,wh,pixel_index;
static void window(uint16_t x,uint16_t y,uint16_t w,uint16_t h)
{
    assert(x+w<=GAME_WIDTH && y+h<=GAME_HEIGHT && w && h);
    wx=x;wy=y;ww=w;wh=h;pixel_index=0;
}
void (*lcd_open_window)(uint16_t,uint16_t,uint16_t,uint16_t)=window;
void MockLCD_Write(uint16_t pixel)
{
    assert(pixel_index<ww*wh);
    screen[wy+pixel_index/ww][wx+pixel_index%ww]=pixel;
    ++pixel_index;
}

static void reset(void)
{
    memset(&in,0,sizeof(in));in.ready=1;GameCore_Start(&g);
}
static void render(void)
{
    JoystickState joy={0};GameMetrics metrics={0};unsigned batches=0;
    joy.calibrated=joy.healthy=1;metrics.sram_ok=metrics.touch_ok=1;
    Renderer_Begin(&g,&joy,&metrics);
    while(Renderer_Busy()) { Renderer_Poll();assert(++batches<=1500); }
}
static void save_ppm(const char *path)
{
    FILE *f=fopen(path,"wb");unsigned x,y;
    assert(f);fprintf(f,"P6\n%d %d\n255\n",GAME_WIDTH,GAME_HEIGHT);
    for(y=0;y<GAME_HEIGHT;++y) for(x=0;x<GAME_WIDTH;++x) {
        uint16_t p=screen[y][x];
        unsigned char rgb[3]={(unsigned char)(((p>>11)&31)*255/31),
            (unsigned char)(((p>>5)&63)*255/63),(unsigned char)((p&31)*255/31)};
        assert(fwrite(rgb,1,3,f)==3);
    }
    fclose(f);
}

static void test_states(void)
{
    GameCore_Init(&g);memset(&in,0,sizeof(in));in.confirm=1;
    GameCore_Update(&g,&in);assert(g.mode==GAME_TITLE);
    in.ready=1;GameCore_Update(&g,&in);assert(g.mode==GAME_PLAYING);
    in.confirm=0;in.pause=1;GameCore_Update(&g,&in);
    assert(g.mode==GAME_PAUSED && g.tick==0);
    in.pause=0;
    for(unsigned i=0;i<100;++i) GameCore_Update(&g,&in);
    assert(g.tick==0);
    in.pause=1;GameCore_Update(&g,&in);assert(g.mode==GAME_PLAYING);
    in.pause=0;in.ready=0;GameCore_Update(&g,&in);assert(g.mode==GAME_PAUSED);
}
static void test_motion(void)
{
    float x,y,d;
    reset();x=g.player_x;y=g.player_y;in.x=in.y=1;
    GameCore_Update(&g,&in);d=hypotf(g.player_x-x,g.player_y-y);
    assert(fabsf(d-245.0f/60)<0.001f);
    in.x=-1;in.y=-1;
    for(unsigned i=0;i<1000;++i) GameCore_Update(&g,&in);
    assert(g.player_x>=14 && g.player_y>=GAME_TOP+20);
    reset();x=g.player_x;in.x=1;in.slow=1;GameCore_Update(&g,&in);
    assert(fabsf(g.player_x-x-95.0f/60)<0.001f);
}
static void test_collision_and_bomb(void)
{
    reset();g.invincible=0;
    g.bullets[0]=(GameBullet){g.player_x,g.player_y-20,0,2400,1,0,4};
    GameCore_Update(&g,&in);
    assert(g.lives==2 && g.invincible && !g.bullets[0].active);
    g.bullets[0]=(GameBullet){g.player_x,g.player_y-20,0,2400,1,0,4};
    GameCore_Update(&g,&in);assert(g.lives==2);
    in.bomb=1;GameCore_Update(&g,&in);
    assert(g.bombs==1 && GameCore_BulletCount(&g)==0);
    in.bomb=0;GameCore_Update(&g,&in);assert(g.bombs==1);
    reset();g.boss_active=1;g.boss_hp=100;in.bomb=1;
    GameCore_Update(&g,&in);assert(g.mode==GAME_WON && !g.boss_hp);
    reset();g.lives=1;g.invincible=0;
    g.bullets[0]=(GameBullet){g.player_x,g.player_y,0,0,1,0,4};
    GameCore_Update(&g,&in);assert(g.mode==GAME_LOST && !g.lives);
}
static void test_patterns_and_capacity(void)
{
    reset();g.tick=899;GameCore_Update(&g,&in);assert(g.boss_active);
    g.tick=934;GameCore_Update(&g,&in);assert(GameCore_BulletCount(&g)==18);
    memset(g.bullets,0,sizeof(g.bullets));g.boss_hp=500;g.tick=944;
    GameCore_Update(&g,&in);assert(GameCore_BulletCount(&g)==9);
    memset(g.bullets,0,sizeof(g.bullets));g.boss_hp=200;g.tick=951;
    GameCore_Update(&g,&in);assert(GameCore_BulletCount(&g)==3);
    for(unsigned i=0;i<GAME_ENEMY_BULLETS;++i)
        g.bullets[i]=(GameBullet){20,100,0,0,1,0,4};
    g.tick=958;GameCore_Update(&g,&in);
    assert(GameCore_BulletCount(&g)==GAME_ENEMY_BULLETS && g.dropped_bullets==3);
}
static void test_soak(void)
{
    unsigned k,i;
    reset();
    for(k=0;k<200000;++k) {
        if(g.mode!=GAME_PLAYING) reset();
        in.x=sinf(k*0.01f);in.y=cosf(k*0.017f);in.bomb=k%3000==0;
        GameCore_Update(&g,&in);
        assert(g.player_x>=14 && g.player_x<=GAME_WIDTH-14);
        assert(g.player_y>=GAME_TOP+20 && g.player_y<=GAME_BOTTOM-14);
        for(i=0;i<GAME_ENEMY_BULLETS;++i)
            assert(!g.bullets[i].active || (isfinite(g.bullets[i].x) && isfinite(g.bullets[i].y)));
    }
}
static void test_render(const char *directory)
{
    char path[512];uint16_t expected[GAME_HEIGHT][GAME_WIDTH];
    Renderer_Init();GameCore_Init(&g);render();
    snprintf(path,sizeof(path),"%s/title.ppm",directory);save_ppm(path);
    reset();g.invincible=60000;
    for(unsigned i=0;i<1300;++i) { in.x=sinf(i*0.02f);GameCore_Update(&g,&in); }
    render();
    snprintf(path,sizeof(path),"%s/gameplay.ppm",directory);save_ppm(path);
    /* Dirty repaint must match a fresh reconstruction, including overlap and erasure. */
    for(unsigned i=0;i<15;++i) { in.x=-1;GameCore_Update(&g,&in); }
    render();memcpy(expected,screen,sizeof(screen));
    Renderer_Init();render();assert(memcmp(expected,screen,sizeof(screen))==0);
    g.mode=GAME_PAUSED;render();
    snprintf(path,sizeof(path),"%s/paused.ppm",directory);save_ppm(path);
    g.mode=GAME_DIAGNOSTIC;render();
    snprintf(path,sizeof(path),"%s/diagnostic.ppm",directory);save_ppm(path);
}
int main(int argc,char **argv)
{
    assert(argc==2);
    test_states();test_motion();test_collision_and_bomb();test_patterns_and_capacity();
    test_soak();test_render(argv[1]);
    puts("PASS: state machine, motion, swept collision, bomb, patterns, pool capacity,");
    puts("      200000-step soak, LCD bounds and dirty repaint equality.");
    return 0;
}
