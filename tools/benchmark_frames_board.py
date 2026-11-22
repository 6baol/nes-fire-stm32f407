"""Measure fixed scenes on the STM32 board through SWD, with no CPU halts.

Uses the first seven entries of the project's reference SD card. Normal menu
launches update recently played history. Only known non-battery cartridges
may be reset. ROM input timing is in emulated logic frames, not host seconds.
"""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import faulthandler
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import time

from elftools.elf.elffile import ELFFile
from pyocd.core.session import Session
from pyocd.coresight.ap import AccessPort, APv1Address, MEM_AP
from pyocd.probe.debug_probe import DebugProbe

import read_sd_state as diag


@dataclass(frozen=True)
class Cartridge:
    index: int
    filename: str
    local_name: str
    mapper: int
    sha256: str
    # Press Start (or other specified buttons) at absolute emulation frames.
    setup: tuple
    begin: int


GAMES = {
    'smb1': Cartridge(5, 'Super Mario Bros. (World).nes', 'smb.nes', 0,
        '0b3d9e1f01ed1668205bab34d6c82b0e281456e137352e4f36a9b2cfa3b66dea',
        ((150, 8),), 350),
    'metroid': Cartridge(1, 'Metroid (USA).nes', 'Metroid (USA).nes', 1,
        'e6e6b7014685adae447ebb3833242815747bc1e5df83ade79f693fb67cf565b6',
        ((360, 8), (484, 8), (968, 1, 12)), 1040),
    'wizards': Cartridge(2, 'Wizards & Warriors (U).nes', 'Wizards & Warriors (U).nes', 7,
        '463018ac63de3b31a006882538fa1e0b500ba113ad7263e09669039e1193d7dc',
        ((360, 8), (484, 8), (1028, 1, 12)), 1100),
    'smb3': Cartridge(6, 'Super Mario Bros. 3 (USA).nes', 'SMB3.nes', 4,
        '6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267',
        ((480, 8), (574, 8), (882, 0x80), (976, 0x10), (1070, 1)), 1284),
}
EXTRA = {'menu': 8, 'menu_armed': 1, 'menu_axis_armed': 1, 'view_active': 1,
         'cat_window': 1248, 'window_first': 4, 'window_valid': 1, 'nes_test_pad': 1,
         'save_active': 1, 'romfile': 4, 'MapperNo': 4, 'running_title': 57,
         'NES_RAM': 4, 'spr_ram': 4, 'nes_audio_ready': 4, 'stats_due': 4}
ERRORS = ('nes_faults', 'nes_audio_dma_errors', 'nes_audio_codec_error',
          'nes_apu_queue_drops', 'sd_read_retries', 'sd_write_retries', 'sd_last_error')
ACTIVITY = ('sd_blocks_read', 'sd_blocks_written', 'nes_sd_save_writes', 'nes_audio_blocks')
COSTS = ('nes_draw_frame_us', 'nes_skip_frame_us', 'nes_effective_render_divisor')


def extra_symbols(axf):
    with axf.open('rb') as stream:
        table = ELFFile(stream).get_section_by_name('.symtab')
        out = {s.name: (s['st_value'], s['st_size']) for s in table.iter_symbols()
               if s['st_info']['type'] == 'STT_OBJECT' and s.name in EXTRA}
    for name, size in EXTRA.items():
        address, actual = out.get(name, (0, 0))
        if actual != size or not any(lo <= address <= hi - size for lo, hi in diag.SRAM_RANGES):
            raise ValueError(f'Incompatible debug symbol {name}')
    return out


def wait_for(read, condition, timeout, description, interval=0.04):
    deadline = time.monotonic() + timeout
    while True:
        value = read()
        if condition(value):
            return value
        if time.monotonic() >= deadline:
            raise RuntimeError(f'Timed out waiting for {description}, last value {value}')
        time.sleep(interval)


