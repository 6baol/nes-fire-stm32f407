"""Read STM32F407 firmware identity and runtime statistics over SWD."""

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from threading import Timer
import time


ROOT = Path(__file__).resolve().parents[1]
FLASH_BASE = 0x08000000
FLASH_SIZE = 0x100000
DEVICE_ID = 0xE0042000
DHCSR = 0xE000EDF0
CFSR = 0xE000ED28
HFSR = 0xE000ED2C
STATE_NAMES = {0: 'menu', 1: 'game', 2: 'settings', 3: 'search', 4: 'library_options',
               5: 'save_error', 6: 'library_check'}
SRAM_RANGES = ((0x20000000, 0x20020000), (0x10000000, 0x10010000))
COUNTERS = (
    'uwTick', 'app_state', 'sd_active', 'catalog_count', 'sd_count',
    'view_count', 'sd_init_attempts', 'sd_last_error', 'sd_bus_width',
    'sd_read_retries', 'sd_write_retries', 'sd_blocks_read', 'sd_blocks_written',
    'nes_sd_file_reads', 'nes_sd_save_writes', 'nes_sd_save_restores',
    'nes_library_boot_ms', 'nes_search_ms', 'nes_load_ms', 'nes_save_ms',
    'nes_menu_redraw_us', 'nes_menu_updates', 'nes_logic_total', 'nes_draw_total',
    'nes_logic_hz', 'nes_draw_hz', 'nes_draw_frame_us', 'nes_skip_frame_us',
    'nes_effective_render_divisor', 'nes_lcd_pixels', 'nes_lcd_us',
    'nes_lcd_updates_total', 'nes_lcd_pixels_total', 'nes_clock_drops', 'nes_faults',
    'nes_audio_blocks', 'nes_audio_max_us', 'nes_audio_codec_error',
    'nes_audio_dma_errors', 'nes_apu_queue_drops', 'nes_capture_rejected',
)


def release_inputs(manifest_path, explicit_axf, flash_only):
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    prefix = manifest['firmware_prefix']
    if not re.fullmatch(r'[A-Za-z0-9._-]+', prefix):
        raise ValueError('Invalid firmware prefix in the release manifest.')
    binary = manifest_path.with_name(prefix + '.bin')
    expected = binary.read_bytes()
    expected_hash = hashlib.sha256(expected).hexdigest()
    if len(expected) == 0 or len(expected) > FLASH_SIZE:
        raise ValueError('Release BIN size is outside STM32F407ZG flash.')
    if expected_hash != manifest['files'][binary.name]['sha256'].lower():
        raise ValueError('Release BIN does not match its manifest SHA-256.')
    if flash_only:
        return manifest['version'], expected, expected_hash, None, {}

    axf = explicit_axf or manifest_path.with_name(prefix + '.axf')
    if explicit_axf is None and not axf.is_file():
        axf = ROOT / 'Project/Output/Fire_F407ZG.axf'
    from elftools.elf.elffile import ELFFile

    with axf.open('rb') as stream:
        expected_axf_hash = manifest['files'].get(prefix + '.axf', {}).get('sha256')
        if expected_axf_hash:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected_axf_hash.lower():
                raise ValueError('AXF does not match its manifest SHA-256.')
            stream.seek(0)
        elf = ELFFile(stream)
        segments = [segment for segment in elf.iter_segments()
                    if segment['p_type'] == 'PT_LOAD' and segment['p_filesz']]
        if not segments or min(seg['p_paddr'] for seg in segments) != FLASH_BASE:
            raise ValueError('AXF has no firmware load segment at the flash base.')
        for segment in segments:
            offset = segment['p_paddr'] - FLASH_BASE
            if offset < 0 or segment.data() != expected[offset:offset + segment['p_filesz']]:
                raise ValueError('AXF firmware bytes do not match the release BIN.')
        symtab = elf.get_section_by_name('.symtab')
        if symtab is None:
            raise ValueError('AXF has no symbol table. Pass the unstripped AXF or use --flash-only.')
        symbols = {sym.name: (sym['st_value'], sym['st_size']) for sym in symtab.iter_symbols()
                   if sym['st_info']['type'] == 'STT_OBJECT' and
                   sym.name in (*COUNTERS, 'status') and 0 < sym['st_size'] <= 4 and
                   any(lo <= sym['st_value'] <= hi - sym['st_size'] for lo, hi in SRAM_RANGES)}
    return manifest['version'], expected, expected_hash, axf, symbols


def read_probes(probe_id):
    from pyocd.core.helpers import ConnectHelper
    from pyocd.probe.cmsis_dap_probe import CMSISDAPProbe

    probes = [probe for probe in ConnectHelper.get_all_connected_probes(
        blocking=False, unique_id=probe_id, print_wait_message=False) if isinstance(probe, CMSISDAPProbe)]
    if len(probes) != 1:
        detail = ', '.join(probe.unique_id for probe in probes) or 'none'
        raise ValueError(f'Expected one matching CMSIS-DAP probe, found {detail}. Use --probe to select an ID.')
    return probes[0]


