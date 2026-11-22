"""Native cover preservation plus malformed SD-cover rejection, local only."""
import sys,tempfile,unittest
from pathlib import Path
from PIL import Image
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from prepare_sd import encode_cover,decode_cover

class SdCoverTest(unittest.TestCase):
    def test_native_title_captures(self):
        for name in ('smb_title','smb2_title','smb3_title','metroid_title','wizards_title'):
            path=ROOT/'Assets/posters'/(name+'.png');packed=encode_cover(path)
            w,h,bits,values=decode_cover(packed);source=Image.open(path).convert('RGB')
            self.assertEqual((w,h),source.size);self.assertEqual(bits,4)
            self.assertEqual(values,[((r>>3)<<11)|((g>>2)<<5)|(b>>3) for r,g,b in source.get_flattened_data()])
    def test_8bit_and_odd_4bit(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'test.png'
            for colors,bits in (([('red')]*15,4),([(i*4,i*3,i*2) for i in range(64)],8)):
                image=Image.new('RGB',(len(colors),1));image.putdata(colors if bits==8 else [(255,0,0)]*15);image.save(path)
                w,h,actual,values=decode_cover(encode_cover(path));self.assertEqual(actual,bits);self.assertEqual(len(values),len(colors))
    def test_corruption_and_truncation(self):
        packed=encode_cover(ROOT/'Assets/posters/metroid_title.png')
        for bad in (packed[:10],packed[:-1],packed+b'\0',b'BAD!'+packed[4:],packed[:40]+bytes([packed[40]^1])+packed[41:]):
            with self.assertRaises(ValueError):decode_cover(bad)

if __name__=='__main__':unittest.main()
