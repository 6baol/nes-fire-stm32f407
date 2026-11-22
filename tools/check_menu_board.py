"""Board check for the game menu: reset, read the menu state, then start the
selected game through the SWD test pad and confirm frames are running.

    python tools/check_menu_board.py            # menu state only
    python tools/check_menu_board.py --start    # also press A via SWD
"""
import argparse, json, struct, time
from pathlib import Path
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

root = Path(__file__).resolve().parents[1]


def symbols():
    with (root / 'Project/Output/Fire_F407ZG.axf').open('rb') as f:
        return {s.name: s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--start', action='store_true', help='press A via nes_test_pad after reading the menu')
    p.add_argument('--frequency', type=int, default=1000000)
    a = p.parse_args()
    sym = symbols()
    pack = next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
    options = {'target_override': 'stm32f407zgtx', 'pack': [str(pack)], 'frequency': a.frequency,
               'connect_mode': 'attach', 'auto_unlock': False, 'resume_on_disconnect': True,
               'cache.enable_memory': False, 'cmsis_dap.limit_packets': True,
               'cmsis_dap.deferred_transfers': False}
    report = {}
    with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000', options=options) as session:
        t = session.target
        t.reset()
        time.sleep(3)
        t.halt()
        idx, cnt, first, audio, touch = struct.unpack('<hBBBB', bytes(t.read_memory_block8(sym['menu'], 6)))
        report['menu'] = {'app_state': t.read8(sym['app_state']), 'index': idx, 'count': cnt,
                          'first': first, 'audio_ok': audio, 'touch_ok': touch,
                          'games_embedded': t.read32(sym['nes_rom_image_count']),
                          'faults': t.read32(sym['nes_faults']),
                          'logic_total': t.read32(sym['nes_logic_total'])}
        report['menu']['pc'] = hex(t.read_core_register('pc'))
        report['menu']['cfsr'] = hex(t.read32(0xe000ed28))
        t.resume()
        print('MENU', json.dumps(report['menu']), flush=True)
        if a.start:
            t.halt(); t.write8(sym['nes_test_pad'], 1); t.resume()
            time.sleep(0.3)
            t.halt(); t.write8(sym['nes_test_pad'], 0); t.resume()
            time.sleep(4)
            t.halt()
            report['game'] = {'app_state': t.read8(sym['app_state']),
                              'faults': t.read32(sym['nes_faults']),
                              'logic_total': t.read32(sym['nes_logic_total']),
                              'draw_total': t.read32(sym['nes_draw_total']),
                              'logic_hz': t.read32(sym['nes_logic_hz']),
                              'draw_hz': t.read32(sym['nes_draw_hz']),
                              'pc': hex(t.read_core_register('pc')),
                              'cfsr': hex(t.read32(0xe000ed28))}
            t.resume()
            print('GAME', json.dumps(report['game']), flush=True)
    (root / 'Release' / 'board_menu_v0.9.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    ok = report['menu']['app_state'] == 0 and report['menu']['count'] >= 1 and report['menu']['faults'] == 0
    if a.start:
        ok = ok and report['game']['app_state'] == 1 and report['game']['logic_total'] > 0
    print('RESULT:', 'PASS' if ok else 'FAIL')
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
