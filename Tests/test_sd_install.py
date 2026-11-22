"""Installer safety with temporary directories, never a physical card."""
import sys,tempfile,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
from install_sd import install

class InstallTest(unittest.TestCase):
    def test_new_copy_repeat_and_unrelated_data(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'TH06').mkdir();(root/'TH06/user.bin').write_bytes(b'untouched')
            first=install(root);self.assertTrue(all(r['action']=='created' for r in first['files']))
            second=install(root);self.assertTrue(all(r['action']=='verified' for r in second['files']))
            self.assertEqual((root/'TH06/user.bin').read_bytes(),b'untouched')
    def test_conflict_preflight_and_explicit_metadata_update(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'NES').mkdir();p=root/'NES/SD17.JSON';p.write_bytes(b'old meta')
            with self.assertRaises(ValueError):install(root)
            self.assertEqual(list((root/'NES').iterdir()),[p]);self.assertEqual(p.read_bytes(),b'old meta')
            report=install(root,True);self.assertEqual(next(r for r in report['files'] if r['file']=='SD17.JSON')['action'],'updated')
            bad=root/'NES/SMB3.nes';bad.write_bytes(b'user data')
            with self.assertRaises(ValueError):install(root,True)
            self.assertEqual(bad.read_bytes(),b'user data')

if __name__=='__main__':unittest.main()
