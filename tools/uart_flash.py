"""Identify or program the STM32F407ZG using its ST AN3155 UART ROM loader."""

import argparse
from datetime import datetime
from functools import reduce
import hashlib
import json
import operator
import os
from pathlib import Path
import re
import struct
import sys


ROOT = Path(__file__).resolve().parents[1]
FLASH_BASE = 0x08000000
FLASH_SIZE_WORD = 0x1FFF7A20
FLASH_KIB = 1024
DEVICE_ID = 0x0413
# Flash offsets at the end of each STM32F407ZG sector (ST RM0090).
SECTOR_ENDS = (0x4000, 0x8000, 0xC000, 0x10000, 0x20000, 0x40000, 0x60000,
               0x80000, 0xA0000, 0xC0000, 0xE0000, 0x100000)
BLOCK_SIZE = 256
ERASE_TIMEOUT = 90.0
ACK = b'\x79'
NACK = b'\x1f'
ERASED_BLOCK = b'\xff' * BLOCK_SIZE


class LoaderError(RuntimeError):
    pass


def packet(data):
    return data + bytes([reduce(operator.xor, data, 0)])


def sha256(data):
    return hashlib.sha256(data).hexdigest()


class RomLoader:
    def __init__(self, connection):
        self.connection = connection

    def read(self, size, stage):
        data = self.connection.read(size)
        if len(data) != size:
            raise LoaderError(f'{stage} timed out ({len(data)}/{size} byte(s) received).')
        return data

    def ack(self, stage):
        response = self.read(1, stage)
        if response == NACK:
            raise LoaderError(f'{stage} was rejected by the ROM loader (NACK).')
        if response != ACK:
            raise LoaderError(f'{stage} expected ACK and got 0x{response.hex()}.')

    def send(self, data, stage):
        if self.connection.write(data) != len(data):
            raise LoaderError(f'{stage} serial write did not finish.')
        self.ack(stage)

    def sync(self):
        self.send(b'\x7f', 'UART ROM loader synchronization')

    def command(self, code):
        self.send(bytes((code, code ^ 0xff)), f'command 0x{code:02x}')

    def query(self, code):
        self.command(code)
        length = self.read(1, 'query length')[0] + 1
        reply = self.read(length, 'query payload')
        self.ack('query end')
        return reply

    def read_memory(self, address, size):
        if not 2 <= size <= BLOCK_SIZE:
            raise ValueError('UART memory read requires 2 to 256 bytes.')
        self.command(0x11)
        self.send(packet(struct.pack('>I', address)), f'read address 0x{address:08x}')
        count = size - 1
        self.send(bytes((count, count ^ 0xff)), 'read length')
        return self.read(size, f'flash data at 0x{address:08x}')

    def identify(self):
        chip_id = self.query(0x02)
        if len(chip_id) != 2 or int.from_bytes(chip_id, 'big') != DEVICE_ID:
            raise LoaderError(f'Expected STM32 device ID 0x{DEVICE_ID:03x}; received 0x{chip_id.hex()}.')
        version, *commands = self.query(0x00)
        if 0x11 not in commands:
            raise LoaderError('The ROM loader did not advertise Read Memory.')
        # Read the aligned word containing the 16-bit Flash size at 0x1FFF7A22.
        size_kib = int.from_bytes(self.read_memory(FLASH_SIZE_WORD, 4)[2:], 'little')
        if size_kib != FLASH_KIB:
            raise LoaderError(f'Expected 1024 KiB of flash; received {size_kib} KiB.')
        return {'device_id': f'0x{DEVICE_ID:03x}', 'flash_kib': size_kib,
                'protocol_version': f'0x{version:02x}', 'commands': [f'0x{cmd:02x}' for cmd in commands]}

    def erase_sectors(self, sectors):
        if not sectors or tuple(sorted(set(sectors))) != tuple(sectors) or not all(
                0 <= sector < len(SECTOR_ENDS) for sector in sectors):
            raise ValueError('Extended Erase requires explicit, unique STM32F407ZG sector IDs.')
        payload = struct.pack(f'>{len(sectors) + 1}H', len(sectors) - 1, *sectors)
        self.command(0x44)
        timeout = self.connection.timeout
        try:
            self.connection.timeout = ERASE_TIMEOUT
            self.send(packet(payload), 'extended sector erase')
        finally:
            self.connection.timeout = timeout

    def write_block(self, address, data):
        if (address % 4 or len(data) != BLOCK_SIZE or not
                FLASH_BASE <= address <= FLASH_BASE + SECTOR_ENDS[-1] - BLOCK_SIZE):
            raise ValueError('Expected an aligned 256-byte block inside main flash.')
        self.command(0x31)
        self.send(packet(struct.pack('>I', address)), f'write address 0x{address:08x}')
        self.send(packet(bytes([len(data) - 1]) + data), f'write data at 0x{address:08x}')


