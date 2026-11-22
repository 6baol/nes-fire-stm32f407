/* 480x800 cover library. Art stays in Flash; no menu framebuffer. */
#include <stdio.h>
#include <string.h>
#include "nes_menu.h"
#include "nes_library.h"
#include "nes_import.h"
#include "nes_posters.h"
#include "lcd_draw.h"
#include "bsp_lcd_display.h"
#include "pixel_font.h"
#include "cjk_font.h"
#define BG 0x0865
#define PANEL 0x194C
#define LINE 0x4AD3
#define BORDER 0xBE5F
#define INK 0xFFDF
#define MUTED 0x9D5B
#define ACCENT 0xFE8B
#define ACTIVE 0x31F4
#define ROW_TOP 550
#define ROW_H 52
#define STATUS_Y 774
static void text(unsigned x,unsigned y,const char *s,uint16_t fg,uint16_t bg,unsigned scale)
{PixelFont_Text((uint16_t)x,(uint16_t)(y+4),s,fg,bg,scale);}
static void small(unsigned x,unsigned y,const char *s,uint16_t fg,uint16_t bg)
{text(x,y,s,fg,bg,1);}
static void medium(unsigned x,unsigned y,const char *s,uint16_t fg,uint16_t bg)
{text(x,y,s,fg,bg,2);}
static void fill(unsigned x,unsigned y,unsigned w,unsigned h,uint16_t c)
{lcd_fill_color((uint16_t)x,(uint16_t)y,(uint16_t)w,(uint16_t)h,c);}
static void card(unsigned x,unsigned y,unsigned w,unsigned h,uint16_t c)
{fill(x,y,w,h,BG);fill(x+2,y+2,w-4,h-4,BORDER);fill(x+4,y+4,w-8,h-8,c);}
static void bitmap_scaled(unsigned x,unsigned y,unsigned tw,unsigned th,const NesPoster *p)
{
    uint32_t sx,sy;
    lcd_open_window((uint16_t)x,(uint16_t)y,(uint16_t)tw,(uint16_t)th);
    for(sy=0;sy<th;sy++){
        uint32_t srcy=sy*(uint32_t)p->height/th;
        for(sx=0;sx<tw;sx++){
            uint32_t srcx=sx*(uint32_t)p->width/tw;
            uint32_t offset=srcy*(uint32_t)p->width+srcx;
            uint8_t index;
            if(p->pixel_bits==4){
                uint8_t pair=p->pixels[offset>>1];
                index=(offset&1)?(pair&15):(pair>>4);
            } else index=p->pixels[offset];
            LCD_WRITE_DATA(p->palette[index]);
        }
    }
}
void NesMenu_Init(NesMenuState *m,uint16_t count,uint8_t audio_ok,uint8_t touch_ok)
{m->count=count;m->index=0;m->first=0;m->audio_ok=audio_ok;m->touch_ok=touch_ok;}
int NesMenu_Move(NesMenuState *m,int dir)
{
    int next;
    if(!m->count || !dir)return 0;
    next=(int)m->index+dir;
    if(next<0)next=m->count-1;
    if(next>=m->count)next=0;
    if(next==m->index)return 0;
    m->index=(int16_t)next;
    if(next<m->first)m->first=(uint16_t)next;
    else if(next>=m->first+NES_MENU_ROWS)m->first=(uint16_t)(next-NES_MENU_ROWS+1);
    return 1;
}
int NesMenu_Page(NesMenuState *m,int dir,unsigned step)
{
    int next;
    if(!m->count || !dir)return 0;
    next=(int)m->index+(int)dir*(int)step;
    if(next<0)next=0;
    if(next>=(int)m->count)next=(int)m->count-1;
    if(next==m->index)return 0;
    m->index=(int16_t)next;
    if(next<m->first)m->first=(uint16_t)next;
    else if(next>=m->first+NES_MENU_ROWS)m->first=(uint16_t)(next-NES_MENU_ROWS+1);
    return 1;
}
/* Text wraps at word boundaries; game names are never abbreviated here.
 * Characters are counted in UTF-8 units so a Chinese name occupies one cell. */
