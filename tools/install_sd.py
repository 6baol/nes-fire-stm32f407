"""Install the prepared library into an explicitly selected card root.
Never formats a card, deletes files, or overwrites differing ROMs/covers.
The firmware scans NES/ itself, so no index file is written. --update-index
explicitly permits replacing only the metadata JSON.
"""
import argparse,hashlib,json
from pathlib import Path
from datetime import datetime,timezone
from prepare_sd import ROOT

def digest(data):return hashlib.sha256(data).hexdigest()

def install(card_root,update_index=False):
    root=Path(card_root)
    if not root.is_dir():raise ValueError('Card root is not available; specify e.g. F:/')
    source=ROOT/'Release/SD_ROOT/NES';manifest=json.loads((source/'GAMES.JSON').read_text())
    entries=[manifest['bios']]
    if manifest.get('titles'):entries.append(manifest['titles'])
    entries+=manifest.get('fonts',[])
    for game in manifest['games']:
        entries.append(game)
        if game.get('cover'):entries.append(game['cover'])
    data={}
    for item in entries:
        name=item['file']
        if Path(name).name!=name or '/' in name or '\\' in name:raise ValueError('Unsafe package filename')
        payload=(source/name).read_bytes()
        if digest(payload)!=item['sha256']:raise ValueError('Source checksum mismatch: '+name)
        data[name]=payload
    data['SD17.JSON']=(source/'GAMES.JSON').read_bytes()
    dest=root/'NES';allowed={'SD17.JSON','TITLES.DB'} if update_index else set()
    # Check every conflict before creating/writing any file.
    for name,payload in data.items():
        target=dest/name
        if target.exists() and (not target.is_file() or (target.read_bytes()!=payload and name not in allowed)):
            raise ValueError('Existing file differs; not overwritten: '+str(target))
    before=sorted(p.name for p in root.iterdir());dest.mkdir(exist_ok=True);records=[]
    for name,payload in data.items():
        target=dest/name;action='verified'
        if not target.exists():
            with target.open('xb') as file:file.write(payload)
            action='created'
        elif target.read_bytes()!=payload:
            # Only reached for the two metadata files explicitly authorized.
            with target.open('wb') as file:file.write(payload)
            action='updated'
        if digest(target.read_bytes())!=digest(payload):raise OSError('Card readback mismatch: '+str(target))
        records.append({'file':name,'bytes':len(payload),'sha256':digest(payload),'action':action})
    if not all((root/name).exists() for name in before):raise OSError('Existing root entry disappeared')
    report={'result':'PASS','timestamp_utc':datetime.now(timezone.utc).isoformat(),'target':str(dest),
            'formatted':False,'root_entries_preserved':before,'files':records,
            'metadata_update_authorized':update_index,'hardware_tested':False}
    print('PASS:',len(records),'files verified at',dest,';',sum(r['action']=='created' for r in records),'new files')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('card_root',type=Path)
    parser.add_argument('--update-index',action='store_true')
    args=parser.parse_args()
    report=install(args.card_root,args.update_index)
    (ROOT/'Release/sd_install_v0.17.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
