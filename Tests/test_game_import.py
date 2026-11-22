"""Import preflight/rollback regressions. Uses temporary files only; no board."""
import sys,tempfile,json,unittest,struct,shutil
from pathlib import Path
from unittest.mock import patch
root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tools'))
import embed_roms as roms
import add_game

def image(mapper=0,prg=1,chr=1):
    d=bytearray(b'NES\x1a'+bytes((prg,chr,(mapper&15)<<4,mapper&0xf0))+bytes(8)+
                b'\xea'*(prg*16384)+bytes(chr*8192))
    d[16+prg*16384-4:16+prg*16384-2]=struct.pack('<H',0x8000)
    return bytes(d)

class ImportTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.base=Path(self.tmp.name);self.roms=self.base/'Roms';self.roms.mkdir()
        (self.base/'User/nes').mkdir(parents=True);(self.base/'Assets/posters').mkdir(parents=True)
        (self.base/'Assets/posters/posters.json').write_text('{"covers":[]}')
        fields={'root':self.base,'roms_dir':self.roms,'manifest_path':self.roms/'roms.json',
                'out_c':self.base/'User/nes/nes_roms.c','out_h':self.base/'User/nes/nes_roms.h'}
        for key,value in fields.items():
            p=patch.object(roms,key,value);p.start();self.addCleanup(p.stop)
        (self.roms/'first.nes').write_bytes(image());roms.save_manifest([{'file':'first.nes','label':'FIRST GAME'}]);roms.build()
    def snapshot(self):
        return {str(p.relative_to(self.base)):p.read_bytes() for p in self.base.rglob('*') if p.is_file()}
    def test_unsupported_mapper_rejection_changes_nothing(self):
        src=self.base.parent/(self.base.name+'-mapper255.nes');src.write_bytes(image(255));self.addCleanup(src.unlink)
        before=self.snapshot()
        with self.assertRaisesRegex(ValueError,'Unsupported mapper 255'):add_game.import_game(src,'UNSUPPORTED GAME')
        self.assertEqual(before,self.snapshot())
    def test_mmc3_import_preserves_full_name_and_source(self):
        src=self.base/'SMB3.nes';src.write_bytes(image(4,prg=2));original=src.read_bytes()
        add_game.import_game(src,'SUPER MARIO BROS. 3')
        entries=roms.load_manifest()
        self.assertEqual(entries[-1],{'file':'SMB3.nes','label':'SUPER MARIO BROS. 3'})
        self.assertEqual(roms.prepare(entries[-1])['mapper'],4)
        self.assertEqual(src.read_bytes(),original)
    def test_full_name_replace_keeps_menu_position(self):
        src=self.base/'second.nes';src.write_bytes(image())
        roms.add_game(src,'A FULL GAME TITLE LONGER THAN 27 CHARACTERS')
        roms.add_game(self.roms/'first.nes','FIRST GAME RENAMED')
        entries=roms.load_manifest()
        self.assertEqual([g['file'] for g in entries],['first.nes','second.nes'])
        self.assertEqual(entries[1]['label'],'A FULL GAME TITLE LONGER THAN 27 CHARACTERS')
    def test_mmc1_axrom_import_preserves_sources(self):
        for mapper,chr_count in ((1,1),(1,0),(7,0)):
            src=self.base/f'mapper{mapper}-chr{chr_count}.nes'
            original=image(mapper,prg=2,chr=chr_count);src.write_bytes(original)
            add_game.import_game(src,f'MAPPER {mapper} CHR {chr_count}')
            self.assertEqual(roms.prepare(roms.load_manifest()[-1])['mapper'],mapper)
            self.assertEqual(src.read_bytes(),original)
    def test_mapper_11_66_71_import_preserves_sources(self):
        for mapper,chr_count in ((11,16),(66,4),(71,0)):
            src=self.base/f'mapper{mapper}.nes';original=image(mapper,prg=2,chr=chr_count)
            src.write_bytes(original);add_game.import_game(src,f'MAPPER {mapper} TEST')
            self.assertEqual(roms.prepare(roms.load_manifest()[-1])['mapper'],mapper)
            self.assertEqual(src.read_bytes(),original)
    def test_new_mapper_invalid_board_rolls_back(self):
        for mapper,chr_count in ((11,0),(66,8),(71,1)):
            src=self.base/f'bad{mapper}.nes';src.write_bytes(image(mapper,prg=2,chr=chr_count))
            before=self.snapshot()
            with self.assertRaises(ValueError):add_game.import_game(src,'UNSUPPORTED BOARD')
            self.assertEqual(before,self.snapshot())
    def test_new_mapper_plain_nes2_normalization(self):
        for mapper,chr_count in ((11,1),(66,1),(71,0)):
            raw=bytearray(image(mapper,prg=2,chr=chr_count));raw[7]|=8
            normalized=roms.normalize(bytes(raw))
            self.assertEqual(normalized[16:],raw[16:])
            self.assertEqual(roms.validate(normalized),mapper)
            raw[8]=0x20  # explicit submapper must not lose its hardware variant
            with self.assertRaises(ValueError):roms.normalize(bytes(raw))
    def test_sd_library_exceeds_flash_budget_but_has_per_game_limit(self):
        entries=[{'data':bytes(400000)},{'data':bytes(400000)}]
        roms.check_budget(entries)
        with self.assertRaises(ValueError):roms.check_embedded_budget(entries)
        with self.assertRaises(ValueError):roms.check_budget([{'data':bytes(640*1024+1)}])
        with self.assertRaises(ValueError):roms.check_budget([{'data':b''}]*65)
    def test_mmc3_budget_rejected_before_any_write(self):
        src=self.base/'SMB3.nes';src.write_bytes(image(4,prg=2));before=self.snapshot()
        with patch.object(roms,'check_budget',side_effect=ValueError('capacity')):
            with self.assertRaisesRegex(ValueError,'capacity'):roms.add_game(src,'SUPER MARIO BROS. 3')
        self.assertEqual(before,self.snapshot())
    def test_invalid_cover_changes_nothing(self):
        src=self.base/'second.nes';src.write_bytes(image());bad=self.base/'bad.png';bad.write_bytes(b'not an image')
        before=self.snapshot()
        with self.assertRaises(OSError):add_game.import_game(src,'SECOND GAME',bad)
        self.assertEqual(before,self.snapshot())
    def test_cover_pack_failure_rolls_back_import(self):
        from PIL import Image
        src=self.base/'second.nes';src.write_bytes(image());cover=self.base/'cover.png';Image.new('RGB',(16,24),'blue').save(cover)
        before=self.snapshot()
        with patch.object(add_game.subprocess,'run',side_effect=OSError('packer failed')):
            with self.assertRaisesRegex(OSError,'packer failed'):add_game.import_game(src,'SECOND GAME',cover)
        self.assertEqual(before,self.snapshot())
    def test_cover_import_generates_mapping_and_pixels(self):
        from PIL import Image
        (self.base/'tools').mkdir()
        shutil.copy2(root/'tools/embed_posters.py',self.base/'tools/embed_posters.py')
        src=self.base/'second.nes';src.write_bytes(image())
        cover=self.base/'cover.png';Image.new('RGB',(16,24),'blue').save(cover)
        original=cover.read_bytes()
        add_game.import_game(src,'SECOND GAME',cover)
        cfg=json.loads((self.base/'Assets/posters/posters.json').read_text())
        self.assertEqual(cfg['covers'][0]['file'],'second.nes')
        self.assertEqual(cfg['covers'][0]['layout'],'poster')
        self.assertTrue((self.base/'User/nes/nes_posters.c').exists())
        packed=json.loads((self.base/'Assets/posters/manifest.json').read_text())
        self.assertEqual(packed['covers'][0]['pixel_bits'],4)
        self.assertEqual(packed['total_flash_bytes'],43232)
        self.assertEqual(original,cover.read_bytes())
    def test_full_colour_cover_keeps_8bit_fallback(self):
        from PIL import Image
        (self.base/'tools').mkdir()
        shutil.copy2(root/'tools/embed_posters.py',self.base/'tools/embed_posters.py')
        src=self.base/'colour.nes';src.write_bytes(image())
        cover=self.base/'colour.png';art=Image.new('RGB',(16,16))
        art.putdata([(x*16,y*16,(x+y)*8) for y in range(16) for x in range(16)]);art.save(cover)
        add_game.import_game(src,'COLOUR COVER',cover)
        packed=json.loads((self.base/'Assets/posters/manifest.json').read_text())
        self.assertEqual(packed['covers'][0]['pixel_bits'],8)
        self.assertEqual(packed['total_flash_bytes'],86912)
    def test_escaped_label_emits_valid_c_string(self):
        roms.add_game(self.roms/'first.nes','A "QUOTED" GAME')
        self.assertIn(r'A \"QUOTED\" GAME',roms.out_c.read_text())

if __name__=='__main__':unittest.main()