static unsigned utf8_seq(unsigned char c)
{return (c<0x80)?1:((c&0xe0)==0xc0)?2:((c&0xf0)==0xe0)?3:((c&0xf8)==0xf0)?4:1;}
static unsigned split_line(const char *source,unsigned limit,char *line)
{
    unsigned n=0,count=0,space=0;
    while(source[n] && count<limit){
        if(source[n]==' ')space=n;
        n+=utf8_seq((unsigned char)source[n]);++count;
    }
    if(source[n] && space)n=space;
    memcpy(line,source,n);line[n]='\0';
    while(source[n]==' ')++n;
    return n;
}
static void full_name(unsigned x,unsigned y,unsigned columns,const char *name,uint16_t bg,int centered)
{
    char line[NES_IMPORT_LABEL_MAX+1];unsigned used=0,row=0;
    unsigned cell=CjkFont_Cell();
    while(name[used] && row<2){
        unsigned n=split_line(name+used,columns,line);
        unsigned start=centered?(480u-Utf8_Length(line)*cell)/2u:x;
        Utf8_Draw((uint16_t)start,(uint16_t)(y+row*cell),line,INK,bg);used+=n;++row;
    }
}
static void fallback_cover(int is_pad)
{
    fill(12,104,456,360,PANEL);
    if(is_pad){medium(160,150,"CONTROLLER",INK,PANEL);medium(208,178,"TEST",INK,PANEL);}
    else medium(176,166,"NO COVER",MUTED,PANEL);
    card(140,254,200,102,INK);
    fill(156,282,58,22,BG);fill(174,264,22,58,BG);fill(176,284,18,18,MUTED);
    card(260,282,24,24,ACCENT);card(294,282,24,24,0xE986);
    fill(228,326,20,5,MUTED);fill(256,326,20,5,MUTED);
}
static void cover_draw(const NesRomImage *game)
{
    const NesPoster *p=NesLibrary_Poster(game);
    if(!p){fallback_cover(!strcmp(game->file,"controller_test.nes"));return;}
    fill(12,104,456,360,p->background);
    /* Wide title captures; portrait posters retain their proportions. */
    if(p->full_art) {
        unsigned w=360u*p->width/p->height,h=360;
        if(w>456){w=456;h=456u*p->height/p->width;}
        bitmap_scaled((480-w)/2,104+(360-h)/2,w,h,p);
    } else bitmap_scaled(12,104,456,360,p);
}
static void detail_header(const NesMenuState *m)
{
    char count[16];
    /* Update only the name and the index; the cover may follow later. */
    fill(12,484,456,48,BG);
    fill(380,36,88,16,BG);
    snprintf(count,sizeof(count),"%u/%u",m->count?(unsigned)m->index+1:0,(unsigned)m->count);
    small((uint16_t)(468u-8u*(unsigned)strlen(count)),36,count,MUTED,BG);
    if(!m->count){full_name(0,484,480u/CjkFont_Cell(),"NO GAMES",BG,1);return;}
    full_name(0,484,480u/CjkFont_Cell(),NesLibrary_Game((unsigned)m->index)->label,BG,1);
}
static void detail_cover(const NesMenuState *m)
{
    if(!m->count){fallback_cover(0);return;}
    cover_draw(NesLibrary_Game((unsigned)m->index));
}
static void detail_draw(const NesMenuState *m)
{
    detail_header(m);
    detail_cover(m);
}
static void row_draw(const NesMenuState *m,unsigned row)
{
    unsigned y=ROW_TOP+row*ROW_H,slot=(unsigned)m->first+row;
    unsigned cell=CjkFont_Cell(),columns=404u/cell;
    uint16_t color=BG;
    fill(12,y,456,48,BG);
    if(slot>=m->count)return;
    if(slot==(unsigned)m->index){color=ACTIVE;fill(12,y,456,48,color);medium(40,y+(48u-16u)/2,">",ACCENT,color);}
    {
        const char *label=NesLibrary_Game(slot)->label;
        unsigned lines=Utf8_Length(label)>columns?2u:1u;
        unsigned top=y+(48u-lines*cell)/2u;
        full_name(76,top,columns,label,color,0);
    }
}
void NesMenu_DrawSelection(const NesMenuState *m)
{unsigned i;detail_draw(m);for(i=0;i<NES_MENU_ROWS;i++)row_draw(m,i);}
void NesMenu_DrawRows(const NesMenuState *m)
{unsigned i;detail_header(m);for(i=0;i<NES_MENU_ROWS;i++)row_draw(m,i);}
void NesMenu_DrawCover(const NesMenuState *m){detail_cover(m);}
void NesMenu_Status(const char *msg)
{fill(12,STATUS_Y,456,14,BG);if(msg && msg[0])small(12,STATUS_Y,msg,ACCENT,BG);}
void NesMenu_Draw(const NesMenuState *m)
{
    fill(0,0,480,800,BG);
    text(12,28,"NES FIRE",INK,BG,3);fill(12,80,456,1,LINE);
    NesMenu_DrawSelection(m);
    fill(12,726,456,1,LINE);
    small(24,742,"UP/DN SELECT  L/R PAGE  CAP/HOLD KEY1 SEARCH",MUTED,BG);
    small(24,758,"KEY2/SW START   KEY1 SETTINGS",MUTED,BG);
    if(!m->audio_ok)small(12,732,"AUDIO OFF",ACCENT,BG);
    if(!m->touch_ok)small(396,732,"TOUCH OFF",MUTED,BG);
    NesMenu_Status("");
}

