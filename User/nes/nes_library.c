#include <stdio.h>
#include <stddef.h>
#include <string.h>
#include "nes_library.h"
#include "nes_import.h"
#include "cjk_font.h"
#include "nes_main.h"
#include "ff.h"
#include "bsp_sdio.h"

/* The listing lives on the card so the entry count costs no RAM:
 *   NES/CATALOG.IDX  fixed records, rebuilt only when NES/ changes
 *   NES/TITLES.DB    optional fingerprint -> title dictionary (UTF-8)
 *   NES/COMPAT.IDX   optional header checks bound to the catalog snapshot
 * Paths are UTF-8 relative to NES/ and may point into subdirectories. */
#define NES_DIR "/NES"
#define CATALOG_PATH "0:/NES/CATALOG.IDX"
#define CATALOG_NEW "0:/NES/CATALOG.NEW"
#define CATALOG_BACKUP "0:/NES/CATALOG.BAK"
#define COMPAT_PATH "0:/NES/COMPAT.IDX"
#define COMPAT_MAGIC "NESCMP1"
#define COMPAT_HEADER 20u
#define COMPAT_RECORD 4u
#define TITLES_PATH "0:/NES/TITLES.DB"
#define NES_PATH_MAX (NES_IMPORT_PATH_MAX + 16)
#define CAT_MAGIC "NESCAT5"
#define CAT_HEADER 32u
#define CAT_RECORD 312u
#define CAT_WINDOW 4u
#define CAT_HASH_MAX 4096u
#define CAT_SCAN_RECORDS 48u
#define CAT_SCAN_ADDR (NES_ROM_ARENA_ADDR + COVER_MAX_BYTES)
#define CAT_TEMP_BYTES (NES_MMC5_ARENA_BYTES - 0x10000u)
#define PINYIN_MAX 39
#define WALK_DEPTH 4u
#define TITLES_MAX_BYTES (320u * 1024u)
#define TITLES_CHUNK 4096u
#define COVER_MAX_BYTES (128u * 1024u)
#define SAVE_BYTES 8192u
#define SAVE_HEADER 28u
#define QUERY_MAX 96u
#define FAVORITE_MAX 64u
#define RECENT_MAX 32u
#define PREFS_SLOT0 "0:/NES/PREFS0.DAT"
#define PREFS_SLOT1 "0:/NES/PREFS1.DAT"
#define SETTINGS_PATH "0:/NES/SETTINGS.BIN"
#define SETTINGS_BYTES 8u
#define SETTINGS_VERSION 1u

typedef struct {
    uint32_t magic;
    uint32_t generation;
    uint32_t favorite_count;
    uint32_t recent_count;
    uint64_t favorites[FAVORITE_MAX];
    uint64_t recent[RECENT_MAX];
    uint32_t crc;
    uint32_t reserved;
} LibraryPrefs;

typedef struct {
    uint32_t size;
    uint32_t stamp;      /* FAT date/time, used to merge an unchanged entry */
    uint32_t flags;      /* 1 = FDS */
    char path[NES_IMPORT_PATH_MAX + 1];
    char label[NES_IMPORT_LABEL_MAX + 1];
    char pinyin[PINYIN_MAX + 1];   /* filled by tools/make_pinyin.py */
    uint8_t reserved[2];
} CatalogRecord;

typedef char catalog_record_size_check[(sizeof(CatalogRecord) == CAT_RECORD) ? 1 : -1];
typedef struct { uint32_t hash; uint16_t index; uint16_t used; } MergeSlot;
typedef void (*WalkFn)(const char *path,const FILINFO *fno,uint8_t fds,void *ctx);

static FATFS fs;
static FIL file;
static FIL writer;
static CatalogRecord cat_window[CAT_WINDOW];
static unsigned window_first;
static uint8_t window_valid;
static NesRomImage scratch;
static char scratch_path[NES_IMPORT_PATH_MAX + 1];
static char scratch_label[NES_IMPORT_LABEL_MAX + 1];
static unsigned scratch_index;
static unsigned catalog_count;
static unsigned overflow_count;
static const char *catalog_file_path=CATALOG_PATH;
static const char *const catalog_files[]={CATALOG_PATH,CATALOG_NEW,CATALOG_BACKUP};
/* A search result is a list of catalog indices; Count/Game/Load then see only
 * those entries. 2048 x 2 bytes in internal RAM. */
static uint16_t view[NES_CATALOG_MAX];
static unsigned view_count;
static uint8_t view_active;
static unsigned view_filter;
static char view_query[QUERY_MAX+1];
static uint8_t search_failed;
static unsigned filter_next;
static uint8_t filter_retry;
/* The low twelve bits hold the mapper and the high nibble holds status. */
static uint16_t compatibility[NES_CATALOG_MAX];
static LibraryPrefs prefs,prefs_work;
static int prefs_slot;
static uint8_t sd_active,arena_menu=1;
/* A user-supplied FDS BIOS on the card takes precedence over the embedded one.
 * 8 KiB is read once at boot; an invalid size/vector leaves the fallback. */
static uint8_t card_fds_bios[8192];
const uint8_t *nes_fds_bios_override;
uint32_t nes_fds_bios_override_size;
static void load_card_fds_bios(void)
{
    UINT got;
    nes_fds_bios_override=0;nes_fds_bios_override_size=0;
    if(f_open(&file,"0:/NES/DISKSYS.ROM",FA_READ)!=FR_OK)return;
    if(f_size(&file)!=8192){f_close(&file);return;}
    if(f_read(&file,card_fds_bios,8192,&got)!=FR_OK||got!=8192){f_close(&file);return;}
    if(f_close(&file)!=FR_OK)return;
    if(((uint32_t)card_fds_bios[0x1ffc]|((uint32_t)card_fds_bios[0x1ffd]<<8))<0xe000)return;
    nes_fds_bios_override=card_fds_bios;
    nes_fds_bios_override_size=8192;
}
static uint8_t input_profile;
unsigned NesLibrary_InputProfile(void){return input_profile;}
static int cached_cover=-1;
static NesPoster poster;
static const char *status="",*error="";
static char sd_status[48];
static char rom_error[48];
static uint8_t save_buffer[SAVE_BYTES];
volatile uint32_t nes_sd_file_reads;
volatile uint32_t nes_sd_save_writes,nes_sd_save_restores;
static uint8_t save_active;
static int8_t save_slot=-1;
static uint32_t save_key,save_rom_size,save_generation,save_baseline;
/* One set of directory objects per recursion level: a parent's FILINFO must
 * stay valid while a subdirectory is being walked. */
static DIR walk_dir[WALK_DEPTH];
static FILINFO walk_info[WALK_DEPTH];
static char walk_full[WALK_DEPTH][NES_PATH_MAX];
static char walk_rel[WALK_DEPTH][NES_IMPORT_PATH_MAX + 1];