class Board:
    def __init__(self, access, symbols):
        self.ap = access
        self.symbols = symbols

    def number(self, name):
        addr, size = self.symbols[name]
        if size == 4:
            return self.ap.read32(addr)
        return self.ap.read8(addr)

    def memory(self, addr, size):
        return bytes(self.ap.read_memory_block8(addr, size))

    def pad(self, value):
        self.ap.write8(self.symbols['nes_test_pad'][0], value)

    def wait(self, name, value, timeout=10):
        return wait_for(lambda: self.number(name), lambda actual: actual == value, timeout, name)

    def wait_frame(self, frame):
        return wait_for(lambda: self.number('nes_logic_total'), lambda actual: actual >= frame,
                        45, f'logic frame {frame}', 0.006)

    def check_game(self, game):
        # The SD preparation tools may normalize iNES headers. The control
        # bits, title and multiple PRG/CHR locations identify this corpus.
        raw = (diag.ROOT / 'Roms' / game.local_name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != game.sha256:
            raise ValueError(f'Unrecognized local ROM {game.local_name}')
        address = self.number('romfile')
        if address != 0x6c060000 or self.number('MapperNo') != game.mapper:
            raise RuntimeError('Unexpected ROM arena or mapper')
        header = self.memory(address, 16)
        if header[:4] != b'NES\x1a' or header[4:7] != raw[4:7] or header[6] & 2:
            raise RuntimeError(f'Unexpected or battery-backed ROM header {header.hex()}')
        if self.number('save_active'):
            raise RuntimeError('Active battery-save session')
        for offset in (16, 336, len(raw) // 2, len(raw) - 128):
            if self.memory(address + offset, 128) != raw[offset:offset + 128]:
                raise RuntimeError(f'Wrong ROM data at offset {offset}')
        return header.hex()

    def reset_known_game(self):
        if self.number('app_state') != 1 or self.number('nes_test_pad'):
            raise RuntimeError('A running reference game with released inputs is required for reset')
        title = self.memory(*self.symbols['running_title']).split(b'\0', 1)[0].decode()
        game = next((g for g in GAMES.values() if g.filename[:-4].upper() == title), None)
        if game is None:
            raise RuntimeError(f'Leaving unrecognized game {title!r} running')
        self.check_game(game)
        self.ap.write32(0xe000ed0c, 0x05fa0004)  # ARM AIRCR.SYSRESETREQ
        time.sleep(1)
        self.wait('menu_armed', 1, 35)

    def launch(self, game):
        if self.number('app_state') == 1:
            self.reset_known_game()
        elif self.number('app_state') == 3:
            # A capacitive-pad touch can open search while the game library
            # is idle. Use the ordinary back button to restore the library.
            self.pad(2)
            try:
                self.wait('app_state', 0, 4)
            finally:
                self.pad(0)
            time.sleep(0.35)
        self.wait('sd_active', 1, 35)
        self.wait('menu_armed', 1)
        if self.number('app_state') != 0 or self.number('view_active') or self.number('nes_test_pad'):
            raise RuntimeError(f'Expected the full SD library: {self.counters(("app_state", "view_active", "nes_test_pad"))}')
        def index():
            return self.ap.read16(self.symbols['menu'][0])
        for _ in range(8):
            selected = index()
            if selected == game.index:
                break
            self.wait('menu_axis_armed', 1)
            step = 1 if selected < game.index else -1
            self.pad(0x20 if step == 1 else 0x10)
            try:
                wait_for(index, lambda i: i == selected + step, 4, 'menu selection')
            finally:
                self.pad(0)
        self.wait('menu_axis_armed', 1)
        first = wait_for(lambda: self.number('window_first'),
                         lambda i: i <= game.index < i + 4 and self.number('window_valid'),
                         4, 'selected catalog window')
        if index() != game.index:
            raise RuntimeError(f'Cannot verify catalog selection {game.index}')
        path_at = self.symbols['cat_window'][0] + 312 * (game.index - first) + 12
        path = self.memory(path_at, 161).split(b'\0', 1)[0].decode()
        if path != game.filename:
            raise RuntimeError(f'Unexpected catalog order, selected {path!r}')
        self.wait('menu_armed', 1)
        start = self.number('nes_logic_total')
        self.pad(1)
        try:
            self.wait('app_state', 1, 15)
        finally:
            self.pad(0)
        return start, self.check_game(game)

    def clock(self):
        # Bracket the target counters with the target's own millisecond clock.
        host_begin = time.perf_counter()
        t0 = self.number('uwTick')
        logic = self.number('nes_logic_total')
        draw = self.number('nes_draw_total')
        t1 = self.number('uwTick')
        host_end = time.perf_counter()
        if not 0 <= t1 - t0 < 100:
            raise RuntimeError('Unusable endpoint clock sample')
        result = {'ms': (t0 + t1) / 2, 'bracket_ms': t1 - t0, 'logic': logic, 'draw': draw,
                  'host_s': (host_begin + host_end) / 2, 'host_bracket_ms': (host_end - host_begin) * 1000,
                  'core_cycles': self.ap.read32(0xe0001004), 'stats_deadline_ms': self.number('stats_due'),
                  'clock_drops': self.number('nes_clock_drops')}
        result.update(self.counters(n for n in ('nes_lcd_updates_total', 'nes_lcd_pixels_total')
                                    if n in self.symbols))
        return result

    def counters(self, names):
        return {name: self.number(name) for name in names}

    def diagnostics(self):
        result = self.counters(ERRORS + ACTIVITY + ('nes_clock_drops', 'nes_audio_ready', 'app_state'))
        result.update(cfsr=self.ap.read32(diag.CFSR), hfsr=self.ap.read32(diag.HFSR))
        if any(result[n] for n in ERRORS + ('cfsr', 'hfsr')) or result['app_state'] != 1 or not result['nes_audio_ready']:
            raise RuntimeError(f'Board fault or audio unavailable: {result}')
        return result

    def position(self, name):
        ram = self.number('NES_RAM')
        if name in ('smb1', 'smb3'):
            x, page, y = (0x86, 0x6d, 0xce) if name == 'smb1' else (0x90, 0x75, 0xa2)
            return [self.ap.read8(ram + x) + 256 * self.ap.read8(ram + page), self.ap.read8(ram + y)]
        start, end = (32, 64) if name == 'metroid' else (4, 44)
        data = self.memory(self.number('spr_ram') + start, end - start)
        return [round(sum(data[3::4]) / len(data[3::4]), 2), min(data[0::4])]

    @contextmanager
    def stats_window(self, enabled):
        previous = self.number('stats_due')
        address = self.symbols['stats_due'][0]
        if not enabled:
            if self.number('app_state') != 1 or self.number('save_active'):
                raise RuntimeError('Not in a verified non-battery game session')
            self.ap.write32(address, (self.number('uwTick') + 60000) & 0xffffffff)
        try:
            yield
        finally:
            if not enabled:
                self.ap.write32(address, previous)

    def run(self, name, stats_enabled):
        game = GAMES[name]
        start, header = self.launch(game)
        print(f'{name} verified, advancing to scene', flush=True)
        for frame, buttons, *duration in game.setup:
            self.wait_frame(start + frame)
            self.pad(buttons)
            self.wait_frame(start + frame + (duration[0] if duration else 4))
            self.pad(0)
        before = self.diagnostics()
        begin = start + game.begin
        self.wait_frame(begin - 10)
        with self.stats_window(stats_enabled):
            return self.measure(name, before, begin, header)

    def measure(self, name, before, begin, header):
        game = GAMES[name]
        self.wait_frame(begin)
        positions = [self.position(name)]
        # Same scripted first-stage movement on all four titles. Sample the
        # latest draw/skip durations every 30 frames (not integrated costs).
        t0 = self.clock()
        samples = []
        for offset, buttons in ((0, 0x80), (30, 0x81), (60, 0x80), (90, 0),
                                (120, 0x80), (150, 0x81), (180, 0x80), (210, 0)):
            self.wait_frame(begin + offset)
            if offset == 30:
                positions.append(self.position(name))
            self.pad(buttons)
            samples.append(self.counters(n for n in COSTS + ('nes_lcd_pixels', 'nes_lcd_us')
                                         if n in self.symbols))
        self.wait_frame(begin + 240)
        t1 = self.clock()
        self.pad(0)
        after = self.diagnostics()
        elapsed = (t1['ms'] - t0['ms']) / 1000
        if elapsed <= 0 or t1['logic'] - t0['logic'] < 230 or t1['draw'] == t0['draw']:
            raise RuntimeError('Incomplete measurement window')
        result = {'game': game.filename, 'mapper': game.mapper, 'local_sha256': game.sha256,
                  'sd_header': header, 'rom_identity_check': 'file path, mapper, header and 4 x 128 payload bytes',
                  'scene': 'first-stage input script', 'start_frame': game.begin, 'target_frames': 240,
                  'start': t0, 'end': t1, 'logic_fps': round((t1['logic']-t0['logic'])/elapsed, 3),
                  'draw_fps': round((t1['draw']-t0['draw'])/elapsed, 3), 'samples': samples,
                  'draw_ms_sample_median': median(s[COSTS[0]] for s in samples)/1000,
                  'skip_ms_sample_median': median(s[COSTS[1]] for s in samples)/1000,
                  'positions_before_after_30_right': positions, 'before': before, 'after': after}
        if 'nes_lcd_updates_total' in t1:
            updates = (t1['nes_lcd_updates_total'] - t0['nes_lcd_updates_total']) & 0xffffffff
            pixels = (t1['nes_lcd_pixels_total'] - t0['nes_lcd_pixels_total']) & 0xffffffff
            result.update(lcd_updates=updates, lcd_update_fps=round(updates/elapsed, 3),
                          lcd_pixels_submitted=pixels)
        result['right_motion_verified'] = positions[1][0] > positions[0][0] + 5
        host_elapsed = t1['host_s'] - t0['host_s']
        cycle_delta = (t1['core_cycles'] - t0['core_cycles']) & 0xffffffff
        dwt_elapsed = cycle_delta / 168000000  # HSE 25 MHz, PLLM=25/N=336/P=2, AHB div1.
        result['dwt_s'] = dwt_elapsed
        result['host_logic_fps'] = round((t1['logic']-t0['logic']) / host_elapsed, 3)
        result['host_draw_fps'] = round((t1['draw']-t0['draw']) / host_elapsed, 3)
        result['dwt_logic_fps'] = round((t1['logic']-t0['logic']) / dwt_elapsed, 3)
        result['dwt_draw_fps'] = round((t1['draw']-t0['draw']) / dwt_elapsed, 3)
        if 'lcd_updates' in result:
            result['host_lcd_update_fps'] = round(result['lcd_updates'] / host_elapsed, 3)
            result['dwt_lcd_update_fps'] = round(result['lcd_updates'] / dwt_elapsed, 3)
        if not result['right_motion_verified']:
            result['scene'] = 'scripted inputs; first-stage movement unconfirmed'
        if any(after[n] != before[n] for n in ACTIVITY[:-1]) or after['nes_audio_blocks'] <= before['nes_audio_blocks']:
            raise RuntimeError('Unexpected gameplay storage traffic or stopped audio')
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='new JSON file')
    parser.add_argument('--probe', required=True)
    parser.add_argument('--games', choices=GAMES, nargs='+', default=list(GAMES))
    parser.add_argument('--stats-modes', nargs='+', choices=['on', 'off'], default=['on'],
                        help='periodic FPS logging state(s) in each gameplay window')
    args = parser.parse_args()
    version, image, digest, axf, symbols = diag.release_inputs(args.manifest, None, False)
    symbols.update(extra_symbols(axf))
    print('Opening probe and verifying the complete firmware image', flush=True)
    # Windows HID can block in a native read. Protect the initial attach,
    # before the script has written an input or issued any reset.
    faulthandler.dump_traceback_later(65, exit=True)
    probe = diag.read_probes(args.probe)
    options = {'target_override': 'cortex_m', 'frequency': 1000000, 'no_config': True,
               'user_script': os.path.abspath(os.devnull), 'auto_unlock': False,
               'cmsis_dap.limit_packets': True, 'cmsis_dap.deferred_transfers': False}
    report = {'version': version, 'sha256': digest, 'utc': datetime.now(timezone.utc).isoformat(),
              'games': {}, 'runs': [], 'result': 'incomplete'}
    with args.output.open('x', encoding='utf-8') as out:
        try:
            with Session(probe, auto_open=False, options=options) as session:
                session.open(init_board=False)
                dp = session.target.dp
                dp.connect(DebugProbe.Protocol.SWD)
                ap = AccessPort.create(dp, APv1Address(0))
                if not isinstance(ap, MEM_AP) or ap.read32(diag.DEVICE_ID) & 0xfff != 0x413:
                    raise RuntimeError('Unexpected debug target')
                readback = hashlib.sha256()
                for offset in range(0, len(image), 512):
                    readback.update(bytes(ap.read_memory_block8(diag.FLASH_BASE+offset, min(512,len(image)-offset))))
                if readback.hexdigest() != digest:
                    raise RuntimeError('Flash identity differs from manifest')
                faulthandler.cancel_dump_traceback_later()
                print('Firmware identity verified', flush=True)
                board = Board(ap, symbols)
                if board.number('nes_test_pad'):
                    raise RuntimeError('Another test already holds an input')
                try:
                    for name in args.games:
                        for mode in args.stats_modes:
                            row = board.run(name, mode == 'on')
                            row['periodic_stats'] = mode
                            report['runs'].append(row)
                            if row['start']['stats_deadline_ms'] == row['end']['stats_deadline_ms'] and mode == 'on':
                                raise RuntimeError('Expected periodic stats activity')
                            if row['start']['stats_deadline_ms'] != row['end']['stats_deadline_ms'] and mode == 'off':
                                raise RuntimeError('Periodic stats fired during suppression')
                            if len(args.stats_modes) == 1:
                                report['games'][name] = row
                            print(name, mode, row['host_logic_fps'], row['host_draw_fps'],
                                  row['positions_before_after_30_right'], flush=True)
                            out.seek(0)
                            json.dump(report, out, indent=2)
                            out.truncate()
                            out.flush()
                    report['result'] = 'pass'
                finally:
                    board.pad(0)
        except Exception as exc:
            report['error'] = str(exc)
            raise
        finally:
            out.seek(0)
            json.dump(report, out, indent=2)
            out.write('\n')
            out.truncate()


if __name__ == '__main__':
    main()