static void input_key(unsigned x,unsigned y,unsigned w,const char *label,int on)
{
    uint16_t color=on?ACTIVE:PANEL;
    card(x,y,w,44,color);
    medium(x+(w-(unsigned)strlen(label)*16)/2,y+10,label,on?ACCENT:INK,color);
}
void NesSettings_Draw(uint8_t audio_ok)
{
    fill(0,0,480,800,BG);
    text(24,28,"SETTINGS",INK,BG,3);fill(24,80,432,1,LINE);
    medium(24,106,"CONTROLLER CHECK",INK,BG);
    small(24,142,"PRESS BUTTONS TO TEST INPUT",MUTED,BG);
    medium(24,570,"AUDIO OUTPUT",INK,BG);
    NesSettings_Audio(1,audio_ok,0);
    fill(24,726,432,1,LINE);
    small(24,750,"HOLD SW 1.5S: BACK",MUTED,BG);
}
void NesSettings_Audio(uint8_t output,uint8_t audio_ok,uint8_t failed)
{
    const char *label=output==0?"< HEADPHONES >":output==1?"< SPEAKER >":"< MUTE >";
    fill(24,600,432,114,BG);
    card(24,600,432,48,PANEL);
    medium(24+(432-(unsigned)strlen(label)*16)/2,616,label,ACCENT,PANEL);
    small(24,670,!audio_ok?"AUDIO OFF - CHECK CODEC":failed?"SWITCH FAILED - TRY AGAIN":"LEFT/RIGHT: CHANGE OUTPUT",
          (!audio_ok||failed)?ACCENT:MUTED,BG);
    small(24,694,"APPLIES TO ALL GAMES",MUTED,BG);
}
void NesSettings_Update(uint8_t pad,uint16_t raw_x,uint16_t raw_y,
                        uint8_t stick_ready,uint8_t cap_ready,uint16_t cap_raw)
{
    char value[40];
    input_key(96,190,80,"UP",pad&16);
    input_key(24,242,96,"LEFT",pad&64);
    input_key(152,242,96,"RIGHT",pad&128);
    input_key(96,294,80,"DOWN",pad&32);
    input_key(292,214,64,"B",pad&2);
    input_key(376,214,64,"A",pad&1);
    input_key(48,366,160,"SELECT",pad&4);
    input_key(264,366,160,"START",pad&8);
    fill(24,440,432,100,BG);
    snprintf(value,sizeof(value),"STICK X:%4u  Y:%4u",(unsigned)raw_x,(unsigned)raw_y);
    small(24,446,value,MUTED,BG);
    small(24,474,stick_ready?"STICK READY":"STICK CALIBRATING / RECONNECTING",stick_ready?MUTED:ACCENT,BG);
    snprintf(value,sizeof(value),"CAP %s  RAW:%u",cap_ready?"READY":"CALIBRATING",(unsigned)cap_raw);
    small(24,502,value,MUTED,BG);
}

