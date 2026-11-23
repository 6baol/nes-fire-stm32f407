/* Cover library drawn straight to the panel; no menu framebuffer.
 * Two layouts share one set of drawing routines: the portrait 480x800 one and
 * the 800x480 landscape one, which puts the list on the left and the cover on
 * the right. nes_screen_landscape selects between them. */
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

extern volatile uint8_t nes_screen_landscape;

typedef struct {
    unsigned w,h;
    unsigned title_x,title_y,title_scale;
    unsigned count_y;
    unsigned name_y;             /* detail name under the cover */
    unsigned cover_x,cover_y,cover_w,cover_h;
    unsigned list_x,list_y,list_w,row_h,text_off,rows;
    unsigned info_y;
    unsigned rule_y,foot1_y,foot2_y,status_y;
    unsigned cols;               /* usable columns in a list row */
} UiLayout;

static const UiLayout PORTRAIT={480,800, 12,28,3, 36, 484, 12,104,456,360, 12,550,456,52,64,3, 530, 726,742,758,774, 404};
static const UiLayout LANDSCAPE={800,480, 16,6,2, 8, 36, 396,56,388,291, 16,92,360,56,30,4, 322, 380,392,412,440, 330};

static const UiLayout *ui(void)
{return nes_screen_landscape?&LANDSCAPE:&PORTRAIT;}

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
    int next;unsigned rows=ui()->rows;
    if(!m->count || !dir)return 0;
    next=(int)m->index+dir;
    if(next<0)next=m->count-1;
    if(next>=m->count)next=0;
    if(next==m->index)return 0;
    m->index=(int16_t)next;
    if(next<m->first)m->first=(uint16_t)next;
    else if(next>=(int)(m->first+rows))m->first=(uint16_t)(next-(int)rows+1);
    return 1;
}
int NesMenu_Page(NesMenuState *m,int dir,unsigned step)
{
    int next;unsigned rows=ui()->rows;
    if(!m->count || !dir)return 0;
    next=(int)m->index+(int)dir*(int)step;
    if(next<0)next=0;
    if(next>=(int)m->count)next=(int)m->count-1;
    if(next==m->index)return 0;
    m->index=(int16_t)next;
    if(next<m->first)m->first=(uint16_t)next;
    else if(next>=(int)(m->first+rows))m->first=(uint16_t)(next-(int)rows+1);
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
static void full_name(unsigned x,unsigned y,unsigned width,unsigned columns,const char *name,uint16_t bg,int centered)
{
    char line[NES_IMPORT_LABEL_MAX+1];unsigned used=0,row=0;
    unsigned cell=CjkFont_Cell();
    while(name[used] && row<2){
        unsigned n=split_line(name+used,columns,line);
        unsigned start=centered?(unsigned)((int)width-(int)(Utf8_Length(line)*cell))/2u:x;
        Utf8_Draw((uint16_t)start,(uint16_t)(y+row*cell),line,INK,bg);used+=n;++row;
    }
}
static void fallback_cover(int is_pad)
{
    const UiLayout *l=ui();
    unsigned x=l->cover_x,y=l->cover_y,w=l->cover_w,h=l->cover_h;
    fill(x,y,w,h,PANEL);
    if(is_pad){
        medium(x+w/2-80,y+h/2-40,"CONTROLLER",INK,PANEL);
        medium(x+w/2-32,y+h/2-12,"TEST",INK,PANEL);
    } else medium(x+w/2-64,y+h/2-8,"NO COVER",MUTED,PANEL);
}
static void cover_draw(const NesRomImage *game)
{
    const UiLayout *l=ui();
    const NesPoster *p=NesLibrary_Poster(game);
    if(!p){fallback_cover(!strcmp(game->file,"controller_test.nes"));return;}
    fill(l->cover_x,l->cover_y,l->cover_w,l->cover_h,p->background);
    /* Wide title captures; portrait posters retain their proportions. */
    if(p->full_art) {
        unsigned w=l->cover_h*p->width/p->height,h=l->cover_h;
        if(w>l->cover_w){w=l->cover_w;h=l->cover_w*p->height/p->width;}
        bitmap_scaled(l->cover_x+(l->cover_w-w)/2,l->cover_y+(l->cover_h-h)/2,w,h,p);
    } else bitmap_scaled(l->cover_x,l->cover_y,l->cover_w,l->cover_h,p);
}
static void detail_header(const NesMenuState *m)
{
    const UiLayout *l=ui();
    char count[16];
    /* Update only the name and the index; the cover may follow later. */
    /* Landscape has no room for a second name line: the highlighted row
     * already carries the title, so only the counter is updated there. */
    if(nes_screen_landscape)return;
    fill(l->list_x,l->name_y,l->list_w,CjkFont_Cell()+4,BG);
    fill(l->w-108,l->count_y,96,16,BG);
    snprintf(count,sizeof(count),"%u/%u",m->count?(unsigned)m->index+1:0,(unsigned)m->count);
    small((uint16_t)(l->w-12u-8u*(unsigned)strlen(count)),l->count_y,count,MUTED,BG);
    if(!m->count){full_name(l->list_x,l->name_y,l->list_w,l->cols/CjkFont_Cell(),"NO GAMES",BG,0);return;}
    {
        const NesRomImage *game=NesLibrary_Game((unsigned)m->index);
        if(game)full_name(l->list_x,l->name_y,l->list_w,l->cols/CjkFont_Cell(),game->label,BG,0);
    }
}
static void detail_cover(const NesMenuState *m)
{
    const NesRomImage *game=m->count?NesLibrary_Game((unsigned)m->index):0;
    if(game)cover_draw(game);
    else fallback_cover(0);
}
static void detail_draw(const NesMenuState *m)
{
    detail_header(m);
    detail_cover(m);
}
static void row_draw(const NesMenuState *m,unsigned row)
{
    const UiLayout *l=ui();
    unsigned y=l->list_y+row*l->row_h,slot=(unsigned)m->first+row;
    unsigned cell=CjkFont_Cell(),columns=l->cols/cell;
    uint16_t color=BG;
    fill(l->list_x,y,l->list_w,l->row_h-4,BG);
    if(slot>=m->count)return;
    if(slot==(unsigned)m->index){color=ACTIVE;fill(l->list_x,y,l->list_w,l->row_h-4,color);medium(l->list_x+4,y+(l->row_h-4u-16u)/2,">",ACCENT,color);}
    {
        const NesRomImage *game=NesLibrary_Game(slot);
        const char *label=game?game->label:"ENTRY UNAVAILABLE";
        unsigned lines=Utf8_Length(label)>columns?2u:1u;
        unsigned top=y+((l->row_h-4u)-lines*cell)/2u;
        full_name(l->list_x+l->text_off,top,l->list_w-l->text_off,columns,label,color,0);
    }
}
void NesMenu_DrawSelection(const NesMenuState *m)
{unsigned i,rows=ui()->rows;detail_draw(m);for(i=0;i<rows;i++)row_draw(m,i);}
void NesMenu_DrawRows(const NesMenuState *m)
{unsigned i,rows=ui()->rows;detail_header(m);for(i=0;i<rows;i++)row_draw(m,i);}
void NesMenu_DrawCover(const NesMenuState *m){detail_cover(m);}
void NesMenu_Info(const char *msg)
{
    const UiLayout *l=ui();
    fill(l->list_x,l->info_y,l->list_w,16,BG);
    if(msg&&msg[0])small(l->list_x,l->info_y,msg,MUTED,BG);
}
void NesMenu_Status(const char *msg)
{
    const UiLayout *l=ui();
    fill(l->list_x,l->status_y,l->list_w,14,BG);
    if(msg && msg[0])small(l->list_x,l->status_y,msg,ACCENT,BG);
}
void NesMenu_Draw(const NesMenuState *m)
{
    const UiLayout *l=ui();
    fill(0,0,l->w,l->h,BG);
    text(l->title_x,l->title_y,"NES FIRE",INK,BG,l->title_scale);
    fill(l->list_x,l->title_y+20u*l->title_scale,l->list_w,1,LINE);
    NesMenu_DrawSelection(m);
    fill(l->list_x,l->rule_y,l->list_w,1,LINE);
    small(l->list_x,l->foot1_y,nes_screen_landscape?"UP/DN MOVE  L/R PAGE  A OK  B BACK":"UP/DN SELECT  A OK  B BACK  SEL DOWN",MUTED,BG);
    small(l->list_x,l->foot2_y,nes_screen_landscape?"KEY1 SETTINGS  KEY2 LIBRARY  CAP ROTATE":"KEY1 SETTINGS  KEY2 LIBRARY  CAP ROTATE",MUTED,BG);
    if(!m->audio_ok)small(l->w-72,l->foot2_y,"AUDIO OFF",ACCENT,BG);
    if(!m->touch_ok)small(l->w-72,l->foot1_y,"TOUCH OFF",MUTED,BG);
    NesMenu_Status("");
}

void NesMenu_LibraryOptions(unsigned cursor,unsigned current_view,int favorite,int has_game)
{
    static const char *const labels[]={"SEARCH", "ALL GAMES", "LOADABLE HEADERS",
        "UNSUPPORTED", "FAVORITES", "RECENTLY PLAYED"};
    unsigned i;
    int wide=nes_screen_landscape;
    unsigned w=wide?800:480,h=wide?480:800;
    unsigned x0=wide?24:24,top=wide?72:126,step=wide?68:72;
    fill(0,0,w,h,BG);
    text(x0,20,"LIBRARY",INK,BG,3);
    fill(x0,64,w-2*x0,1,LINE);
    for(i=0;i<NES_LIBRARY_OPTIONS;i++) {
        unsigned y=top+i*step;
        uint16_t bg=i==cursor?ACTIVE:PANEL;
        const char *label=i<6?labels[i]:favorite?"REMOVE FAVORITE":"ADD FAVORITE";
        fill(x0,y,w-2*x0,52,bg);
        if(i==current_view)medium(x0+16,y+12,">",ACCENT,bg);
        medium(x0+46,y+12,label,i==6&&!has_game?MUTED:INK,bg);
    }
    small(x0,wide?450u:742u,"UP/DN MOVE   KEY2/SW SELECT   KEY1 BACK",MUTED,BG);
}

void NesMenu_SaveError(const char *reason)
{
    int wide=nes_screen_landscape;
    unsigned w=wide?800:480,h=wide?480:800,x0=wide?24:24;
    fill(0,0,w,h,BG);
    text(x0,wide?20u:28u,"SAVE FAILED",ACCENT,BG,3);
    fill(x0,wide?64u:80u,w-2*x0,1,LINE);
    small(x0,wide?120u:155u,reason,MUTED,BG);
    medium(x0,wide?190u:244u,"KEY2/SW RETRY SAVE",INK,BG);
    medium(x0,wide?240u:294u,"KEY1 RESUME GAME",INK,BG);
    small(x0,wide?310u:368u,"KEEP POWER ON TO RETAIN THIS PROGRESS",MUTED,BG);
}

static void input_key(unsigned x,unsigned y,unsigned w,const char *label,int on)
{
    uint16_t color=on?ACTIVE:PANEL;
    card(x,y,w,44,color);
    medium(x+(w-(unsigned)strlen(label)*16)/2,y+10,label,on?ACCENT:INK,color);
}
void NesSettings_Draw(uint8_t audio_ok)
{
    int wide=nes_screen_landscape;
    unsigned w=wide?800:480,h=wide?480:800,x0=24;
    fill(0,0,w,h,BG);
    text(x0,wide?18u:28u,"SETTINGS",INK,BG,3);fill(x0,wide?62u:80u,w-2*x0,1,LINE);
    medium(x0,wide?82u:106u,"CONTROLLER CHECK",INK,BG);
    small(x0,wide?112u:142u,"PRESS BUTTONS TO TEST INPUT",MUTED,BG);
    if(wide){
        /* Two columns: controller test on the left, switches on the right. */
        medium(460,82,"SCREEN",INK,BG);
        NesSettings_Screen(nes_screen_landscape);
        medium(460,190,"AUDIO OUTPUT",INK,BG);
        NesSettings_Audio(1,audio_ok,0);
        fill(x0,440,w-2*x0,1,LINE);
        small(x0,452,"HOLD SW 1.5S: BACK",MUTED,BG);
    } else {
        medium(x0,500,"SCREEN",INK,BG);
        NesSettings_Screen(nes_screen_landscape);
        medium(x0,570,"AUDIO OUTPUT",INK,BG);
        NesSettings_Audio(1,audio_ok,0);
        fill(x0,726,w-2*x0,1,LINE);
        small(x0,750,"HOLD SW 1.5S: BACK",MUTED,BG);
    }
}
void NesSettings_Screen(uint8_t landscape)
{
    int wide=nes_screen_landscape;
    unsigned x0=wide?460u:24u,w=wide?316u:480u;
    unsigned top=wide?104u:530u;
    const char *label=landscape?"< LANDSCAPE >":"< PORTRAIT >";
    fill(x0,top,w,74,BG);
    card(x0,top,w,44,PANEL);
    medium(x0+(w-(unsigned)strlen(label)*16)/2,top+14,label,ACCENT,PANEL);
    small(x0,top+52,"UP/DOWN: ROTATE 90",MUTED,BG);
}
void NesSettings_Audio(uint8_t output,uint8_t audio_ok,uint8_t failed)
{
    int wide=nes_screen_landscape;
    unsigned x0=wide?460u:24u,w=wide?316u:480u;
    unsigned top=wide?212u:600u;
    const char *label=output==0?"< HEADPHONES >":output==1?"< SPEAKER >":"< MUTE >";
    fill(x0,top,w,114,BG);
    card(x0,top,w,48,PANEL);
    medium(x0+(w-(unsigned)strlen(label)*16)/2,top+16,label,ACCENT,PANEL);
    small(x0,top+70,!audio_ok?"AUDIO OFF - CHECK CODEC":failed?"SWITCH FAILED - TRY AGAIN":"LEFT/RIGHT: CHANGE OUTPUT",
          (!audio_ok||failed)?ACCENT:MUTED,BG);
    small(x0,top+94,"APPLIES TO ALL GAMES",MUTED,BG);
}
void NesSettings_Update(uint8_t pad,uint16_t raw_x,uint16_t raw_y,
                        uint8_t stick_ready,uint8_t cap_ready,uint16_t cap_raw)
{
    char value[40];
    int wide=nes_screen_landscape;
    unsigned y0=wide?130u:190u;
    input_key(wide?96u:96u,y0,80,"UP",pad&16);
    input_key(wide?24u:24u,y0+52,96,"LEFT",pad&64);
    input_key(wide?152u:152u,y0+52,96,"RIGHT",pad&128);
    input_key(wide?96u:96u,y0+104,80,"DOWN",pad&32);
    input_key(wide?284u:292u,y0+24,64,"B",pad&2);
    input_key(wide?356u:376u,y0+24,64,"A",pad&1);
    input_key(wide?24u:48u,y0+180,160,"SELECT",pad&4);
    input_key(wide?196u:264u,y0+180,160,"START",pad&8);
    fill(24,wide?390u:440u,wide?400u:432u,80,BG);
    snprintf(value,sizeof(value),"STICK X:%4u  Y:%4u",(unsigned)raw_x,(unsigned)raw_y);
    small(24,wide?396u:446u,value,MUTED,BG);
    small(24,wide?418u:474u,stick_ready?"STICK READY":"STICK CALIBRATING / RECONNECTING",stick_ready?MUTED:ACCENT,BG);
    snprintf(value,sizeof(value),"CAP %s  RAW:%u",cap_ready?"READY":"CALIBRATING",(unsigned)cap_raw);
    small(24,wide?440u:502u,value,MUTED,BG);
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
    int wide=nes_screen_landscape;
    unsigned i;
    for(i=0;i<s->length;i++)line[i]=s->query[i];
    line[s->length]='_';
    line[s->length+1]='\0';
    fill(24,wide?128u:214u,wide?640u:432u,20,BG);
    medium(24,wide?128u:214u,line,INK,BG);
}
void NesSearch_Draw(const NesSearchState *s)
{
    unsigned row,col;
    int wide=nes_screen_landscape;
    unsigned w=wide?800:480,h=wide?480:800;
    unsigned top=wide?168u:300u,step=wide?60u:76u,cell_h=wide?52u:72u,cell_w=wide?54u:54u;
    fill(0,0,w,h,BG);
    text(12,wide?14u:28u,"SEARCH",INK,BG,3);
    fill(12,wide?60u:80u,w-24,1,LINE);
    small(24,wide?96u:180u,"TYPE LETTERS, THEN * TO SEARCH",MUTED,BG);
    search_draw_query(s);
    for(row=0;row<SEARCH_ROWS;row++){
        for(col=0;col<SEARCH_COLS;col++){
            unsigned x=12+col*(cell_w+3),y=top+row*step;
            unsigned idx=row*SEARCH_COLS+col;
            uint16_t color=idx==s->cursor?ACTIVE:BG;
            char one[2];
            fill(x,y,cell_w,cell_h,color);
            if(color!=BG)fill(x+1,y+1,cell_w-2,cell_h-2,BORDER);
            one[0]=search_grid[row][col];one[1]='\0';
            medium(x+(cell_w-16u)/2u,y+(cell_h-16u)/2u,one,idx==39?ACCENT:INK,color);
        }
    }
    small(24,wide?452u:742u,wide?"STICK MOVE  KEY2 INSERT  * SEARCH  KEY1 BACK":"STICK MOVE   KEY2 INSERT   * SEARCH",MUTED,BG);
    if(!wide)small(24,758,"KEY1 BACK",MUTED,BG);
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
