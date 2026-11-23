"""Build an SD-root directory from Roms/roms.json; no card or board access.

Optional convenience only: firmware v0.20 scans NES/ itself, so a card works
when the player copies .nes/.fds files into it. This script exists to ship a
known-good pack (and the covers) for CI. Use FAT32.
"""
import argparse,hashlib,json
from pathlib import Path
import embed_roms
import make_titles
from cover_codec import COVER_HEADER,decode_cover,encode_cover,encode_cover_image

ROOT=Path(__file__).resolve().parents[1]
MAX_NAME=64  # FF_LFN_BUF in ffconf.h


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