static uint32_t le32(const uint8_t *p){return (uint32_t)p[0]|((uint32_t)p[1]<<8)|((uint32_t)p[2]<<16)|((uint32_t)p[3]<<24);}
static uint16_t le16c(const uint8_t *p){return (uint16_t)(p[0]|((uint16_t)p[1]<<8));}
static void put32(uint8_t *p,uint32_t v)
{p[0]=(uint8_t)v;p[1]=(uint8_t)(v>>8);p[2]=(uint8_t)(v>>16);p[3]=(uint8_t)(v>>24);}
static uint32_t crc_step(uint32_t crc,const uint8_t *p,uint32_t size)
{
    uint32_t i;unsigned b;
    for(i=0;i<size;i++){crc^=p[i];for(b=0;b<8;b++)crc=(crc>>1)^((0u-(crc&1u))&0xedb88320u);}
    return crc;
}
static uint32_t crc32(const uint8_t *p,uint32_t size){return ~crc_step(~0u,p,size);}
static uint32_t fnv1a(const char *s)
{
    uint32_t h=2166136261u;
    while(*s)h=(h^(uint8_t)*s++)*16777619u;
    return h;
}
static void save_path(char *path,unsigned slot)
{snprintf(path,40,"0:/NES/SAVES/%08lX.SV%u",(unsigned long)save_key,slot);}
/* 1=valid, 0=absent, -1=invalid, -2=I/O error. */
static int save_read(unsigned slot,uint32_t *generation,uint32_t *checksum)
{
    char path[40];uint8_t h[SAVE_HEADER];UINT got;FRESULT fr;int result=-1;
    save_path(path,slot);fr=f_open(&file,path,FA_READ);
    if(fr==FR_NO_FILE||fr==FR_NO_PATH)return 0;
    if(fr!=FR_OK)return -2;
    if(f_size(&file)!=SAVE_HEADER+SAVE_BYTES)goto done;
    ++nes_sd_file_reads;
    fr=f_read(&file,h,sizeof(h),&got);
    if(fr!=FR_OK||got!=sizeof(h)){result=-2;goto done;}
    if(memcmp(h,"NSV1",4)||le32(h+4)!=save_key||le32(h+8)!=save_rom_size||
       le32(h+12)!=SAVE_BYTES||le32(h+24)!=crc32(h,24))goto done;
    ++nes_sd_file_reads;fr=f_read(&file,save_buffer,SAVE_BYTES,&got);
    if(fr!=FR_OK||got!=SAVE_BYTES){result=-2;goto done;}
    if(crc32(save_buffer,SAVE_BYTES)!=le32(h+20))goto done;
    *generation=le32(h+16);*checksum=le32(h+20);result=1;
done:
    if(f_close(&file)!=FR_OK)result=-2;
    return result;
}
static int save_restore(uint32_t key,uint32_t rom_size)
{
    unsigned slot;uint32_t generation,checksum;int result,bad=0,io_error=0;
    save_active=0;save_slot=-1;save_generation=0;
    if(!sd_active||MapperNo==20||!(RomHeader->flags_1&2))return 0;
    save_key=key;save_rom_size=rom_size;
    save_baseline=crc32(NES_SRAM,SAVE_BYTES);
    for(slot=0;slot<2;slot++) {
        result=save_read(slot,&generation,&checksum);
        if(result<0){bad=1;if(result==-2)io_error=1;continue;}
        if(result==1&&(save_slot<0||(int32_t)(generation-save_generation)>0)) {
            memcpy(NES_SRAM,save_buffer,SAVE_BYTES);save_slot=(int8_t)slot;
            save_generation=generation;save_baseline=checksum;
        }
    }
    if(save_slot<0&&bad){error=io_error?"SD SAVE READ ERROR":"SD SAVE INVALID - CHECK SAVES";return 1;}
    if(save_slot>=0){++nes_sd_save_restores;status=bad?"SAVE BACKUP LOADED":"SAVE LOADED";}
    save_active=1;return 0;
}
int NesLibrary_SavePending(void)
{return save_active&&crc32(NES_SRAM,SAVE_BYTES)!=save_baseline;}
int NesLibrary_Save(void)
{
    uint32_t checksum,generation,verify_gen,verify_crc;unsigned slot;
    char path[40];uint8_t h[SAVE_HEADER];UINT wrote;FRESULT fr;int failed,opened=0;
    if(!save_active)return 0;
    checksum=crc32(NES_SRAM,SAVE_BYTES);
    if(checksum==save_baseline)return 0;
    slot=save_slot<0?0u:(unsigned)(1-save_slot);generation=save_generation+1;
    fr=f_mkdir("0:/NES/SAVES");if(fr!=FR_OK&&fr!=FR_EXIST)goto failure;
    memcpy(h,"NSV1",4);put32(h+4,save_key);put32(h+8,save_rom_size);put32(h+12,SAVE_BYTES);
    put32(h+16,generation);put32(h+20,checksum);put32(h+24,crc32(h,24));
    save_path(path,slot);
    if(f_open(&file,path,FA_WRITE|FA_CREATE_ALWAYS)!=FR_OK)goto failure;
    opened=1;
    fr=f_write(&file,h,sizeof(h),&wrote);failed=(fr!=FR_OK||wrote!=sizeof(h));
    if(!failed){fr=f_write(&file,NES_SRAM,SAVE_BYTES,&wrote);failed=(fr!=FR_OK||wrote!=SAVE_BYTES);}
    if(!failed)failed=(f_sync(&file)!=FR_OK);
    fr=f_close(&file);opened=0;
    if(failed||fr!=FR_OK)goto failure;
    if(save_read(slot,&verify_gen,&verify_crc)!=1||verify_gen!=generation||verify_crc!=checksum)goto failure;
    save_slot=(int8_t)slot;save_generation=generation;save_baseline=checksum;
    ++nes_sd_save_writes;status="SAVE OK";return 0;
failure:
    if(opened)(void)f_close(&file);
    error="SD SAVE FAILED - CHECK CARD";status=error;return 1;
}

/* ------------------------------------------------------------------------- */
/* Catalog                                                                   */
/* ------------------------------------------------------------------------- */

static const char *prefs_path(unsigned slot)
{return slot ? PREFS_SLOT1 : PREFS_SLOT0;}

static int prefs_read(unsigned slot, LibraryPrefs *data)
{
    UINT got;
    int valid;
    if (f_open(&file, prefs_path(slot), FA_READ) != FR_OK) return 0;
    valid = f_size(&file) == sizeof(*data) &&
            f_read(&file, data, sizeof(*data), &got) == FR_OK && got == sizeof(*data);
    if (f_close(&file) != FR_OK) return 0;
    return valid && data->magic == 0x3152504eu && !data->reserved &&
           data->favorite_count <= FAVORITE_MAX && data->recent_count <= RECENT_MAX &&
           data->crc == crc32((const uint8_t *)data, offsetof(LibraryPrefs, crc));
}

static void prefs_boot(void)
{
    unsigned slot;
    memset(&prefs, 0, sizeof(prefs));
    prefs_slot = -1;
    for (slot = 0; slot < 2; ++slot) {
        if (prefs_read(slot, &prefs_work) &&
            (prefs_slot < 0 || (int32_t)(prefs_work.generation - prefs.generation) > 0)) {
            prefs = prefs_work;
            prefs_slot = (int)slot;
        }
    }
}

static int prefs_write(void)
{
    const unsigned slot = prefs_slot < 0 ? 0u : (unsigned)(1 - prefs_slot);
    const uint32_t generation = prefs.generation + 1;
    uint32_t checksum;
    UINT wrote;
    int ok;
    prefs_work.magic = 0x3152504eu;
    prefs_work.generation = generation;
    checksum = crc32((const uint8_t *)&prefs_work, offsetof(LibraryPrefs, crc));
    prefs_work.crc = checksum;
    if (f_open(&file, prefs_path(slot), FA_WRITE | FA_CREATE_ALWAYS) != FR_OK) return 0;
    ok = f_write(&file, &prefs_work, sizeof(prefs_work), &wrote) == FR_OK &&
         wrote == sizeof(prefs_work) && f_sync(&file) == FR_OK;
    if (f_close(&file) != FR_OK || !ok) return 0;
    if (!prefs_read(slot, &prefs_work) || prefs_work.generation != generation ||
        prefs_work.crc != checksum) return 0;
    prefs = prefs_work;
    prefs_slot = (int)slot;
    return 1;
}

/* Settings are independent of the ROM catalog and cheap enough to rewrite on
 * every change: one 512-byte sector, no dual slot needed. */