def sample(access, symbols, expected):
    raw_dhcsr = access.read32(DHCSR)
    state = 'lockup' if raw_dhcsr & (1 << 19) else 'halted' if raw_dhcsr & (1 << 17) else 'running'
    data = {name: int.from_bytes(access.read_memory_block8(address, size), 'little')
            for name, (address, size) in symbols.items() if name != 'status'}
    if 'app_state' in data:
        data['screen'] = STATE_NAMES.get(data['app_state'], 'unknown')
    if 'status' in symbols:
        address = access.read32(symbols['status'][0])
        ranges = (*SRAM_RANGES, (FLASH_BASE, FLASH_BASE + len(expected)))
        count = next((min(96, hi - address) for lo, hi in ranges if lo <= address < hi), 0)
        if count:
            data['status_text'] = bytes(access.read_memory_block8(address, count)).split(b'\0', 1)[0].decode('ascii', 'replace')
    data.update(state=state, SCB_CFSR=f'0x{access.read32(CFSR):08x}', SCB_HFSR=f'0x{access.read32(HFSR):08x}')
    return data


def read_board(args, version, expected, expected_hash, axf, symbols):
    from pyocd.core.session import Session
    from pyocd.coresight.ap import AccessPort, APv1Address, MEM_AP
    from pyocd.probe.debug_probe import DebugProbe

    probe = read_probes(args.probe)
    options = {'target_override': 'cortex_m', 'frequency': args.frequency,
               'no_config': True, 'user_script': os.path.abspath(os.devnull),
               'auto_unlock': False, 'cmsis_dap.limit_packets': True,
               'cmsis_dap.deferred_transfers': False}
    report = {'observed_at': datetime.now(timezone.utc).isoformat(), 'expected_release': version,
              'probe': probe.unique_id, 'frequency_hz': args.frequency, 'device_id': None,
              'transport': 'SWD MEM-AP reads, no target initialization',
              'expected_flash_sha256': expected_hash, 'bytes_checked': 0,
              'full_flash_match': False, 'samples': []}
    # Full pyOCD discovery can touch system registers even in attach mode. Open
    # only the probe and address AP 0 directly, without discovering the CPU.
    with Session(probe, auto_open=False, options=options) as session:
        session.open(init_board=False)
        port = session.target.dp
        port.connect(DebugProbe.Protocol.SWD)
        access = AccessPort.create(port, APv1Address(0))
        if not isinstance(access, MEM_AP):
            raise ValueError('AP 0 is not a memory access port.')
        device_id = access.read32(DEVICE_ID) & 0xfff
        report['device_id'] = f'0x{device_id:03x}'
        if device_id != 0x413:
            raise ValueError(f'Unexpected STM32 device ID {report["device_id"]}.')
        digest = hashlib.sha256()
        for offset in range(0, len(expected), 1024):
            chunk = bytes(access.read_memory_block8(FLASH_BASE + offset, min(1024, len(expected) - offset)))
            digest.update(chunk)
            report['bytes_checked'] += len(chunk)
        report['observed_flash_sha256'] = digest.hexdigest()
        report['full_flash_match'] = report['bytes_checked'] == len(expected) and digest.hexdigest() == expected_hash
        if report['full_flash_match'] and axf:
            report['symbols_source'] = str(axf)
            report['unavailable_counters'] = [name for name in COUNTERS if name not in symbols]
            start = time.monotonic()
            for index in range(args.samples):
                if index:
                    time.sleep(args.interval)
                measurements = sample(access, symbols, expected)
                measurements['elapsed_s'] = round(time.monotonic() - start, 3)
                report['samples'].append(measurements)
    return report


def hardware_timeout():
    # Some Windows HID backends can wait forever for the probe's response.
    print('CMSIS-DAP diagnostics timed out while waiting for the probe or reading the target.',
          file=sys.stderr, flush=True)
    os._exit(2)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=ROOT / 'Release/manifest.json')
    parser.add_argument('--axf', type=Path, help='matching standalone ARM ELF with symbols')
    parser.add_argument('--flash-only', action='store_true', help='verify firmware identity without reading RAM')
    parser.add_argument('--probe', help='CMSIS-DAP probe serial number')
    parser.add_argument('--frequency', type=int, default=1000000, help='SWD clock in Hz')
    parser.add_argument('--samples', type=int, default=3)
    parser.add_argument('--interval', type=float, default=1.0, help='seconds between samples')
    parser.add_argument('--timeout', type=float, default=90.0,
                        help='maximum SWD operation time in seconds, excluding sample delays')
    parser.add_argument('--output', type=Path, help='optional new JSON report file')
    args = parser.parse_args(argv)
    if (args.frequency <= 0 or args.samples <= 0 or not 0 <= args.interval < float('inf') or
            not 0 < args.timeout < float('inf')):
        parser.error('Frequency, samples and timeout must be positive. Interval must be finite and nonnegative.')
    try:
        args.manifest = args.manifest.resolve()
        if args.axf:
            args.axf = args.axf.resolve()
        if args.output:
            args.output = args.output.resolve()
            if args.output.exists():
                raise FileExistsError(f'Report already exists: {args.output}')
        release = release_inputs(args.manifest, args.axf, args.flash_only)
        timeout = Timer(args.timeout + (args.samples - 1) * args.interval, hardware_timeout)
        timeout.daemon = True
        timeout.start()
        try:
            report = read_board(args, *release)
        finally:
            timeout.cancel()
        document = json.dumps(report, ensure_ascii=False, indent=2)
        if args.output:
            with args.output.open('x', encoding='utf-8') as stream:
                stream.write(document + '\n')
        print(document)
        return 0 if report['full_flash_match'] else 1
    except (OSError, ImportError, ValueError, KeyError) as exc:
        print(f'Board diagnostics failed: {exc}', file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        from pyocd.core.exceptions import Error

        if not isinstance(exc, Error):
            raise
        print(f'SWD connection failed: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
