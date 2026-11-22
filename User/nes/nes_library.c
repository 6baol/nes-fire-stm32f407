#include <stdio.h>
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
 * Paths are UTF-8 relative to NES/ and may point into subdirectories. */
#define NES_DIR "/NES"
#define CATALOG_PATH "0:/NES/CATALOG.IDX"
#define SEARCH_PATH "0:/NES/SEARCH.IDX"
#define SEARCH_MAGIC "NESIDX1"
#define SEARCH_KEY 24u
#define SEARCH_MAX_BYTES (120u * 1024u)
#define TITLES_PATH "0:/NES/TITLES.DB"
#define NES_PATH_MAX (NES_IMPORT_PATH_MAX + 16)
#define CAT_MAGIC "NESCAT5"
#define CAT_HEADER 32u
#define CAT_RECORD 312u
#define CAT_WINDOW 4u
#define CAT_HASH_MAX 2048u
#define PINYIN_MAX 39
#define WALK_DEPTH 4u
#define TITLES_MAX_BYTES (320u * 1024u)
#define TITLES_CHUNK 4096u
#define COVER_MAX_BYTES (128u * 1024u)
#define SAVE_BYTES 8192u
#define SAVE_HEADER 28u

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
/* A search result is a list of catalog indices; Count/Game/Load then see only
 * those entries. 2048 x 2 bytes in internal RAM. */