int NesLibrary_LoadSettings(NesLibrarySettings *settings)
{
    uint8_t data[SETTINGS_BYTES];
    UINT got;
    FRESULT fr;
    int ok;
    if(!sd_active||!settings)return 0;
    fr=f_open(&file,SETTINGS_PATH,FA_READ);
    if(fr!=FR_OK)return 0;
    ok=f_size(&file)==SETTINGS_BYTES&&f_read(&file,data,SETTINGS_BYTES,&got)==FR_OK&&
       got==SETTINGS_BYTES;
    fr=f_close(&file);
    if(!ok||fr!=FR_OK)return 0;
    if(data[0]!=SETTINGS_VERSION||data[1]>1||data[2]>100||data[3]>2||
       le32(data+4)!=crc32(data,4))return 0;
    settings->version=data[0];
    settings->landscape=data[1];
    settings->volume=data[2];
    settings->output=data[3];
    ++nes_sd_file_reads;
    return 1;
}
int NesLibrary_SaveSettings(const NesLibrarySettings *settings)
{
    uint8_t data[SETTINGS_BYTES];
    UINT wrote;
    FRESULT fr;
    if(!sd_active||!settings)return -1;
    data[0]=SETTINGS_VERSION;
    data[1]=settings->landscape?1:0;
    data[2]=settings->volume>100?100:settings->volume;
    data[3]=settings->output>2?2:settings->output;
    put32(data+4,crc32(data,4));
    if(f_open(&file,SETTINGS_PATH,FA_WRITE|FA_CREATE_ALWAYS)!=FR_OK)return -1;
    fr=f_write(&file,data,SETTINGS_BYTES,&wrote);
    if(fr==FR_OK&&wrote==SETTINGS_BYTES)fr=f_sync(&file);
    else fr=FR_DISK_ERR;
    if(f_close(&file)!=FR_OK)return -1;
    return fr==FR_OK?0:-1;
}

static uint64_t prefs_key(const char *path)
{
    uint64_t key = UINT64_C(14695981039346656037);
    while (*path) {
        uint8_t c = (uint8_t)*path++;
        if (c >= 'A' && c <= 'Z') c = (uint8_t)(c + ('a' - 'A'));
        key = (key ^ c) * UINT64_C(1099511628211);
    }
    return key;
}

static unsigned prefs_position(const uint64_t *keys, unsigned count, uint64_t key)
{
    unsigned i;
    for (i = 0; i < count; ++i) if (keys[i] == key) break;
    return i;
}