/* ---- On-screen search ------------------------------------------------ */
#define SEARCH_COLS 8
#define SEARCH_ROWS 5
static const char search_grid[SEARCH_ROWS][SEARCH_COLS] = {
    {'A','B','C','D','E','F','G','H'},
    {'I','J','K','L','M','N','O','P'},
    {'Q','R','S','T','U','V','W','X'},
    {'Y','Z','0','1','2','3','4','5'},
    {'6','7','8','9',' ','<','C','*'}
};

void NesSearch_Init(NesSearchState *s)
{
    memset(s,0,sizeof(*s));
}
static void search_draw_query(const NesSearchState *s)
{
    char line[NES_SEARCH_QUERY+2];
    unsigned i;
    for(i=0;i<s->length;i++)line[i]=s->query[i];
    line[s->length]='_';
    line[s->length+1]='\0';
    fill(24,214,432,20,BG);
    medium(24,214,line,INK,BG);
}
void NesSearch_Draw(const NesSearchState *s)
{
    unsigned row,col;
    fill(0,0,480,800,BG);
    text(12,28,"SEARCH",INK,BG,3);
    fill(12,80,456,1,LINE);
    small(24,180,"TYPE LETTERS, THEN * TO SEARCH",MUTED,BG);
    search_draw_query(s);
    for(row=0;row<SEARCH_ROWS;row++){
        for(col=0;col<SEARCH_COLS;col++){
            unsigned x=12+col*57,y=300+row*76;
            unsigned idx=row*SEARCH_COLS+col;
            uint16_t color=idx==s->cursor?ACTIVE:BG;
            char one[2];
            fill(x,y,54,72,color);
            if(color!=BG)fill(x+1,y+1,52,70,BORDER);
            one[0]=search_grid[row][col];one[1]='\0';
            medium(x+(54u-16u)/2u,y+(72u-16u)/2u,one,idx==39?ACCENT:INK,color);
        }
    }
    small(24,742,"STICK MOVE   KEY2 INSERT   * SEARCH",MUTED,BG);
    small(24,758,"KEY1 BACK",MUTED,BG);
}
int NesSearch_Move(NesSearchState *s,int dx,int dy)
{
    int row=s->cursor/SEARCH_COLS,col=s->cursor%SEARCH_COLS;
    int next_row=row+dy,next_col=col+dx;
    if(next_row<0)next_row=SEARCH_ROWS-1;
    if(next_row>=SEARCH_ROWS)next_row=0;
    if(next_col<0)next_col=SEARCH_COLS-1;
    if(next_col>=SEARCH_COLS)next_col=0;
    s->cursor=(uint8_t)(next_row*SEARCH_COLS+next_col);
    return 1;
}
int NesSearch_Select(NesSearchState *s)
{
    unsigned idx=s->cursor;
    if(idx>=SEARCH_ROWS*SEARCH_COLS)return 0;
    if(idx==39)return 1;                    /* '*' runs the search */
    if(idx==37){if(s->length)s->query[--s->length]='\0';}
    else if(idx==38){s->length=0;s->query[0]='\0';}
    else{
        char key=search_grid[idx/SEARCH_COLS][idx%SEARCH_COLS];
        if(s->length<NES_SEARCH_QUERY){s->query[s->length++]=key;s->query[s->length]='\0';}
    }
    search_draw_query(s);
    return 0;
}
