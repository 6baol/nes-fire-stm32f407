"""Subdirectories, UTF-8 names and a larger library through real ARM FatFs."""
import hashlib, json, sys
from sd_arm_harness import SdArm, ROOT, pack_files
from test_mmc1_axrom_arm import rom as make_rom

CHINESE = [
    '蝙蝠侠 - 幻想汉化 (CN).NES',
    '七龙珠Z 超武斗传5 - 卡圣 (CN).NES',
    '空中魂斗罗 - 金明汉化 (CN).NES',
    '红巾特工队 - 佛易汉化组 (CN).NES',
    '三国志英杰传 - 外星科技 (CN).NES',
    '少年游侠 - 外星科技 (CN).NES',
    '超级马里奥 - 无敌版 (CN).NES',
    '魂斗罗 - 力量 (CN).NES',
]


def build_files():
    files = pack_files()
    files.pop('TITLES.DB', None)          # this card names games by filename
    for name in ('FONT.MAP', 'FONT.HZK'):
        files[name] = (ROOT / 'Assets/fonts/cjk' / name).read_bytes()
    for i, name in enumerate(CHINESE):
        files[f'合集{i % 2}/' + name] = make_rom(0, prg16=2, chr8=1)
    for i in range(30):
        files['合集1/批量%02d.NES' % i] = make_rom(0, prg16=2, chr8=1)
    files['_归档/旧游戏.NES'] = make_rom(0, prg16=2, chr8=1)
    files['SAVES/存档.NES'] = make_rom(0, prg16=2, chr8=1)
    return files


def main():
    files = build_files()
    a = SdArm(files)
    assert a.boot() == 0
    names = a.names()
    expected = len(CHINESE) + 30 + len([n for n in files if n.lower().endswith(('.nes', '.fds')) and '/' not in n])
    assert a.call('NesLibrary_Count') == expected, (a.call('NesLibrary_Count'), expected)
    assert any(n.startswith('合集0/') for n in names)
    assert not any(n.startswith('_归档/') for n in names), 'underscore directory must be skipped'
    assert not any(n.lower().startswith('saves/') for n in names), 'SAVES must be skipped'
    for name in ('合集0/' + CHINESE[0], '合集1/' + CHINESE[1]):
        item = a.game_index(name)
        label = bytes(a.u.mem_read(a.r32(a.call('NesLibrary_Game', item)), 96)).split(b'\0')[0]
        assert label.decode('utf-8') == name.rsplit('/', 1)[1].rsplit('.', 1)[0], label
        a.call('NesLibrary_EnterMenu')
        assert a.call('NesLibrary_Load', item) == 0, name
    # Second boot reuses the on-card catalog: no rewrite, same listing.
    b = SdArm(files); b.disk = bytearray(a.disk)
    assert b.boot() == 0 and b.call('NesLibrary_Count') == expected
    assert b.blocks_written == 0
    assert b.names() == names

    report = {'result': 'PASS', 'hardware_tested': False, 'entries': expected,
              'checks': ['subdirectory ROMs are listed with their relative path',
                         'UTF-8 names survive FatFs and the catalog',
                         'directories starting with _ and SAVES are skipped',
                         'a game inside a subdirectory loads',
                         'second boot reuses CATALOG.IDX without rewriting it'],
              'axf_sha256': hashlib.sha256((ROOT / 'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT / 'Tests/nes_output/sd_utf8_results.json').write_text(json.dumps(report, indent=2))
    print('PASS', expected, 'entries;', len(CHINESE), 'Chinese names in subdirectories')


if __name__ == '__main__':
    main()