/* Component names may contain UTF-8; only separators and controls are denied. */
static int valid_component(const char *s)
{
    unsigned i,len=(unsigned)strlen(s);
    if(!len||len>NES_IMPORT_NAME_MAX||s[0]=='.')return 0;
    for(i=0;i<len;i++){
        unsigned char c=(unsigned char)s[i];
        if(c<32||c=='/'||c=='\\'||c==':')return 0;
    }
    return 1;
}
static int valid_relpath(const char *s)
{
    const char *component=s,*p=s;
    if(strlen(s)>NES_IMPORT_PATH_MAX)return 0;
    for(;;++p){
        if(!*p||*p=='/'){
            size_t len=(size_t)(p-component);
            if(!len||(len==1&&component[0]=='.')||
               (len==2&&component[0]=='.'&&component[1]=='.'))return 0;
            if(!*p)return 1;
            component=p+1;
        }else if((unsigned char)*p<32||*p=='\\'||*p==':')return 0;
    }
}
static int read_whole(const char *path,uint8_t *dest,uint32_t limit,uint32_t *size)
{
    UINT got;FRESULT fr;uint32_t total=0,bytes;
    if(f_open(&file,path,FA_READ)!=FR_OK){error="SD FILE MISSING";return 0;}
    bytes=(uint32_t)f_size(&file);
    if(!bytes||bytes>limit){(void)f_close(&file);error="SD FILE SIZE ERROR";return 0;}
    while(total<bytes){
        UINT chunk=(UINT)((bytes-total)>16384u?16384u:bytes-total);
        ++nes_sd_file_reads;
        fr=f_read(&file,dest+total,chunk,&got);
        if(fr!=FR_OK||got!=chunk){(void)f_close(&file);error="SD READ ERROR";return 0;}
        total+=got;
    }
    if(f_close(&file)!=FR_OK){error="SD CLOSE ERROR";return 0;}
    *size=total;return 1;
}
static uint32_t snapshot_mix(uint32_t h,const char *path,uint32_t size,uint16_t date,uint16_t time)
{
    unsigned i;uint32_t stamp=((uint32_t)date<<16)|time;
    for(i=0;path[i];i++)h=(h^(uint8_t)path[i])*16777619u;
    h=(h^size)*16777619u;
    h=(h^stamp)*16777619u;
    return h;
}
/* Directories starting with '.' or '_' are opt-out markers; SAVES is ours. */
static int skip_dir(const char *name)
{
    unsigned i;
    if(name[0]=='.'||name[0]=='_')return 1;
    if(strlen(name)==5){
        static const char saves[]="SAVES";
        for(i=0;i<5;i++){
            char c=name[i];if(c>='a'&&c<='z')c=(char)(c-0x20);
            if(c!=saves[i])return 0;
        }
        return 1;
    }
    return 0;
}
/* Walk NES/ and its subdirectories; every ROM file reaches the callback once. */
static void walk_into(unsigned depth,WalkFn fn,void *ctx)
{
    FRESULT fr;
    if(depth>=WALK_DEPTH)return;
    fr=f_opendir(&walk_dir[depth],walk_full[depth]);
    if(fr!=FR_OK){error="SD DIRECTORY ERROR";return;}
    for(;;){
        FILINFO *fno=&walk_info[depth];
        char rel[NES_IMPORT_PATH_MAX+1];uint8_t fds;
        fr=f_readdir(&walk_dir[depth],fno);
        if(fr!=FR_OK){error="SD READ ERROR";break;}
        if(!fno->fname[0])break;
        if(!strcmp(fno->fname,".")||!strcmp(fno->fname,".."))continue;
        if(fno->fattrib&(AM_HID|AM_SYS))continue;
        if(strlen(walk_rel[depth])+strlen(fno->fname)+(walk_rel[depth][0]!=0)>=sizeof(rel))continue;
        snprintf(rel,sizeof(rel),"%s%s%s",walk_rel[depth],walk_rel[depth][0]?"/":"",fno->fname);
        if(fno->fattrib&AM_DIR){
            if(depth+1>=WALK_DEPTH)continue;
            if(!valid_component(fno->fname)||skip_dir(fno->fname))continue;
            strcpy(walk_rel[depth+1],rel);
            snprintf(walk_full[depth+1],sizeof(walk_full[depth+1]),"%s/%s",walk_full[depth],fno->fname);
            walk_into(depth+1,fn,ctx);
            if(error[0])break;
            continue;
        }
        if(!NesImport_Extension(fno->fname,&fds))continue;
        if(!valid_relpath(rel))continue;
        fn(rel,fno,fds,ctx);
        if(error[0])break;
    }
    if(f_closedir(&walk_dir[depth])!=FR_OK&&!error[0])error="SD DIRECTORY ERROR";
}
typedef struct { uint32_t hash; unsigned count; } SnapshotCtx;
static void snapshot_visit(const char *path,const FILINFO *fno,uint8_t fds,void *ctx)
{
    SnapshotCtx *s=(SnapshotCtx*)ctx;
    (void)fds;
    s->hash=snapshot_mix(s->hash,path,(uint32_t)fno->fsize,fno->fdate,fno->ftime);
    s->count++;
}
static int directory_pass(uint32_t *snapshot,unsigned *count)
{
    SnapshotCtx s;s.hash=2166136261u;s.count=0;
    strcpy(walk_rel[0],"");strcpy(walk_full[0],"0:" NES_DIR);
    walk_into(0,snapshot_visit,&s);
    if(error[0])return 0;
    *snapshot=s.hash;*count=s.count;return 1;
}
static int catalog_header(const char *path,uint32_t *count,uint32_t *snapshot)
{
    uint8_t h[CAT_HEADER];UINT got;FRESULT fr;FSIZE_t bytes;
    fr=f_open(&file,path,FA_READ);
    if(fr!=FR_OK)return 0;
    bytes=f_size(&file);
    ++nes_sd_file_reads;
    fr=f_read(&file,h,CAT_HEADER,&got);
    if(f_close(&file)!=FR_OK)return 0;
    if(fr!=FR_OK||got!=CAT_HEADER||memcmp(h,CAT_MAGIC,7))return 0;
    if(le32(h+16)!=CAT_RECORD||le32(h+20)!=CAT_WINDOW)return 0;
    *count=le32(h+8);*snapshot=le32(h+12);
    return *count<=NES_CATALOG_MAX&&bytes==CAT_HEADER+*count*CAT_RECORD;
}
static int catalog_record_ok(const CatalogRecord *rec)
{
    return memchr(rec->path,0,sizeof(rec->path))&&valid_relpath(rec->path)&&
           memchr(rec->label,0,sizeof(rec->label))&&memchr(rec->pinyin,0,sizeof(rec->pinyin));
}
static int catalog_read(unsigned index,CatalogRecord *out)
{
    unsigned first,slots;UINT got;FRESULT fr;
    if(index>=catalog_count)return 0;
    if(window_valid&&index>=window_first&&index<window_first+CAT_WINDOW){
        *out=cat_window[index-window_first];return catalog_record_ok(out);
    }
    first=index-(index%CAT_WINDOW);
    slots=CAT_WINDOW;
    if(first+slots>catalog_count)slots=catalog_count-first;
    if(f_open(&file,catalog_file_path,FA_READ)!=FR_OK)return 0;
    if(f_lseek(&file,CAT_HEADER+first*CAT_RECORD)!=FR_OK){(void)f_close(&file);return 0;}
    ++nes_sd_file_reads;
    fr=f_read(&file,cat_window,slots*CAT_RECORD,&got);
    (void)f_close(&file);
    if(fr!=FR_OK||got!=slots*CAT_RECORD)return 0;
    window_first=first;window_valid=1;
    *out=cat_window[index-first];return catalog_record_ok(out);
}
/* TITLES.DB fingerprint: size, then the first and last 4 KiB. */
static uint32_t rom_fingerprint(const char *path,uint32_t size)
{
    char full[NES_PATH_MAX];uint8_t buf[512],tag[4];uint32_t crc=~0u,left;
    put32(tag,size);crc=crc_step(crc,tag,4);
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",path);
    if(f_open(&file,full,FA_READ)!=FR_OK)return 0;
    left=size<TITLES_CHUNK?size:TITLES_CHUNK;
    while(left){
        UINT chunk=(UINT)(left>sizeof(buf)?sizeof(buf):left),got;
        if(f_read(&file,buf,chunk,&got)!=FR_OK||got!=chunk){(void)f_close(&file);return 0;}
        crc=crc_step(crc,buf,got);left-=got;
    }
    left=size<TITLES_CHUNK?0:(size<TITLES_CHUNK*2?size-TITLES_CHUNK:TITLES_CHUNK);
    if(left&&f_lseek(&file,size-TITLES_CHUNK)!=FR_OK){(void)f_close(&file);return 0;}
    while(left){
        UINT chunk=(UINT)(left>sizeof(buf)?sizeof(buf):left),got;
        if(f_read(&file,buf,chunk,&got)!=FR_OK||got!=chunk){(void)f_close(&file);return 0;}
        crc=crc_step(crc,buf,got);left-=got;
    }
    (void)f_close(&file);
    return ~crc;
}
static const char *titles_lookup(const char *db,uint32_t db_size,uint32_t want,char *out)
{
    const char *line=db,*end=db+db_size;
    if(db_size<8||memcmp(line,"NESDB1",6))return 0;
    while(line<end){
        const char *nl=memchr(line,'\n',(size_t)(end-line));
        const char *tab=memchr(line,'\t',(size_t)((nl?nl:end)-line));
        if(tab&&nl&&(size_t)(tab-line)==8){
            uint32_t value=0;unsigned i;int ok=1;
            for(i=0;i<8;i++){
                char c=tab[-8+i];value<<=4;
                if(c>='0'&&c<='9')value|=(uint32_t)(c-'0');
                else if(c>='a'&&c<='f')value|=(uint32_t)(c-'a'+10);
                else if(c>='A'&&c<='F')value|=(uint32_t)(c-'A'+10);
                else {ok=0;break;}
            }
            if(ok&&value==want){
                unsigned n=0;
                while(tab+1+n<nl&&n<NES_IMPORT_LABEL_MAX){
                    unsigned char c=(unsigned char)tab[1+n];
                    if(c<32||c=='\t')break;
                    out[n++]=(char)c;
                }
                while(n&&out[n-1]==' ')n--;
                out[n]=0;
                return n?out:0;
            }
        }
        if(!nl)break;
        line=nl+1;
    }
    return 0;
}
static const CatalogRecord *old_catalog;
static unsigned old_count;
static MergeSlot *merge_table;
static void merge_build(void)
{
    unsigned i;
    memset(merge_table,0,CAT_HASH_MAX*sizeof(MergeSlot));
    for(i=0;i<old_count;i++){
        unsigned slot=fnv1a(old_catalog[i].path)&(CAT_HASH_MAX-1);
        while(merge_table[slot].used)slot=(slot+1)&(CAT_HASH_MAX-1);
        merge_table[slot].used=1;
        merge_table[slot].hash=fnv1a(old_catalog[i].path);
        merge_table[slot].index=(uint16_t)i;
    }
}
static const CatalogRecord *merge_find(const char *path,uint32_t hash)
{
    unsigned slot=hash&(CAT_HASH_MAX-1),probes=0;
    while(merge_table[slot].used&&probes++<CAT_HASH_MAX){
        if(merge_table[slot].hash==hash){
            const CatalogRecord *rec=&old_catalog[merge_table[slot].index];
            if(!strcmp(rec->path,path))return rec;
        }
        slot=(slot+1)&(CAT_HASH_MAX-1);
    }
    return 0;
}
static void catalog_copy_old(void)
{
    CatalogRecord *sram=(CatalogRecord*)NES_MMC5_ARENA_ADDR;
    uint32_t count,snapshot,bytes;UINT got;unsigned i;
    old_catalog=0;old_count=0;
    for(i=0;i<sizeof(catalog_files)/sizeof(catalog_files[0]);++i){
        unsigned j,kept=0;int read_ok=0;
        if(!catalog_header(catalog_files[i],&count,&snapshot)||!count)continue;
        bytes=count*CAT_RECORD;
        if(f_open(&file,catalog_files[i],FA_READ)!=FR_OK)continue;
        if(f_lseek(&file,CAT_HEADER)==FR_OK){
            ++nes_sd_file_reads;
            read_ok=f_read(&file,sram,bytes,&got)==FR_OK&&got==bytes;
        }
        if(f_close(&file)!=FR_OK||!read_ok)continue;
        for(j=0;j<count;++j){
            if(catalog_record_ok(&sram[j]))sram[kept++]=sram[j];
        }
        old_count=kept;
        if(old_count){old_catalog=sram;return;}
    }
}
static int catalog_write_header(uint32_t count,uint32_t snapshot)
{
    uint8_t h[CAT_HEADER];UINT wrote;
    memset(h,0,sizeof(h));memcpy(h,CAT_MAGIC,7);
    put32(h+8,count);put32(h+12,snapshot);put32(h+16,CAT_RECORD);put32(h+20,CAT_WINDOW);
    return f_lseek(&writer,0)==FR_OK&&f_write(&writer,h,sizeof(h),&wrote)==FR_OK&&wrote==sizeof(h);
}
typedef struct { const uint8_t *db; uint32_t db_size; unsigned written; int ok; } RebuildCtx;
static void rebuild_visit(const char *path,const FILINFO *fno,uint8_t fds,void *ctx)
{
    RebuildCtx *c=(RebuildCtx*)ctx;
    CatalogRecord rec;const CatalogRecord *old=0;uint32_t hash;UINT wrote;
    if(!c->ok||c->written>=NES_CATALOG_MAX)return;
    memset(&rec,0,sizeof(rec));
    strcpy(rec.path,path);
    rec.size=(uint32_t)fno->fsize;rec.stamp=((uint32_t)fno->fdate<<16)|fno->ftime;
    rec.flags=(uint32_t)fds;
    hash=fnv1a(rec.path);
    if(old_count){
        old=merge_find(rec.path,hash);
        if(old&&old->size==rec.size&&old->stamp==rec.stamp){
            memcpy(rec.label,old->label,sizeof(rec.label));
            memcpy(rec.pinyin,old->pinyin,sizeof(rec.pinyin));
        }
        else old=0;
    }
    if(!old){
        const char *title=c->db_size?titles_lookup((const char*)c->db,c->db_size,
            rom_fingerprint(rec.path,rec.size),rec.label):0;
        if(!title){
            const char *base=strrchr(path,'/');
            NesImport_Label(base?base+1:path,rec.label);
        }
    }
    if(f_write(&writer,&rec,sizeof(rec),&wrote)!=FR_OK||wrote!=sizeof(rec)){
        error="SD CATALOG WRITE ERROR";c->ok=0;return;
    }
    c->written++;
}
static int catalog_commit(void)
{
    uint32_t count,snapshot;
    FRESULT fr;
    if(catalog_header(CATALOG_PATH,&count,&snapshot)){
        fr=f_unlink(CATALOG_BACKUP);
        if(fr!=FR_OK&&fr!=FR_NO_FILE)return 0;
        if(f_rename(CATALOG_PATH,CATALOG_BACKUP)!=FR_OK)return 0;
    }else{
        fr=f_unlink(CATALOG_PATH);
        if(fr!=FR_OK&&fr!=FR_NO_FILE)return 0;
    }
    return f_rename(CATALOG_NEW,CATALOG_PATH)==FR_OK;
}

