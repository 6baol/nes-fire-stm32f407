"""Import one NES/FDS plus an optional PNG/JPG cover. Never flashes a board."""
from pathlib import Path
import argparse,hashlib,json,re,subprocess,sys
import embed_roms as roms

def import_game(source,name=None,cover=None):
    # Preflight before touching the list, including unsupported mappers, labels,
    # image decode and all existing entries / ROM capacity.
    source=Path(source)
    roms.validate(roms.normalize(source.read_bytes()))
    roms.checked_label(name or roms.auto_label(source.name))
    image_data=None;cfg_path=roms.root/'Assets/posters/posters.json'
    if cover:
        from PIL import Image
        cover=Path(cover);image_data=cover.read_bytes()
        with Image.open(cover) as image:
            if image.format not in ('PNG','JPEG'):raise ValueError('Cover must be PNG or JPG')
            image.verify()
        config=json.loads(cfg_path.read_text(encoding='utf-8'))
    destination=next((g['file'] for g in roms.load_manifest() if g['file'].casefold()==source.name.casefold()),source.name)
    paths=[roms.roms_dir/destination,roms.manifest_path,roms.out_c,roms.out_h,roms.roms_dir/'current.json',
           cfg_path,roms.root/'Assets/posters/manifest.json',roms.root/'User/nes/nes_posters.c',roms.root/'User/nes/nes_posters.h']
    backup={p:p.read_bytes() if p.exists() else None for p in paths}
    created=None
    try:
        entry=roms.add_game(source,name)
        if image_data is not None:
            slug=re.sub(r'[^A-Za-z0-9_-]','_',source.stem)[:50]
            filename=slug+'-'+hashlib.sha256(image_data).hexdigest()[:12]+cover.suffix.lower()
            target=cfg_path.parent/filename
            if not target.exists():target.write_bytes(image_data);created=target
            record={'file':entry['file'],'image':filename,'layout':'poster','title':[],
                    'edition':'','system':'','credit':'','description':[],'cover_title':'','cover_subtitle':'',
                    'background':'#182864','ink':'#F8F8F8'}
            entries=config['covers']
            index=next((i for i,g in enumerate(entries) if g['file']==entry['file']),None)
            if index is None:entries.append(record)
            else:entries[index]=record
            cfg_path.write_text(json.dumps(config,indent=2,ensure_ascii=False),encoding='utf-8')
            subprocess.run([sys.executable,str(roms.root/'tools/embed_posters.py')],check=True)
    except Exception:
        for p,data in backup.items():
            if data is None:
                if p.exists():p.unlink()
            else:p.write_bytes(data)
        if created is not None and created.exists():created.unlink()
        raise
    print('Imported:',entry['label'])
    print('No board access. Build locally when ready; flashing is a separate manual step.')

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('rom',type=Path);p.add_argument('--name');p.add_argument('--cover',type=Path)
    a=p.parse_args();import_game(a.rom,a.name,a.cover)

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as exc:raise SystemExit(str(exc))