#define VIEW_MAX 2048u
static uint16_t view[VIEW_MAX];
static unsigned view_count;
static uint8_t view_active;
static uint8_t sd_active,arena_menu=1;
static uint8_t input_profile;
unsigned NesLibrary_InputProfile(void){return input_profile;}
static int cached_cover=-1;
static NesPoster poster;
static const char *status="",*error="";
static char sd_status[48];
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
    unsigned slot;uint32_t generation,checksum;int result,bad=0;
    save_active=0;save_slot=-1;save_generation=0;
    if(!sd_active||MapperNo==20||!(RomHeader->flags_1&2))return 0;
    save_key=key;save_rom_size=rom_size;
    save_baseline=crc32(NES_SRAM,SAVE_BYTES);
    for(slot=0;slot<2;slot++) {
        result=save_read(slot,&generation,&checksum);
        if(result==-2){error="SD SAVE READ ERROR";return 1;}
        if(result<0){bad=1;continue;}
        if(result==1&&(save_slot<0||(int32_t)(generation-save_generation)>0)) {
            memcpy(NES_SRAM,save_buffer,SAVE_BYTES);save_slot=(int8_t)slot;
            save_generation=generation;save_baseline=checksum;
        }
    }
    if(save_slot<0&&bad){error="SD SAVE INVALID - CHECK SAVES";return 1;}
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
    unsigned i,len=(unsigned)strlen(s);
    if(!len||len>NES_IMPORT_PATH_MAX)return 0;
    if(s[0]=='/'||strstr(s,".."))return 0;
    for(i=0;i<len;i++){
        unsigned char c=(unsigned char)s[i];
        if(c<32||c=='\\'||c==':')return 0;
    }
    return 1;
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
    if(fr!=FR_OK){if(!depth)error="SD DIRECTORY ERROR";return;}
    for(;;){
        FILINFO *fno=&walk_info[depth];
        char rel[NES_IMPORT_PATH_MAX+1];uint8_t fds;
        fr=f_readdir(&walk_dir[depth],fno);
        if(fr!=FR_OK){if(!depth)error="SD READ ERROR";break;}
        if(!fno->fname[0])break;
        if(!strcmp(fno->fname,".")||!strcmp(fno->fname,".."))continue;
        if(fno->fattrib&(AM_HID|AM_SYS))continue;
        if(strlen(walk_rel[depth])+strlen(fno->fname)+2>sizeof(rel))continue;
        snprintf(rel,sizeof(rel),"%s%s%s",walk_rel[depth],walk_rel[depth][0]?"/":"",fno->fname);
        if(fno->fattrib&AM_DIR){
            if(depth+1>=WALK_DEPTH)continue;
            if(!valid_component(fno->fname)||skip_dir(fno->fname))continue;
            strcpy(walk_rel[depth+1],rel);
            snprintf(walk_full[depth+1],sizeof(walk_full[depth+1]),"%s/%s",walk_full[depth],fno->fname);
            walk_into(depth+1,fn,ctx);
            continue;
        }
        if(!NesImport_Extension(fno->fname,&fds))continue;
        if(!valid_relpath(rel))continue;
        fn(rel,fno,fds,ctx);
    }
    (void)f_closedir(&walk_dir[depth]);
}
typedef struct { uint32_t hash; unsigned count; } SnapshotCtx;
static void snapshot_visit(const char *path,const FILINFO *fno,uint8_t fds,void *ctx)
{
    SnapshotCtx *s=(SnapshotCtx*)ctx;
    (void)fds;
    s->hash=snapshot_mix(s->hash,path,(uint32_t)fno->fsize,fno->fdate,fno->ftime);
    if(s->count<NES_CATALOG_MAX)s->count++;
}
static int directory_pass(uint32_t *snapshot,unsigned *count)
{
    SnapshotCtx s;s.hash=2166136261u;s.count=0;
    strcpy(walk_rel[0],"");strcpy(walk_full[0],"0:" NES_DIR);
    walk_into(0,snapshot_visit,&s);
    if(error[0])return 0;
    *snapshot=s.hash;*count=s.count;return 1;
}
static int catalog_header(uint32_t *count,uint32_t *snapshot)
{
    uint8_t h[CAT_HEADER];UINT got;FRESULT fr;
    fr=f_open(&file,CATALOG_PATH,FA_READ);
    if(fr!=FR_OK)return 0;
    ++nes_sd_file_reads;
    fr=f_read(&file,h,CAT_HEADER,&got);
    (void)f_close(&file);
    if(fr!=FR_OK||got!=CAT_HEADER||memcmp(h,CAT_MAGIC,7))return 0;
    if(le32(h+16)!=CAT_RECORD||le32(h+20)!=CAT_WINDOW)return 0;
    *count=le32(h+8);*snapshot=le32(h+12);
    return *count<=NES_CATALOG_MAX;
}
static int catalog_read(unsigned index,CatalogRecord *out)
{
    unsigned first,slots;UINT got;FRESULT fr;
    if(index>=catalog_count)return 0;
    if(window_valid&&index>=window_first&&index<window_first+CAT_WINDOW){
        *out=cat_window[index-window_first];return 1;
    }
    first=index-(index%CAT_WINDOW);
    slots=CAT_WINDOW;
    if(first+slots>catalog_count)slots=catalog_count-first;
    if(f_open(&file,CATALOG_PATH,FA_READ)!=FR_OK)return 0;
    if(f_lseek(&file,CAT_HEADER+first*CAT_RECORD)!=FR_OK){(void)f_close(&file);return 0;}
    ++nes_sd_file_reads;
    fr=f_read(&file,cat_window,slots*CAT_RECORD,&got);
    (void)f_close(&file);
    if(fr!=FR_OK||got!=slots*CAT_RECORD)return 0;
    window_first=first;window_valid=1;
    *out=cat_window[index-first];return 1;
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
    CatalogRecord *sram=(CatalogRecord*)NES_ROM_ARENA_ADDR;
    uint32_t count,snapshot,bytes;UINT got;
    old_catalog=0;old_count=0;
    if(!catalog_header(&count,&snapshot)||!count)return;
    bytes=count*CAT_RECORD;
    if(bytes>NES_ROM_ARENA_BYTES-CAT_HASH_MAX*sizeof(MergeSlot)-0x10000u)return;
    if(f_open(&file,CATALOG_PATH,FA_READ)!=FR_OK)return;
    if(f_lseek(&file,CAT_HEADER)!=FR_OK){(void)f_close(&file);return;}
    ++nes_sd_file_reads;
    if(f_read(&file,sram,bytes,&got)!=FR_OK||got!=bytes){(void)f_close(&file);return;}
    (void)f_close(&file);
    old_catalog=sram;old_count=count;
}
static void catalog_write_header(uint32_t count,uint32_t snapshot)
{
    uint8_t h[CAT_HEADER];UINT wrote;
    memset(h,0,sizeof(h));memcpy(h,CAT_MAGIC,7);
    put32(h+8,count);put32(h+12,snapshot);put32(h+16,CAT_RECORD);put32(h+20,CAT_WINDOW);
    (void)f_lseek(&writer,0);
    (void)f_write(&writer,h,sizeof(h),&wrote);
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
static int catalog_rebuild(uint32_t snapshot,unsigned count)
{
    uint8_t *arena=(uint8_t*)NES_ROM_ARENA_ADDR;
    uint32_t used=old_count*CAT_RECORD;
    uint32_t merge_bytes=CAT_HASH_MAX*sizeof(MergeSlot);
    uint8_t *db=arena+used;
    uint32_t db_limit=NES_ROM_ARENA_BYTES-merge_bytes-used-0x10000u;
    uint32_t db_size=0;
    UINT wrote;int ok=1;RebuildCtx ctx;
    if(db_limit>TITLES_MAX_BYTES)db_limit=TITLES_MAX_BYTES;
    merge_table=(MergeSlot*)(arena+NES_ROM_ARENA_BYTES-merge_bytes);
    if(f_open(&writer,CATALOG_PATH,FA_WRITE|FA_CREATE_ALWAYS)!=FR_OK){
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
    if(ok){
        catalog_write_header(ctx.written,snapshot);
        if(f_sync(&writer)!=FR_OK)ok=0;
    }
    if(f_close(&writer)!=FR_OK)ok=0;
    if(!ok){error="SD CATALOG WRITE ERROR";return 0;}
    catalog_count=ctx.written;window_valid=0;
    (void)f_unlink(SEARCH_PATH);   /* compact index no longer matches */
    (void)count;
    return 1;
}
int NesLibrary_Boot(void)
{
    uint32_t snapshot,cat_snapshot=0;unsigned count,cat_count=0;
    SdBspResult sd_result;FRESULT mount_result;
    sd_active=0;catalog_count=0;arena_menu=1;cached_cover=-1;error="";save_active=0;input_profile=0;
    window_valid=0;status="";sd_status[0]=0;
    NesLibrary_ClearView();
    CjkFont_Invalidate();
    sd_result=SDIO_Config();
    if(sd_result!=SD_BSP_OK){
        snprintf(sd_status,sizeof(sd_status),"SD %s ERROR %08lX",sd_result==SD_BSP_ERR_BUS?"BUS":"INIT",(unsigned long)sd_last_error);
        status=sd_status;return -1;
    }
    mount_result=f_mount(&fs,"0:",1);
    if(mount_result!=FR_OK){status=mount_result==FR_NO_FILESYSTEM?"SD FORMAT ERROR - USE FAT32":"SD READ ERROR - RESTART";return -2;}
    if(!directory_pass(&snapshot,&count)){status=error[0]?error:"SD READ ERROR";return -3;}
    if(!count){status="NO GAMES ON SD - BUILT-IN GAME";return -3;}
    if(catalog_header(&cat_count,&cat_snapshot)&&cat_snapshot==snapshot&&cat_count==count){
        catalog_count=cat_count;
    }else{
        catalog_copy_old();
        if(!catalog_rebuild(snapshot,count))return -3;
        if(!catalog_count){status="NO SUPPORTED GAMES";return -3;}
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
void NesLibrary_ClearView(void){view_active=0;view_count=0;window_valid=0;}
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
unsigned NesLibrary_Search(const char *needle)
{
    unsigned i;
    CatalogRecord rec;
    if(!sd_active||!needle||!needle[0]){NesLibrary_ClearView();return 0;}
    view_count=0;view_active=0;
    /* Fast path: tools/make_search_index.py writes compact lowercase keys so a
     * query reads ~40 KiB instead of the whole 486 KiB catalog. */
    {
        uint8_t *buf=(uint8_t*)NES_ROM_ARENA_ADDR;
        uint32_t bytes=0,count;
        if(read_whole(SEARCH_PATH,buf,SEARCH_MAX_BYTES,&bytes)&&bytes>12){
            count=le32(buf+8);
            if(!memcmp(buf,SEARCH_MAGIC,7)&&count==catalog_count&&
               bytes>=12+count*(2+SEARCH_KEY)){
                unsigned k;
                for(k=0;k<count;k++){
                    const uint8_t *e=buf+12+k*(2+SEARCH_KEY);
                    char key[SEARCH_KEY+1];
                    memcpy(key,e+2,SEARCH_KEY);key[SEARCH_KEY]=0;
                    if(contains(key,needle))
                        view[view_count++]=(uint16_t)((unsigned)e[0]|((unsigned)e[1]<<8));
                }
                if(view_count)view_active=1;
                error="";
                return view_count;
            }
        }
        error="";
    }
    for(i=0;i<catalog_count&&view_count<VIEW_MAX;i++){
        if(!catalog_read(i,&rec))break;
        if(contains(rec.label,needle)||contains(rec.path,needle)||
           (rec.pinyin[0]&&contains(rec.pinyin,needle)))
            view[view_count++]=(uint16_t)i;
    }
    if(view_count){view_active=1;}
    return view_count;
}
const NesRomImage *NesLibrary_Game(unsigned index)
{
    CatalogRecord rec;
    unsigned catalog_index=index;
    if(view_active){
        if(index>=view_count)return 0;
        catalog_index=view[index];
    }
    if(!sd_active)return index<nes_rom_image_count?&nes_rom_images[index]:0;
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
/* Read the header only, so the arena can be chosen before the full preload. */
static int probe(const char *path,NesImportInfo *info)
{
    char full[NES_PATH_MAX];uint8_t hdr[16];UINT got;uint32_t size;int rc;
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",path);
    if(f_open(&file,full,FA_READ)!=FR_OK){error="SD FILE MISSING";return 0;}
    size=(uint32_t)f_size(&file);
    ++nes_sd_file_reads;
    if(f_read(&file,hdr,16,&got)!=FR_OK||got!=16){
        (void)f_close(&file);error="SD READ ERROR";return 0;
    }
    rc=NesImport_Header(hdr,size,info);
    (void)f_close(&file);
    if(rc!=NES_IMPORT_OK){error=NesImport_Reason(rc);return 0;}
    return 1;
}
int NesLibrary_Load(unsigned index)
{
    CatalogRecord rec;NesImportInfo info;uint8_t *arena;char full[NES_PATH_MAX];
    uint32_t bytes,crc;int result;
    error="";
    if(NesLibrary_Save())return 10;
    if(!sd_active){
        const NesRomImage *g=index<nes_rom_image_count?&nes_rom_images[index]:0;
        if(!g){error="NO GAME SELECTED";return 10;}
        arena_menu=0;cached_cover=-1;
        result=Nes_Load(g->data,g->size);
        if(result)return result;
        save_active=0;
        return save_restore(crc32(g->data,g->size),g->size)?10:0;
    }
    if(view_active){
        if(index>=view_count){error="NO GAME SELECTED";return 10;}
        index=view[index];
    }
    if(!catalog_read(index,&rec)){error="NO GAME SELECTED";return 10;}
    if(!probe(rec.path,&info))return 10;
    arena=(uint8_t*)(info.mapper==5?NES_MMC5_ARENA_ADDR:
                     (info.chr_large?NES_LARGE_ARENA_ADDR:NES_ROM_ARENA_ADDR));
    CjkFont_Invalidate();   /* the ROM is about to own the arena */
    snprintf(full,sizeof(full),"0:" NES_DIR "/%s",rec.path);
    if(!read_whole(full,arena,info.mapper==5?NES_MMC5_ARENA_BYTES:
                   (info.chr_large?NES_LARGE_ARENA_BYTES:NES_ROM_ARENA_BYTES),&bytes))return 10;
    if(bytes!=info.size){error="SD FILE SIZE ERROR";return 10;}
    crc=crc32(arena,bytes);
    if(info.rewrite)memcpy(arena,info.header,16);
    arena_menu=0;cached_cover=-1;
    result=Nes_Load(arena,bytes);
    if(result)return result;
    /* Restrict this adaptation to the verified Japan image, not all MMC5
     * games. Use the on-card CRC, independent of menu labels. */
    input_profile=(uint8_t)(info.mapper==5 && bytes==786448u && crc==0x60579af2u);
    save_active=0;
    return save_restore(crc,bytes)?10:0;
}
