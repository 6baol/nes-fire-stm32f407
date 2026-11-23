"""Offline test for tools/dedup_sd.py: keeper choice, covers, prefs, catalog, quarantine."""
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
    struct.pack_into('<I', data, bucket_sd.PREF_CRC_OFFSET,
                     zlib.crc32(data[:784]) & 0xFFFFFFFF)
    path.write_bytes(data)


def main():
    with tempfile.TemporaryDirectory() as temp:
        nes = Path(temp) / 'NES'
        famicom = nes / 'famicom'
        famicom.mkdir(parents=True)
        for name in ('A (Japan)', 'A (USA)', 'A (USA) (Rev 1)',
                     'B (Japan)', 'B (USA)', 'C (Japan)'):
            (famicom / f'{name}.nes').write_bytes(b'ROM ' + name.encode())
            (famicom / f'{name}.COV').write_bytes(b'COV ' + name.encode())
        (nes / 'ROOT.nes').write_bytes(b'root game')
        (nes / 'CATALOG.IDX').write_bytes(b'old catalog')
        (nes / 'CATALOG.BAK').write_bytes(b'old backup')

        old_favorites = [bucket_sd.path_key('famicom/A (Japan).nes'),
                         bucket_sd.path_key('famicom/B (Japan).nes'),
                         bucket_sd.path_key('ROOT.nes')]
        old_recent = [bucket_sd.path_key('famicom/A (USA).nes')]
        make_prefs(nes / 'PREFS0.DAT', 5, old_favorites, old_recent)

        tool = str(ROOT / 'tools' / 'dedup_sd.py')
        dry = subprocess.run([sys.executable, tool, str(famicom)],
                             text=True, capture_output=True)
        assert dry.returncode == 0, dry.stderr
        assert (famicom / 'A (Japan).nes').exists()
        assert (nes / 'CATALOG.IDX').exists()

        apply = subprocess.run([sys.executable, tool, str(famicom), '--apply'],
                               text=True, capture_output=True)
        assert apply.returncode == 0, apply.stderr

        assert (famicom / 'A (USA) (Rev 1).nes').exists()
        assert (famicom / 'A (USA) (Rev 1).COV').exists()
        assert not (famicom / 'A (Japan).nes').exists()
        assert not (famicom / 'A (USA).nes').exists()
        assert (famicom / 'B (USA).nes').exists() and (famicom / 'B (USA).COV').exists()
        assert not (famicom / 'B (Japan).nes').exists()
        assert (famicom / 'C (Japan).nes').exists()
        assert (nes / 'ROOT.nes').exists()
        assert (nes / 'CATALOG.IDX.OLD').exists() and (nes / 'CATALOG.BAK.OLD').exists()
        assert not (nes / 'CATALOG.IDX').exists()

        parsed = bucket_sd.read_prefs(nes / 'PREFS0.DAT')
        assert parsed is not None
        _, generation, favorite_count, recent_count, favorites, recent = parsed
        keeper_a = bucket_sd.path_key('famicom/A (USA) (Rev 1).nes')
        keeper_b = bucket_sd.path_key('famicom/B (USA).nes')
        assert generation == 6
        assert favorites[:favorite_count] == [keeper_a, keeper_b, bucket_sd.path_key('ROOT.nes')]
        assert recent[:recent_count] == [keeper_a]

        quarantines = list(Path(temp).glob('_dedup_removed*'))
        assert len(quarantines) == 1
        names = {p.name for p in quarantines[0].rglob('*') if p.is_file()}
        assert {'A (Japan).nes', 'A (Japan).COV', 'A (USA).nes', 'A (USA).COV',
                'B (Japan).nes', 'B (Japan).COV'} <= names

    print('PASS dedup keep/remove, cover pairing, prefs remap, catalog reset, quarantine')


if __name__ == '__main__':
    main()
