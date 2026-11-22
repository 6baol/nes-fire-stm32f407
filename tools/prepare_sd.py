"""Build an SD-root directory from Roms/roms.json; no card or board access.

Optional convenience only: firmware v0.20 scans NES/ itself, so a card works
when the player copies .nes/.fds files into it. This script exists to ship a
known-good pack (and the covers) for CI. Use FAT32.
"""
import argparse,hashlib,json,struct,zlib
from pathlib import Path
from PIL import Image,ImageOps
import embed_roms
import make_titles

ROOT=Path(__file__).resolve().parents[1]
COVER_HEADER=struct.Struct('<4sHHBBHIII')
MAX_NAME=64  # FF_LFN_BUF in ffconf.h

def encode_cover(path,poster=False):
    image=Image.open(path).convert('RGB')
    if poster:image=ImageOps.fit(image,(240,360),method=Image.Resampling.LANCZOS)
    return encode_cover_image(image)


def encode_cover_image(image,poster=False):
    """Pack an RGB image into the NCV1 layout the firmware reads."""
    if poster:image=ImageOps.fit(image,(240,360),method=Image.Resampling.LANCZOS)
    if image.width>512 or image.height>480:raise ValueError('Cover capture exceeds 512x480')
    indexed=image.quantize(colors=256,method=Image.Quantize.MEDIANCUT)
    pixels=indexed.tobytes();bits=4 if max(pixels)<16 else 8;count=1<<bits
    pal=indexed.getpalette();pal+= [0]*(768-len(pal))
    palette=b''.join(struct.pack('<H',((pal[i]>>3)<<11)|((pal[i+1]>>2)<<5)|(pal[i+2]>>3)) for i in range(0,count*3,3))
    if bits==4:pixels=bytes((pixels[i]<<4)|(pixels[i+1] if i+1<len(pixels) else 0) for i in range(0,len(pixels),2))
    payload=palette+pixels
    return COVER_HEADER.pack(b'NCV1',image.width,image.height,bits,int(poster),count,len(palette),len(pixels),zlib.crc32(payload))+payload

def decode_cover(data):
    if len(data)<COVER_HEADER.size:raise ValueError('Truncated cover header')
    magic,w,h,bits,flags,count,pal_size,pixel_size,crc=COVER_HEADER.unpack_from(data)
    if magic!=b'NCV1' or not 0<w<=512 or not 0<h<=480 or bits not in (4,8) or flags not in (0,1) or count!=(1<<bits):
        raise ValueError('Invalid cover header')
    payload=data[COVER_HEADER.size:]
    if pal_size!=count*2 or pixel_size!=(w*h*bits+7)//8 or len(payload)!=pal_size+pixel_size or zlib.crc32(payload)!=crc:
        raise ValueError('Invalid cover size or CRC')
    palette=struct.unpack('<'+'H'*count,payload[:pal_size]);pixels=payload[pal_size:]
    values=[palette[(pixels[i//2]>>(0 if i&1 else 4))&15] if bits==4 else palette[pixels[i]] for i in range(w*h)]
    return w,h,bits,values

def prepare(output):
    entries=embed_roms.load_manifest()
    embed_roms.check_budget([embed_roms.prepare(e) for e in entries])
    dest=Path(output)/'NES';dest.mkdir(parents=True,exist_ok=True)
    covers={c['file']:c for c in json.loads((ROOT/'Assets/posters/posters.json').read_text())['covers']}
    # Drop files from the previous pack so no stale ROM survives a rename.
    previous=dest/'GAMES.JSON'
    if previous.exists():
        for game in json.loads(previous.read_text())['games']:
            for item in (game,game.get('cover')):
                if item and (dest/item['file']).exists():(dest/item['file']).unlink()
        if (dest/'DISKSYS.ROM').exists():(dest/'DISKSYS.ROM').unlink()
    records=[];used=set()
    def write(name,data):
        (dest/name).write_bytes(data)
        return {'file':name,'bytes':len(data),'sha256':hashlib.sha256(data).hexdigest()}
    for entry in entries:
        source=(ROOT/'Roms'/entry['file']).read_bytes();data=embed_roms.normalize(source)
        mapper=embed_roms.validate(data)
        # The on-card name is the menu label: keep the player's original name.
        # sd_name lets a short repo filename ship under its full title.
        name=entry.get('sd_name') or entry['file']
        if len(name)>MAX_NAME:raise ValueError(f'ROM name exceeds {MAX_NAME} characters: {name}')
        base=name.rsplit('.',1)[0]
        if name.lower() in used or (base+'.COV').lower() in used:raise ValueError('Duplicate SD file name: '+name)
        used.add(name.lower())
        record=write(name,data);record.update(label=entry['label'],source=entry['file'],mapper=mapper,source_sha256=hashlib.sha256(source).hexdigest())
        if entry['file'] in covers:
            cover_name=base+'.COV';c=covers[entry['file']];packed=encode_cover(ROOT/'Assets/posters'/c['image'],c.get('layout')=='poster')
            decode_cover(packed);record['cover']=write(cover_name,packed);used.add(cover_name.lower())
        if '\t' in entry['label'] or '\n' in entry['label']:raise ValueError('Invalid label')
        records.append(record)
    bios=write('DISKSYS.ROM',(ROOT/'Roms/disksys.rom').read_bytes())
    if bios['bytes']!=8192:raise ValueError('BIOS must be 8192 bytes')
    # Ship the on-card title dictionary so the menu shows full names even when
    # the files themselves are short (e.g. "smb.nes").
    titles=['NESDB1']
    for record in records:
        digest=make_titles.fingerprint((dest/record['file']).read_bytes())
        titles.append(f'{digest:08X}\t{make_titles.clean_title(record["label"])}')
    title_record=write('TITLES.DB',('\n'.join(titles)+'\n').encode('ascii'))
    # 16x16 CJK glyphs + Unicode map, generated once by tools/make_cjk_font.py.
    fonts=[]
    font_source=ROOT/'Assets/fonts/cjk'
    for font_name in ('FONT.MAP','FONT.HZK'):
        if (font_source/font_name).exists():fonts.append(write(font_name,(font_source/font_name).read_bytes()))
    report={'version':3,'firmware_sd_loader_available':True,'firmware_min_version':'0.20','games':records,'bios':bios,
            'titles':title_record,'fonts':fonts,
            'note':'Optional pack: the firmware scans NES/ itself and needs no index. FDS BIOS stays embedded.'}
    (dest/'GAMES.JSON').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('Prepared',len(records),'games in',dest)
    print('No index file is written; v0.20 firmware scans the directory. No physical card was accessed.')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'Release/SD_ROOT')
    prepare(parser.parse_args().output)
