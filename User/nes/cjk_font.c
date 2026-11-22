/* 16x16 or 24x24 CJK glyphs from the SD card. ASCII stays on the Flash pixel
 * font, scaled so both use the same cell. FONT.MAP stores the cell size. */
#include <string.h>
#include "cjk_font.h"
#include "ff.h"
#include "pixel_font.h"
#include "lcd_draw.h"
#include "bsp_lcd_display.h"

#define FONT_MAP_PATH "0:/NES/FONT.MAP"
#define FONT_HZK_PATH "0:/NES/FONT.HZK"
/* Map in the top 32 KiB of the arena, decoded glyph cache right after it.
 * The menu owns the arena; loading a ROM calls CjkFont_Invalidate first. */
#define FONT_MAP_ADDR 0x6c0f0000u
#define FONT_MAP_MAX  0x00008000u
#define FONT_CACHE_ADDR 0x6c0f8000u
#define GLYPH_BYTES 72u
#define GLYPH_CACHE 384u
#define CELL_DEFAULT 16u

typedef struct {
    uint16_t slot;
    uint8_t used;
    uint8_t bits[GLYPH_BYTES];
} GlyphCache;

static FIL font_file;
static FIL hzk_file;
static GlyphCache *glyphs=(GlyphCache*)FONT_CACHE_ADDR;
static unsigned map_count;
static unsigned cell=CELL_DEFAULT;
static unsigned stride=2;
static unsigned glyph_bytes;
static uint8_t map_ready,map_tried,hzk_open;

static uint16_t le16(const uint8_t *p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static uint32_t le32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}

static const uint8_t *map_entries(void){return (const uint8_t*)FONT_MAP_ADDR+12;}

void CjkFont_Invalidate(void)
{
    if(hzk_open){(void)f_close(&hzk_file);hzk_open=0;}
    memset(glyphs,0,GLYPH_CACHE*sizeof(GlyphCache));
    map_ready=0;map_count=0;map_tried=0;
    cell=CELL_DEFAULT;stride=2;glyph_bytes=0;
}
int CjkFont_Ready(void)
{
    UINT got;uint32_t bytes;
    if(map_ready)return 1;
    if(map_tried)return 0;          /* one attempt per boot; no per-draw retry */
    map_tried=1;
    if(f_open(&font_file,FONT_MAP_PATH,FA_READ)!=FR_OK)return 0;
    bytes=(uint32_t)f_size(&font_file);
    if(bytes<16||bytes>FONT_MAP_MAX){(void)f_close(&font_file);return 0;}
    if(f_read(&font_file,(void*)FONT_MAP_ADDR,bytes,&got)!=FR_OK||got!=bytes){
        (void)f_close(&font_file);return 0;
    }
    (void)f_close(&font_file);
    if(memcmp((const void*)FONT_MAP_ADDR,"NESFM1",6))return 0;
    {
        unsigned size=((const uint8_t*)FONT_MAP_ADDR)[6];
        if(size<8||size>24)size=CELL_DEFAULT;
        cell=size;stride=(size+7)/8;glyph_bytes=stride*size;
    }
    map_count=le32((const uint8_t*)FONT_MAP_ADDR+8);
    if(map_count<1||(uint32_t)map_count*4+12>bytes)return 0;
    memset(glyphs,0,GLYPH_CACHE*sizeof(GlyphCache));
    map_ready=1;
    return 1;
}
unsigned CjkFont_Cell(void)
{
    (void)CjkFont_Ready();
    return cell;
}
static int map_find(uint32_t code,uint16_t *slot)
{
    unsigned lo=0,hi=map_count;
    const uint8_t *e=map_entries();
    while(lo<hi){
        unsigned mid=(lo+hi)/2;
        uint16_t value=le16(e+mid*4);
        if(value==code){*slot=le16(e+mid*4+2);return 1;}
        if(value<code)lo=mid+1;else hi=mid;
    }
    return 0;
}
static const uint8_t *glyph_bits(uint16_t slot)
{
    GlyphCache *entry=&glyphs[slot%GLYPH_CACHE];
    UINT got;
    if(entry->used&&entry->slot==slot)return entry->bits;
    if(!hzk_open){
        if(f_open(&hzk_file,FONT_HZK_PATH,FA_READ)!=FR_OK)return 0;
        hzk_open=1;
    }
    if(f_lseek(&hzk_file,(uint32_t)slot*glyph_bytes)!=FR_OK)return 0;
    if(f_read(&hzk_file,entry->bits,glyph_bytes,&got)!=FR_OK||got!=glyph_bytes){
        entry->used=0;return 0;
    }
    entry->slot=slot;entry->used=1;
    return entry->bits;
}
static uint32_t utf8_next(const char **s)
{
    const uint8_t *p=(const uint8_t*)*s;
    uint32_t cp;unsigned extra,i;
    if(*p<0x80){(*s)++;return *p;}
    if((*p&0xe0)==0xc0){cp=*p&0x1f;extra=1;}
    else if((*p&0xf0)==0xe0){cp=*p&0x0f;extra=2;}
    else if((*p&0xf8)==0xf0){cp=*p&0x07;extra=3;}
    else {(*s)++;return 0xfffd;}
    for(i=1;i<=extra;i++){
        if((p[i]&0xc0)!=0x80){(*s)++;return 0xfffd;}
        cp=(cp<<6)|(p[i]&0x3f);
    }
    *s+=extra+1;
    return cp;
}
unsigned Utf8_Length(const char *utf8)
{
    unsigned n=0;
    while(*utf8){
        if((*utf8&0xc0)!=0x80)n++;
        utf8++;
    }
    return n;
}
static void draw_cell(uint16_t x,uint16_t y,uint32_t code,uint16_t fg,uint16_t bg)
{
    uint16_t slot;const uint8_t *bits;
    unsigned row,col;
    unsigned ascii_y=y+(cell-8u*(cell/8u))/2u;   /* centre 8x8*scale in the cell */
    if(code<0x80){
        char one[2];one[0]=(char)code;one[1]=0;
        PixelFont_Text(x,(uint16_t)ascii_y,one,fg,bg,cell/8);
        return;
    }
    if(!map_find(code,&slot)||!(bits=glyph_bits(slot))){
        char one[2];one[0]='?';one[1]=0;
        PixelFont_Text(x,(uint16_t)ascii_y,one,fg,bg,cell/8);
        return;
    }
    lcd_open_window(x,y,(uint16_t)cell,(uint16_t)cell);
    for(row=0;row<cell;row++){
        for(col=0;col<cell;col++){
            uint8_t value=bits[row*stride+col/8];
            LCD_WRITE_DATA((value&(0x80>>(col%8)))?fg:bg);
        }
    }
}
unsigned Utf8_Draw(uint16_t x0,uint16_t y,const char *utf8,uint16_t fg,uint16_t bg)
{
    uint16_t x=x0;
    (void)CjkFont_Ready();   /* draw_cell falls back to '?' without the card font */
    while(*utf8){
        uint32_t code=utf8_next(&utf8);
        if(!code)break;
        if(x+cell>480)break;
        draw_cell(x,y,code,fg,bg);
        x=(uint16_t)(x+cell);
    }
    return (unsigned)(x-x0);
}
