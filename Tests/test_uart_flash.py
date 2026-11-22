"""Offline AN3155 transcript and STM32F407 sector-preservation regressions."""

from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import struct
import sys
from tempfile import TemporaryDirectory
import unittest


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import uart_flash as flash


class TranscriptPort:
    def __init__(self, response):
        self.response = io.BytesIO(response)
        self.written = []
        self.timeout = 2.5

    def read(self, count):
        return self.response.read(count)

    def write(self, data):
        self.written.append((data, self.timeout))
        return len(data)


class FlashSimulation:
    def __init__(self, before, backup_dir, corrupt=False):
        self.before = before
        self.memory = bytearray(before)
        self.backup_dir = backup_dir
        self.corrupt = corrupt
        self.erase_requests = []
        self.write_addresses = []

    def read_memory(self, address, length):
        offset = address - flash.FLASH_BASE
        data = bytes(self.memory[offset:offset + length])
        return b'\x00' + data[1:] if self.corrupt and self.erase_requests and offset == 0 else data

    def erase_sectors(self, sectors):
        backup, = self.backup_dir.glob('flash_uart_*.bin')
        assert backup.read_bytes() == self.before[:flash.SECTOR_ENDS[sectors[-1]]]
        self.erase_requests.append(sectors)
        for sector in sectors:
            start = flash.SECTOR_ENDS[sector - 1] if sector else 0
            end = flash.SECTOR_ENDS[sector]
            self.memory[start:end] = b'\xff' * (end - start)

    def write_block(self, address, data):
        assert data != flash.ERASED_BLOCK
        offset = address - flash.FLASH_BASE
        self.memory[offset:offset + len(data)] = data
        self.write_addresses.append(address)


class UartFlashTests(unittest.TestCase):
    def test_identify_is_a_read_only_protocol_exchange(self):
        port = TranscriptPort(bytes.fromhex('79 79 01 04 13 79 79 04 31 00 11 31 44 79 79 79 79 00 00 00 04'))
        loader = flash.RomLoader(port)
        loader.sync()
        identity = loader.identify()
        self.assertEqual(identity['flash_kib'], 1024)
        self.assertEqual(identity['device_id'], '0x413')
        self.assertEqual([data.hex() for data, _ in port.written],
                         ['7f', '02fd', '00ff', '11ee', '1fff7a20ba', '03fc'])

    def test_erase_and_write_packets_and_timeout_restoration(self):
        port = TranscriptPort(flash.ACK * 5)
        loader = flash.RomLoader(port)
        loader.erase_sectors(tuple(range(6)))
        block = bytes(range(256))
        loader.write_block(flash.FLASH_BASE, block)
        self.assertEqual(port.written[0], (b'\x44\xbb', 2.5))
        self.assertEqual(port.written[1], (bytes.fromhex('0005 0000 0001 0002 0003 0004 0005 04'), 90.0))
        self.assertEqual(port.written[2][0], b'\x31\xce')
        self.assertEqual(port.written[3][0], bytes.fromhex('0800000008'))
        self.assertEqual(port.written[4][0], b'\xff' + block + b'\xff')
        self.assertEqual(port.timeout, 2.5)
        with self.assertRaises(ValueError):
            loader.erase_sectors((0xffff,))
        port = TranscriptPort(flash.ACK + flash.NACK)
        with self.assertRaisesRegex(flash.LoaderError, 'NACK'):
            flash.RomLoader(port).erase_sectors((0,))
        self.assertEqual(port.timeout, 2.5)

    def test_candidate_span_allowlist_and_preservation(self):
        identity = {'commands': ['0x31', '0x44']}
        image = b'\x42' + b'\xff' * (184320 - 1)
        before = b'\x55' * len(image) + b'\xff' * 16 + b'\x23' + b'\xff' * (0x40000 - len(image) - 17)
        before += b'next sector'
        with TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            directory = Path(folder)
            loader = FlashSimulation(before, directory)
            report = flash.program_image(loader, identity, 'test', image, directory)
            self.assertEqual(loader.erase_requests, [tuple(range(6))])
            self.assertEqual(loader.write_addresses, [flash.FLASH_BASE, flash.FLASH_BASE + len(image)])
            self.assertEqual(loader.memory, image + before[len(image):])
            self.assertEqual(report['firmware_sha256'], flash.sha256(image))
            self.assertEqual(report['full_span_sha256'], flash.sha256(loader.memory[:0x40000]))
            self.assertEqual(report['verified_bytes'], 0x40000)
            backup = Path(report['backup'])
            self.assertEqual(json.loads(backup.with_suffix('.json').read_text())['backup_sha256'],
                             flash.sha256(before[:0x40000]))

    def test_wrong_id_wrong_size_and_readback_failure(self):
        wrong_id = TranscriptPort(bytes.fromhex('79 01 04 19 79'))
        with self.assertRaisesRegex(flash.LoaderError, '0x0419'):
            flash.RomLoader(wrong_id).identify()
        small_flash = TranscriptPort(bytes.fromhex('79 01 04 13 79 79 02 31 00 11 79 79 79 79 00 00 00 02'))
        with self.assertRaisesRegex(flash.LoaderError, '512 KiB'):
            flash.RomLoader(small_flash).identify()
        with TemporaryDirectory() as folder, redirect_stdout(io.StringIO()):
            directory = Path(folder)
            loader = FlashSimulation(b'\xff' * 0x4000, directory, corrupt=True)
            with self.assertRaisesRegex(flash.LoaderError, 'differs at 0x08000000'):
                flash.program_image(loader, {'commands': ['0x31', '0x44']}, 'test', b'\x42', directory)
            self.assertEqual(len(list(directory.glob('*.bin'))), 1)
            self.assertEqual(len(list(directory.glob('*.json'))), 0)

    def test_manifest_hash_is_mandatory(self):
        with TemporaryDirectory() as folder:
            manifest = Path(folder) / 'manifest.json'
            firmware = manifest.with_name('demo.bin')
            firmware.write_bytes(struct.pack('<I', 0x12345678))
            name = firmware.name
            mf = dict(version='test', firmware_prefix='demo', files={name: {'sha256': '0' * 64, 'bytes': 4}})
            manifest.write_text(json.dumps(mf))
            with self.assertRaisesRegex(ValueError, 'SHA-256'):
                flash.load_image(manifest)


if __name__ == '__main__':
    unittest.main()