static int catalog_rebuild(uint32_t snapshot)
{
    uint8_t *arena=(uint8_t*)NES_MMC5_ARENA_ADDR;
    uint32_t used=old_count*CAT_RECORD;
    uint32_t merge_bytes=CAT_HASH_MAX*sizeof(MergeSlot);
    uint8_t *db=arena+used;
    uint32_t db_limit=CAT_TEMP_BYTES-merge_bytes-used;
    uint32_t db_size=0;
    UINT wrote;int ok=1;RebuildCtx ctx;
    if(db_limit>TITLES_MAX_BYTES)db_limit=TITLES_MAX_BYTES;
    merge_table=(MergeSlot*)(arena+CAT_TEMP_BYTES-merge_bytes);
    if(f_open(&writer,CATALOG_NEW,FA_WRITE|FA_CREATE_ALWAYS)!=FR_OK){
        error="SD CATALOG WRITE ERROR";return 0;
    }
    {
        uint8_t blank[CAT_HEADER];memset(blank,0,sizeof(blank));
        if(f_write(&writer,blank,sizeof(blank),&wrote)!=FR_OK||wrote!=sizeof(blank))ok=0;
    }
    if(ok&&db_limit>16&&read_whole(TITLES_PATH,db,db_limit,&db_size)){
        ++nes_sd_file_reads;
    }else{
        db_size=0;error="";
    }
    if(ok&&old_count)merge_build();
    ctx.db=db;ctx.db_size=db_size;ctx.written=0;ctx.ok=1;
    if(ok){
        strcpy(walk_rel[0],"");strcpy(walk_full[0],"0:" NES_DIR);
        walk_into(0,rebuild_visit,&ctx);
        ok=ctx.ok&&!error[0];
    }
    if(ok)ok=catalog_write_header(ctx.written,snapshot)&&f_sync(&writer)==FR_OK;
    if(f_close(&writer)!=FR_OK)ok=0;
    if(!ok){error="SD CATALOG WRITE ERROR";return 0;}
    /* The synced NEW file remains a boot candidate if rotation is interrupted. */
    catalog_file_path=catalog_commit()?CATALOG_PATH:CATALOG_NEW;
    catalog_count=ctx.written;window_valid=0;
    return 1;
}
static void compatibility_store(unsigned index, int code, unsigned mapper)
{
    if(code==NES_LIBRARY_COMPAT_UNKNOWN||code==NES_LIBRARY_COMPAT_READ_ERROR)return;
    if(code<-13||code>NES_LIBRARY_COMPAT_HEADER_OK)return;
    compatibility[index]=(uint16_t)(((unsigned)(code>0?1:1-code)<<12)|(mapper&0xfffu));
}

static int compatibility_code(unsigned index)
{
    unsigned encoded=compatibility[index]>>12;
    return encoded>1?1-(int)encoded:(int)encoded;
}

static void compatibility_boot(uint32_t snapshot)
{
    uint8_t *data=(uint8_t*)CAT_SCAN_ADDR;
    const unsigned payload=catalog_count*COMPAT_RECORD;
    UINT got;int valid;unsigned i;
    if(f_open(&file,COMPAT_PATH,FA_READ)!=FR_OK)return;
    valid=f_size(&file)==COMPAT_HEADER+payload&&
          f_read(&file,data,COMPAT_HEADER+payload,&got)==FR_OK&&got==COMPAT_HEADER+payload;
    if(f_close(&file)!=FR_OK||!valid||memcmp(data,COMPAT_MAGIC,7)||data[7]||
       le32(data+8)!=catalog_count||le32(data+12)!=snapshot||
       le32(data+16)!=crc32(data+COMPAT_HEADER,payload))return;
    for(i=0;i<catalog_count;++i){
        const uint8_t *entry=data+COMPAT_HEADER+i*COMPAT_RECORD;
        compatibility_store(i,(int8_t)entry[3],le16c(entry));
    }
}

