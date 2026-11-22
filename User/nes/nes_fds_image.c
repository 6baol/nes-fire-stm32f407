#include "nes_fds.h"
#include <string.h>

static unsigned le16(const uint8_t *p) {return (unsigned)p[0]|((unsigned)p[1]<<8);}

int FdsImage_File(const FdsImage *image,unsigned side,unsigned index,FdsFile *out)
{
    const uint8_t *p,*end;
    unsigned i,length,address,type;
    FdsFile file;
    if(!image || !out || !image->data || side>=image->sides ||
       image->size<(uint32_t)image->header_size+(uint32_t)image->sides*FDS_SIDE_SIZE) return 1;
    p=image->data+image->header_size+side*FDS_SIDE_SIZE;
    end=p+FDS_SIDE_SIZE;
    if(p[0]!=1 || memcmp(p+1,"*NINTENDO-HVC*",14) || p[56]!=2 || index>=p[57]) return 2;
    p+=58;
    for(i=0;i<=index;i++) {
        if((uint32_t)(end-p)<17u || p[0]!=3 || p[16]!=4) return 3;
        address=le16(p+11);length=le16(p+13);type=p[15];
        if(length>(uint32_t)(end-p)-17u) return 3;
        if(type>2 || (type==0 && (address<0x6000u || address+length>0xE000u)) ||
           (type==1 && address+length>0x2000u) ||
           (type==2 && (address<0x2000u || address+length>0x4000u))) return 4;
        if(i==index) {
            memset(&file,0,sizeof(file));
            file.data=p+17;file.address=(uint16_t)address;file.size=(uint16_t)length;
            file.number=p[1];file.id=p[2];file.type=(uint8_t)type;
            memcpy(file.name,p+3,8);*out=file;
            return 0;
        }
        p+=17+length;
    }
    return 2;
}

int FdsImage_Open(FdsImage *out,const uint8_t *data,uint32_t size)
{
    FdsImage image;
    FdsFile file;
    unsigned side,index,count;
    if(!out || !data || size<58u) return 1;
    memset(&image,0,sizeof(image));image.data=data;image.size=size;
    if(!memcmp(data,"FDS\x1a",4)) {
        image.header_size=16;image.sides=data[4];
    } else {
        if(size%FDS_SIDE_SIZE) return 1;
        count=size/FDS_SIDE_SIZE;
        if(count>FDS_MAX_SIDES) return 1;
        image.sides=(uint8_t)count;
    }
    if(!image.sides || image.sides>FDS_MAX_SIDES ||
       size!=(uint32_t)image.header_size+(uint32_t)image.sides*FDS_SIDE_SIZE) return 1;
    for(side=0;side<image.sides;side++) {
        const uint8_t *p=data+image.header_size+side*FDS_SIDE_SIZE;
        if(p[0]!=1 || memcmp(p+1,"*NINTENDO-HVC*",14) || p[56]!=2) return 2;
        for(index=0;index<p[57];index++) {
            int result=FdsImage_File(&image,side,index,&file);
            if(result) return result;
        }
    }
    *out=image; /* Reject malformed later sides without publishing partial state. */
    return 0;
}