def load_image(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    prefix = manifest['firmware_prefix']
    if prefix in ('.', '..') or not re.fullmatch(r'[a-zA-Z0-9._-]+', prefix):
        raise ValueError('Invalid firmware filename in the manifest.')
    binary = manifest_path.with_name(prefix + '.bin')
    image = binary.read_bytes()
    record = manifest['files'][binary.name]
    if len(image) != record['bytes'] or sha256(image) != record['sha256'].lower():
        raise ValueError('Firmware BIN length or SHA-256 does not match the manifest.')
    if not 0 < len(image) <= SECTOR_ENDS[-1]:
        raise ValueError('Firmware is outside STM32F407ZG main flash.')
    return manifest['version'], image


def read_flash(loader, span, stage):
    data = bytearray()
    for offset in range(0, span, BLOCK_SIZE):
        if offset % (64 * 1024) == 0:
            print(f'{stage}: {offset}/{span} bytes', flush=True)
        data.extend(loader.read_memory(FLASH_BASE + offset, BLOCK_SIZE))
    return bytes(data)


def program_image(loader, identity, version, image, backup_dir):
    if not {'0x31', '0x44'}.issubset(identity['commands']):
        raise LoaderError('The ROM loader must advertise Write Memory and Extended Erase.')
    last_sector, span = next((index, end) for index, end in enumerate(SECTOR_ENDS) if end >= len(image))
    sectors = tuple(range(last_sector + 1))
    backup_dir.mkdir(parents=True, exist_ok=True)
    before = read_flash(loader, span, 'Reading touched sectors')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    backup_path = backup_dir / f'flash_uart_{stamp}.bin'
    with backup_path.open('xb') as stream:
        stream.write(before)
        stream.flush()
        os.fsync(stream.fileno())
    if backup_path.read_bytes() != before:
        raise LoaderError(f'Sector backup verification failed: {backup_path}')
    print(f'Backed up {span} bytes to {backup_path}', flush=True)

    expected = image + before[len(image):]
    changed = before != expected
    if changed:
        print(f'Erasing sectors {", ".join(map(str, sectors))} (up to {ERASE_TIMEOUT:g} seconds)', flush=True)
        loader.erase_sectors(sectors)
        for offset in range(0, span, BLOCK_SIZE):
            if offset % (64 * 1024) == 0:
                print(f'Programming: {offset}/{span} bytes', flush=True)
            block = expected[offset:offset + BLOCK_SIZE]
            if block != ERASED_BLOCK:
                loader.write_block(FLASH_BASE + offset, block)
    actual = read_flash(loader, span, 'Verifying all touched sectors')
    if actual != expected:
        first = next((i for i, (read, wanted) in enumerate(zip(actual, expected)) if read != wanted), len(actual))
        raise LoaderError(f'Flash differs at 0x{FLASH_BASE + first:08x}. Sector backup: {backup_path}')

    report = dict(identity, version=version, programmer='STM32 UART ROM loader (AN3155)',
                  programmed=changed, sectors=list(sectors), firmware_bytes=len(image), verified_bytes=span,
                  firmware_sha256=sha256(actual[:len(image)]), full_span_sha256=sha256(actual),
                  backup=str(backup_path), backup_sha256=sha256(before), full_readback_match=True)
    report_path = backup_path.with_suffix('.json')
    with report_path.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, indent=2)
        stream.write('\n')
    return report


def main(argv=None):
    cli = argparse.ArgumentParser(description=__doc__, epilog=(
        'Enter the STM32 system ROM loader before opening the port. The program leaves the MCU in '
        'the ROM loader. To run the application, select normal flash boot and reset after verification.'))
    cli.add_argument('--port', '--com', required=True, help='Windows COM port for the STM32 UART')
    cli.add_argument('--baud', type=int, default=115200, choices=(9600, 19200, 38400, 57600, 115200))
    mode = cli.add_mutually_exclusive_group()
    mode.add_argument('--identify', action='store_true', help='read identification and flash size (default)')
    mode.add_argument('--program', action='store_true', help='back up, program and verify the named release')
    cli.add_argument('--manifest', type=Path, help='release manifest for --program')
    cli.add_argument('--backup-dir', type=Path, default=ROOT.parent / 'backups')
    cli.add_argument('--skip-sync', action='store_true', help='reuse an already synchronized ROM session at the same baud')
    args = cli.parse_args(argv)
    if not re.fullmatch(r'COM[1-9][0-9]*', args.port, re.IGNORECASE):
        cli.error('--port must be an explicit Windows COM name, such as COM4.')
    if args.program != (args.manifest is not None):
        cli.error('--program and --manifest must be supplied together.')

    try:
        release = load_image(args.manifest.resolve()) if args.program else None
        import serial

        link = serial.Serial(baudrate=args.baud, bytesize=serial.EIGHTBITS, parity=serial.PARITY_EVEN,
                             stopbits=serial.STOPBITS_ONE, timeout=2.5, write_timeout=2.5,
                             xonxoff=False, rtscts=False, dsrdtr=False)
        link.dtr = False
        link.rts = False
        link.port = args.port.upper()
        with link as connection:
            connection.reset_input_buffer()
            loader = RomLoader(connection)
            if not args.skip_sync:
                loader.sync()
            identity = loader.identify()
            identity.update(port=args.port.upper(), baud=args.baud)
            if release:
                report = program_image(loader, identity, *release, args.backup_dir.resolve())
            else:
                report = dict(identity, programmed=False)
        print(json.dumps(report, indent=2))
        return 0
    except ImportError as exc:
        print(f'UART flash requires pyserial. Install it with python -m pip install pyserial. {exc}', file=sys.stderr)
    except (KeyError, LoaderError, OSError, ValueError) as exc:
        print(f'UART flash failed: {exc}', file=sys.stderr)
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