int NesLibrary_Boot(void)
{
    uint32_t snapshot,cat_snapshot=0,cat_count=0;unsigned count,i;
    SdBspResult sd_result;FRESULT mount_result;
    sd_active=0;catalog_count=0;arena_menu=1;cached_cover=-1;error="";save_active=0;input_profile=0;
    nes_fds_bios_override=0;nes_fds_bios_override_size=0;
    window_valid=0;status="";sd_status[0]=0;overflow_count=0;
    view_filter=NES_LIBRARY_FILTER_ALL;
    search_failed=0;
    filter_next=0;filter_retry=0;
    catalog_file_path=CATALOG_PATH;
    memset(compatibility,0,sizeof(compatibility));
    NesLibrary_ClearView();
    CjkFont_Invalidate();
    sd_result=SDIO_Config();
    if(sd_result!=SD_BSP_OK){
        snprintf(sd_status,sizeof(sd_status),"SD %s ERROR %08lX",sd_result==SD_BSP_ERR_BUS?"BUS":"INIT",(unsigned long)sd_last_error);
        status=sd_status;return -1;
    }
    mount_result=f_mount(&fs,"0:",1);
    if(mount_result!=FR_OK){status=mount_result==FR_NO_FILESYSTEM?"SD FORMAT ERROR - USE FAT32":"SD READ ERROR - RESTART";return -2;}
    load_card_fds_bios();
    if(!directory_pass(&snapshot,&count)){status=error[0]?error:"SD READ ERROR";return -3;}
    if(!count){status="NO GAMES ON SD - BUILT-IN GAME";return -3;}
    if(count>NES_CATALOG_MAX){overflow_count=count-NES_CATALOG_MAX;count=NES_CATALOG_MAX;}
    for(i=0;i<sizeof(catalog_files)/sizeof(catalog_files[0]);++i){
        if(catalog_header(catalog_files[i],&cat_count,&cat_snapshot)&&
           cat_snapshot==snapshot&&cat_count==count){
            catalog_count=cat_count;
            catalog_file_path=catalog_files[i];
            break;
        }
    }
    if(!catalog_count){
        catalog_copy_old();
        if(!catalog_rebuild(snapshot)){status=error;return -3;}
        if(!catalog_count){status="NO SUPPORTED GAMES";return -3;}
    }
    compatibility_boot(snapshot);
    prefs_boot();
    if(overflow_count){
        snprintf(sd_status,sizeof(sd_status),"SD LIMIT %u - %u OMITTED",NES_CATALOG_MAX,overflow_count);
        status=sd_status;
    }
    sd_active=1;error="";
    return 0;
}
unsigned NesLibrary_Count(void)
{
    if(view_active)return view_count;
    return sd_active?catalog_count:nes_rom_image_count;
}
unsigned NesLibrary_ViewActive(void){return view_active;}
unsigned NesLibrary_Filter(void){return view_filter;}
unsigned NesLibrary_OverflowCount(void){return overflow_count;}
int NesLibrary_SearchFailed(void){return search_failed;}
static int contains(const char *hay,const char *needle)
{
    unsigned i,j;
    if(!needle[0])return 1;
    for(i=0;hay[i];i++){
        for(j=0;needle[j];j++){
            char a=hay[i+j],b=needle[j];
            if(!a)return 0;
            if(a>='A'&&a<='Z')a=(char)(a+0x20);
            if(b>='A'&&b<='Z')b=(char)(b+0x20);
            if(a!=b)break;
        }
        if(!needle[j])return 1;
    }
    return 0;
}

static int probe_rom(const char *path, NesImportInfo *info, int static_checks);

static unsigned view_catalog_index(unsigned index)
{
    if(index>=NesLibrary_Count())return UINT16_MAX;
    return view_active?view[index]:index;
}

static int check_compatibility(unsigned index, const CatalogRecord *rec)
{
    NesImportInfo info;
    int code=compatibility_code(index);
    if(code!=NES_LIBRARY_COMPAT_UNKNOWN)return code;
    code=probe_rom(rec->path,&info,1);
    if(code==NES_IMPORT_OK)code=NES_LIBRARY_COMPAT_HEADER_OK;
    compatibility_store(index,code,info.mapper);
    return code;
}

int NesLibrary_Compatibility(unsigned index, int probe, unsigned *mapper)
{
    CatalogRecord rec;
    int code=NES_LIBRARY_COMPAT_UNKNOWN;
    if(mapper)*mapper=UINT16_MAX;
    index=view_catalog_index(index);
    if(index==UINT16_MAX)return code;
    if(!sd_active){
        if(mapper)*mapper=nes_rom_images[index].mapper;
        return NES_LIBRARY_COMPAT_HEADER_OK;
    }
    code=compatibility_code(index);
    if(probe&&code==NES_LIBRARY_COMPAT_UNKNOWN){
        if(!catalog_read(index,&rec))return NES_LIBRARY_COMPAT_READ_ERROR;
        code=check_compatibility(index,&rec);
    }
    if(mapper&&code!=NES_LIBRARY_COMPAT_UNKNOWN&&code!=NES_IMPORT_BAD_HEADER&&
       code!=NES_LIBRARY_COMPAT_READ_ERROR)*mapper=compatibility[index]&0xfffu;
    return code;
}

static int compatibility_filter(void)
{return view_filter==NES_LIBRARY_FILTER_COMPATIBLE||view_filter==NES_LIBRARY_FILTER_UNSUPPORTED;}

static int build_view(void)
{
    CatalogRecord one;
    CatalogRecord *batch=arena_menu?(CatalogRecord*)CAT_SCAN_ADDR:&one;
    const unsigned batch_capacity=arena_menu?CAT_SCAN_RECORDS:1u;
    const uint64_t *keys=0;
    unsigned keys_count=0;
    uint16_t ranked[FAVORITE_MAX];
    unsigned i,j;
    int ok;
    view_count=0;
    view_active=view_filter!=NES_LIBRARY_FILTER_ALL||view_query[0];
    if(!view_active)return 1;
    if(!sd_active){
        if(view_filter!=NES_LIBRARY_FILTER_ALL&&view_filter!=NES_LIBRARY_FILTER_COMPATIBLE)return 1;
        for(i=0;i<nes_rom_image_count&&i<NES_CATALOG_MAX;++i){
            const NesRomImage *entry=&nes_rom_images[i];
            if(contains(entry->label,view_query)||contains(entry->file,view_query))view[view_count++]=(uint16_t)i;
        }
        return 1;
    }
    if(view_filter==NES_LIBRARY_FILTER_FAVORITES){keys=prefs.favorites;keys_count=prefs.favorite_count;}
    if(view_filter==NES_LIBRARY_FILTER_RECENT){keys=prefs.recent;keys_count=prefs.recent_count;}
    if(keys&&!keys_count)return 1;
    for(i=0;i<keys_count;++i)ranked[i]=UINT16_MAX;

    /* Search every untouched UTF-8 field, one sequential file pass. SEARCH.IDX
     * v1 truncates aliases and may silently omit both full and partial hits. */
    if(f_open(&writer,catalog_file_path,FA_READ)!=FR_OK)return 0;
    ok=f_lseek(&writer,CAT_HEADER)==FR_OK;
    for(i=0;i<catalog_count&&ok;i+=batch_capacity){
        unsigned n=catalog_count-i;
        UINT got,bytes;
        if(n>batch_capacity)n=batch_capacity;
        bytes=(UINT)(n*sizeof(*batch));
        ++nes_sd_file_reads;
        ok=f_read(&writer,batch,bytes,&got)==FR_OK&&got==bytes;
        if(!ok)break;
        for(j=0;j<n;++j){
            const CatalogRecord *rec=&batch[j];
            const unsigned index=i+j;
            int code;
            if(!catalog_record_ok(rec)){ok=0;break;}
            if(!contains(rec->label,view_query)&&!contains(rec->path,view_query)&&
               !contains(rec->pinyin,view_query))continue;
            if(keys){
                unsigned rank=prefs_position(keys,keys_count,prefs_key(rec->path));
                if(rank<keys_count)ranked[rank]=(uint16_t)index;
                continue;
            }
            if(compatibility_filter()){
                code=compatibility_code(index);
                if(view_filter==NES_LIBRARY_FILTER_COMPATIBLE&&code!=NES_LIBRARY_COMPAT_HEADER_OK)continue;
                if(view_filter==NES_LIBRARY_FILTER_UNSUPPORTED&&(code>=0||code==NES_LIBRARY_COMPAT_READ_ERROR))continue;
            }
            view[view_count++]=(uint16_t)index;
        }
    }
    if(f_close(&writer)!=FR_OK||!ok){view_count=0;return 0;}
    for(i=0;i<keys_count;++i)if(ranked[i]!=UINT16_MAX)view[view_count++]=ranked[i];
    return 1;
}

void NesLibrary_ClearView(void)
{
    view_query[0]=0;
    search_failed=0;
    (void)build_view();
}

