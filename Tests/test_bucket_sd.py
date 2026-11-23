"""Offline test for tools/bucket_sd.py: buckets, prefs remap, catalog reset."""
import shutil
import struct
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import bucket_sd


def make_prefs(path, generation, favorites, recent):
    data = bytearray(bucket_sd.PREF_SIZE)
    struct.pack_into('<IIII', data, 0, bucket_sd.PREF_MAGIC, generation,
                     len(favorites), len(recent))
    for index, key in enumerate(favorites):
        struct.pack_into('<Q', data, bucket_sd.PREF_FAV_OFFSET + index * 8, key)
    for index, key in enumerate(recent):
        struct.pack_into('<Q', data, bucket_sd.PREF_RECENT_OFFSET + index * 8, key)
    struct.pack_into('<I', data, bucket_sd.PREF_CRC_OFFSET, zlib.crc32(data[:784]) & 0xFFFFFFFF)
    path.write_bytes(data)


def main():
    with tempfile.TemporaryDirectory() as temp:
        nes = Path(temp) / 'NES'
        famicom = nes / 'famicom'
        famicom.mkdir(parents=True)
        for name in 'ABCDE':
            (famicom / f'{name}.nes').write_bytes(b'ROM ' + name.encode())
            (famicom / f'{name}.COV').write_bytes(b'COV ' + name.encode())
        (nes / 'CATALOG.IDX').write_bytes(b'old catalog')
        (nes / 'CATALOG.BAK').write_bytes(b'old backup')

        old_favorites = [bucket_sd.path_key('famicom/A.nes'),
                         bucket_sd.path_key('famicom/C.nes')]
        old_recent = [bucket_sd.path_key('famicom/E.nes')]
        make_prefs(nes / 'PREFS0.DAT', 5, old_favorites, old_recent)
        make_prefs(nes / 'PREFS1.DAT', 4, old_favorites, old_recent)

        tool = str(ROOT / 'tools' / 'bucket_sd.py')
        dry = subprocess.run([sys.executable, tool, str(famicom), '--bucket-size', '3'],
                             text=True, capture_output=True)
        assert dry.returncode == 0, dry.stderr
        assert (famicom / 'A.nes').exists()
        assert (nes / 'CATALOG.IDX').exists()

        apply = subprocess.run([sys.executable, tool, str(famicom), '--bucket-size', '3', '--apply'],
                               text=True, capture_output=True)
        assert apply.returncode == 0, apply.stderr
        assert not (famicom / 'A.nes').exists()
        assert (famicom / '00' / 'A.nes').exists() and (famicom / '00' / 'A.COV').exists()
        assert (famicom / '00' / 'C.nes').exists()
        assert (famicom / '01' / 'E.nes').exists() and (famicom / '01' / 'E.COV').exists()
        assert (nes / 'CATALOG.IDX.OLD').exists() and (nes / 'CATALOG.BAK.OLD').exists()
        assert not (nes / 'CATALOG.IDX').exists()

        parsed = bucket_sd.read_prefs(nes / 'PREFS0.DAT')
        assert parsed is not None
        _, generation, favorite_count, recent_count, favorites, recent = parsed
        assert generation == 6
        assert favorites[:favorite_count] == [bucket_sd.path_key('famicom/00/A.nes'),
                                              bucket_sd.path_key('famicom/00/C.nes')]
        assert recent[:recent_count] == [bucket_sd.path_key('famicom/01/E.nes')]
        parsed1 = bucket_sd.read_prefs(nes / 'PREFS1.DAT')
        assert parsed1 is not None and parsed1[1] == 5

    print('PASS bucket moves, cover pairing, prefs remap, catalog reset')


if __name__ == '__main__':
    main()