unsigned NesLibrary_SetFilter(unsigned filter)
{
    if(filter>NES_LIBRARY_FILTER_RECENT)return NesLibrary_Count();
    view_filter=filter;
    filter_next=0;filter_retry=0;search_failed=0;
    while(filter_next<catalog_count&&compatibility_code(filter_next)!=NES_LIBRARY_COMPAT_UNKNOWN)++filter_next;
    if(!NesLibrary_FilterPending())search_failed=(uint8_t)!build_view();
    else{view_count=0;view_active=1;}
    return NesLibrary_Count();
}

unsigned NesLibrary_FilterPending(void)
{return sd_active&&compatibility_filter()?catalog_count-filter_next:0;}

void NesLibrary_AdvanceFilter(void)
{
    unsigned work;
    if(!NesLibrary_FilterPending())return;
    for(work=0;work<2&&filter_next<catalog_count;++work){
        CatalogRecord rec;
        int code;
        while(filter_next<catalog_count&&compatibility_code(filter_next)!=NES_LIBRARY_COMPAT_UNKNOWN)++filter_next;
        if(filter_next==catalog_count)break;
        if(!catalog_read(filter_next,&rec)){
            if(filter_retry++==0)return;
            search_failed=1;
            filter_next=catalog_count;
            break;
        }
        code=check_compatibility(filter_next,&rec);
        if(code==NES_LIBRARY_COMPAT_READ_ERROR){
            if(filter_retry++==0)return;
            search_failed=1;
        }
        ++filter_next;
        filter_retry=0;
    }
    while(filter_next<catalog_count&&compatibility_code(filter_next)!=NES_LIBRARY_COMPAT_UNKNOWN)++filter_next;
    if(!NesLibrary_FilterPending()&&!build_view())search_failed=1;
}

unsigned NesLibrary_Search(const char *needle)
{
    int ok;
    if(!needle||!needle[0]){NesLibrary_ClearView();return 0;}
    snprintf(view_query,sizeof(view_query),"%s",needle);
    ok=build_view();
    search_failed=(uint8_t)!ok;
    if(view_count)return view_count;
    NesLibrary_ClearView();
    search_failed=(uint8_t)!ok;
    return 0;
}

static int game_key(unsigned index, uint64_t *key)
{
    CatalogRecord rec;
    index=view_catalog_index(index);
    if(!sd_active||index==UINT16_MAX||!catalog_read(index,&rec))return 0;
    *key=prefs_key(rec.path);
    return 1;
}

int NesLibrary_IsFavorite(unsigned index)
{
    uint64_t key;
    return prefs.favorite_count&&game_key(index,&key)&&
           prefs_position(prefs.favorites,prefs.favorite_count,key)<prefs.favorite_count;
}

int NesLibrary_ToggleFavorite(unsigned index)
{
    uint64_t key;
    unsigned pos;
    int added;
    if(!game_key(index,&key))return -1;
    prefs_work=prefs;
    pos=prefs_position(prefs.favorites,prefs.favorite_count,key);
    added=pos==prefs.favorite_count;
    if(added){
        if(pos==FAVORITE_MAX)return -2;
        prefs_work.favorites[prefs_work.favorite_count++]=key;
    }else{
        --prefs_work.favorite_count;
        memmove(&prefs_work.favorites[pos],&prefs_work.favorites[pos+1],
                (prefs_work.favorite_count-pos)*sizeof(key));
    }
    if(!prefs_write())return -1;
    if(view_filter==NES_LIBRARY_FILTER_FAVORITES)(void)build_view();
    return added;
}

int NesLibrary_RecordPlayed(unsigned index)
{
    uint64_t key;
    unsigned pos;
    if(!sd_active)return 0;
    if(!game_key(index,&key))return -1;
    pos=prefs_position(prefs.recent,prefs.recent_count,key);
    if(prefs.recent_count&&pos==0)return 0;
    prefs_work=prefs;
    if(pos==prefs.recent_count&&pos<RECENT_MAX)++prefs_work.recent_count;
    if(pos==RECENT_MAX)--pos;
    memmove(&prefs_work.recent[1],prefs_work.recent,pos*sizeof(key));
    prefs_work.recent[0]=key;
    return prefs_write()?0:-1;
}

const NesRomImage *NesLibrary_Game(unsigned index)
{
    CatalogRecord rec;
    unsigned catalog_index=view_catalog_index(index);
    if(catalog_index==UINT16_MAX)return 0;
    if(!sd_active)return &nes_rom_images[catalog_index];
    /* A card pulled mid-session must not take the menu down with it. */
    if(!catalog_read(catalog_index,&rec)){
        memset(&rec,0,sizeof(rec));
        strcpy(rec.label,"NO DATA");
    }
    memcpy(scratch_path,rec.path,sizeof(rec.path));
    memcpy(scratch_label,rec.label,sizeof(rec.label));
    scratch_path[sizeof(scratch_path)-1]=0;
    scratch_label[sizeof(scratch_label)-1]=0;
    scratch.label=scratch_label;scratch.file=scratch_path;
    scratch.data=0;scratch.size=rec.size;scratch.mapper=0;
    scratch_index=catalog_index;
    return &scratch;
}
const char *NesLibrary_Status(void){return status;}
const char *NesLibrary_Error(void){return error;}
void NesLibrary_EnterMenu(void){arena_menu=1;cached_cover=-1;}
static int cover_path(const char *path,char *out,unsigned cap)
{
    const char *dot=strrchr(path,'.');
    unsigned len=dot?(unsigned)(dot-path):(unsigned)strlen(path);
    if(len+5>cap)return 0;
    memcpy(out,path,len);memcpy(out+len,".COV",5);
    return 1;
}
int NesLibrary_CoverExists(const char *rom_path)
{
    char cover[NES_IMPORT_PATH_MAX+8];
    char full[NES_PATH_MAX];
    FIL file;
    if(!sd_active)return 1; /* No card: runtime capture is a no-op. */
    if(!rom_path||!rom_path[0]||!cover_path(rom_path,cover,sizeof(cover)))return 1;
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",cover);
    if(f_open(&file,full,FA_READ)!=FR_OK)return 0;
    f_close(&file);
    return 1;
}
int NesLibrary_SaveCover(const char *rom_path,const uint8_t *pixels,const uint16_t *palette)
{
    static const uint8_t zeros[384]={0};
    char cover[NES_IMPORT_PATH_MAX+8];
    char full[NES_PATH_MAX];
    uint8_t header[24];
    uint32_t crc=~0u;
    unsigned i;
    UINT wrote;
    FIL file;
    int failed=0;
    if(!sd_active||!pixels||!palette)return -1;
    if(!cover_path(rom_path,cover,sizeof(cover)))return -1;
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",cover);
    if(f_open(&file,full,FA_READ)==FR_OK){f_close(&file);return 1;}
    /* 256 palette slots: the first 64 are the live NES palette, the rest
     * stay black. Pixels are already 0..63 indices, so bits=8 is a direct
     * copy with no quantization. */
    crc=crc_step(crc,(const uint8_t*)palette,64u*2u);
    crc=crc_step(crc,zeros,sizeof(zeros));
    for(i=0;i<240u;i++)crc=crc_step(crc,pixels+i*256u,256u);
    memset(header,0,sizeof(header));
    memcpy(header,"NCV1",4);
    header[5]=1;    /* width 256 low byte */
    header[6]=240;  /* height 240 low byte */
    header[8]=8;    /* 8-bit indices, count 256 */
    header[11]=1;
    put32(header+12,512u);
    put32(header+16,240u*256u);
    put32(header+20,~crc);
    if(f_open(&file,full,FA_WRITE|FA_CREATE_ALWAYS)!=FR_OK)return -2;
    if(f_write(&file,header,sizeof(header),&wrote)!=FR_OK||wrote!=sizeof(header))failed=1;
    if(!failed&&(f_write(&file,palette,64u*2u,&wrote)!=FR_OK||wrote!=64u*2u))failed=1;
    if(!failed&&(f_write(&file,zeros,sizeof(zeros),&wrote)!=FR_OK||wrote!=sizeof(zeros)))failed=1;
    for(i=0;!failed&&i<240u;i++)
        if(f_write(&file,pixels+i*256u,256u,&wrote)!=FR_OK||wrote!=256u)failed=1;
    if(!failed&&f_sync(&file)!=FR_OK)failed=1;
    if(f_close(&file)!=FR_OK)failed=1;
    if(failed){f_unlink(full);return -3;}
    return 0;
}
const NesPoster *NesLibrary_Poster(const NesRomImage *game)
{
    uint32_t bytes,pal_bytes,pixel_bytes,count,pixels;uint8_t bits,flags;
    uint8_t *p=(uint8_t*)NES_ROM_ARENA_ADDR;char cover[NES_IMPORT_PATH_MAX+8];
    char path[NES_PATH_MAX];
    unsigned i;
    if(!sd_active)return game?NesPoster_Find(game->file):0;
    if(!arena_menu||game!=&scratch)return 0; /* Never overwrite the live ROM. */
    i=scratch_index;
    if(cached_cover==(int)i)return &poster;
    cached_cover=-1;
    if(!cover_path(scratch_path,cover,sizeof(cover)))return 0;
    snprintf(path,sizeof(path),"0:" NES_DIR "/%s",cover);
    if(!read_whole(path,p,COVER_MAX_BYTES,&bytes)){error="";return 0;}
    if(bytes<24 || memcmp(p,"NCV1",4))return 0;
    bits=p[8];flags=p[9];count=(uint32_t)p[10]|((uint32_t)p[11]<<8);
    pal_bytes=le32(p+12);pixel_bytes=le32(p+16);pixels=(uint32_t)le16c(p+4)*(uint32_t)le16c(p+6);
    if(!le16c(p+4)||le16c(p+4)>512||!le16c(p+6)||le16c(p+6)>480||
       (bits!=4&&bits!=8)||flags>1||count!=(1u<<bits)||pal_bytes!=count*2||
       pixel_bytes!=(pixels*bits+7)/8||bytes!=24+pal_bytes+pixel_bytes||crc32(p+24,bytes-24)!=le32(p+20))return 0;
    memset(&poster,0,sizeof(poster));poster.file=scratch_path;
    poster.width=le16c(p+4);poster.height=le16c(p+6);poster.pixel_bits=bits;poster.full_art=flags;
    poster.palette=(const uint16_t*)(p+24);poster.pixels=p+24+pal_bytes;
    poster.background=0x0865;poster.ink=0xffdf;cached_cover=(int)i;return &poster;
}
/* Picking an arena only needs the header. Library classification also checks
 * the reset vector and resolves known ambiguous Mapper 16 dumps. */
static int probe_rom(const char *path,NesImportInfo *info,int static_checks)
{
    char full[NES_PATH_MAX];uint8_t hdr[16]={0};UINT got;uint32_t size;int code;
    memset(info,0,sizeof(*info));info->mapper=NES_IMPORT_UNKNOWN_MAPPER;
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",path);
    if(f_open(&file,full,FA_READ)!=FR_OK)return NES_LIBRARY_COMPAT_READ_ERROR;
    size=(uint32_t)f_size(&file);
    ++nes_sd_file_reads;
    if(f_read(&file,hdr,sizeof(hdr),&got)!=FR_OK||(size>=sizeof(hdr)&&got!=sizeof(hdr))){
        code=NES_LIBRARY_COMPAT_READ_ERROR;
    }else{
        code=NesImport_Header(hdr,size,info);
    }
    if(static_checks&&code==NES_IMPORT_OK&&!info->fds){
        uint8_t vec[2];
        if(f_lseek(&file,NesImport_VectorOffset(info->header))!=FR_OK||
           f_read(&file,vec,sizeof(vec),&got)!=FR_OK||got!=sizeof(vec))code=NES_LIBRARY_COMPAT_READ_ERROR;
        else if(!NesImport_VectorOk(vec))code=NES_IMPORT_BAD_VECTOR;
    }
    if(static_checks&&code==NES_IMPORT_OK&&info->mapper==16&&!info->submapper){
        uint8_t bytes[512];
        uint32_t left=size-sizeof(hdr),crc=~0u;
        if(f_lseek(&file,sizeof(hdr))!=FR_OK)code=NES_LIBRARY_COMPAT_READ_ERROR;
        while(left&&code==NES_IMPORT_OK){
            UINT n=left>sizeof(bytes)?sizeof(bytes):(UINT)left;
            if(f_read(&file,bytes,n,&got)!=FR_OK||got!=n)code=NES_LIBRARY_COMPAT_READ_ERROR;
            else{crc=crc_step(crc,bytes,n);left-=n;}
        }
        if(code==NES_IMPORT_OK&&!NesImport_Mapper16Submapper(~crc))code=NES_IMPORT_BAD_BOARD;
    }
    if(f_close(&file)!=FR_OK)return NES_LIBRARY_COMPAT_READ_ERROR;
    return code;
}
int NesLibrary_Load(unsigned index)
{
    CatalogRecord rec;NesImportInfo info;uint8_t *arena;char full[NES_PATH_MAX];
    uint32_t bytes,crc;int result;
    error="";
    if(NesLibrary_Save())return 10;
    index=view_catalog_index(index);
    if(index==UINT16_MAX){error="NO GAME SELECTED";return 10;}
    if(!sd_active){
        const NesRomImage *g=&nes_rom_images[index];
        arena_menu=0;cached_cover=-1;
        result=Nes_Load(g->data,g->size);
        if(result)return result;
        save_active=0;
        return save_restore(crc32(g->data,g->size),g->size)?10:0;
    }
    if(!catalog_read(index,&rec)){error="NO GAME SELECTED";return 10;}
    result=probe_rom(rec.path,&info,0);
    if(result!=NES_IMPORT_OK){
        compatibility_store(index,result,info.mapper);
        if(result==NES_LIBRARY_COMPAT_READ_ERROR)error="SD ROM MISSING OR UNREADABLE";
        else{NesImport_FormatReason(result,&info,rom_error,sizeof(rom_error));error=rom_error;}
        return 10;
    }
    arena=(uint8_t*)(info.mapper==5?NES_MMC5_ARENA_ADDR:
                     (info.chr_large?NES_LARGE_ARENA_ADDR:NES_ROM_ARENA_ADDR));
    CjkFont_Invalidate();   /* the ROM is about to own the arena */
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",rec.path);
    if(!read_whole(full,arena,info.mapper==5?NES_MMC5_ARENA_BYTES:
                   (info.chr_large?NES_LARGE_ARENA_BYTES:NES_ROM_ARENA_BYTES),&bytes))return 10;
    if(bytes!=info.size){error="SD FILE SIZE ERROR";return 10;}
    crc=crc32(arena,bytes);
    arena_menu=0;cached_cover=-1;
    result=Nes_Load(arena,bytes);
    if(result){
        int reject=result==11?NES_IMPORT_BAD_BOARD:(result==5?NES_IMPORT_BAD_VECTOR:0);
        if(reject){
            compatibility_store(index,reject,info.mapper);
            NesImport_FormatReason(reject,&info,rom_error,sizeof(rom_error));error=rom_error;
        }
        return result;
    }
    compatibility_store(index,NES_LIBRARY_COMPAT_HEADER_OK,info.mapper);
    /* Restrict this adaptation to the verified Japan image, not all MMC5
     * games. Use the on-card CRC, independent of menu labels. */
    input_profile=(uint8_t)(info.mapper==5 && bytes==786448u && crc==0x60579af2u);
    save_active=0;
    return save_restore(crc,bytes)?10:0;
}
