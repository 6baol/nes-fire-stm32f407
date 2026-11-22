"""Search/filter over the on-card catalog through the real ARM firmware."""
import hashlib, json, sys
from sd_arm_harness import SdArm, ROOT, pack_files

Q = 0x2001c400


def put(a, text):
    a.u.mem_write(Q, text.encode('utf-8') + b'\0')
    return Q


def file_data(a, path):
    fil = 0x6c100000
    name = fil + 1024
    got = fil + 2048
    a.u.mem_write(name, path.encode() + b'\0')
    assert a.call('f_open', fil, name, 1) == 0
    assert a.call('f_read', fil, 0x6c0a0000, 32, got) == 0
    header = bytes(a.u.mem_read(0x6c0a0000, 32))
    count = int.from_bytes(header[8:12], 'little')
    size = 32 + count * 312
    rest = size - 32
    if rest:
        assert a.call('f_read', fil, 0x6c0a0000 + 32, rest, got) == 0
        assert a.r32(got) == rest
    data = bytes(a.u.mem_read(0x6c0a0000, size))
    assert a.call('f_close', fil) == 0
    return data


def write_file(a, path, payload):
    fil = 0x6c100000
    name = fil + 1024
    got = fil + 2048
    a.u.mem_write(name, path.encode() + b'\0')
    assert a.call('f_open', fil, name, 10) == 0
    a.u.mem_write(0x6c0a0000, payload)
    assert a.call('f_write', fil, 0x6c0a0000, len(payload), got) == 0
    assert a.r32(got) == len(payload)
    assert a.call('f_close', fil) == 0


def main():
    files = pack_files()
    files.pop('TITLES.DB', None)
    a = SdArm(files)
    assert a.boot() == 0
    total = a.call('NesLibrary_Count')
    assert total == len([n for n in files if n.lower().endswith(('.nes', '.fds'))])

    # ASCII substring, case-insensitive, over the English part of the label.
    hits = a.call('NesLibrary_Search', put(a, 'mario'))
    assert hits == 3, hits
    assert a.call('NesLibrary_Count') == 3
    names = a.names()
    assert all('MARIO' in n.upper() for n in names), names
    assert a.call('NesLibrary_ViewActive') == 1
    # A filtered entry still loads through the view index.
    assert a.call('NesLibrary_Load', 0) == 0

    # The legacy sidecar can match one title while dropping other valid hits.
    # A correct search produces the same results with or without that file.
    order = sorted(n for n in files if n.lower().endswith(('.nes', '.fds')))
    blob = bytearray(b'NESIDX1\0' + len(order).to_bytes(4, 'little'))
    for i, name in enumerate(order):
        key = b'mario' if 'Mario' in name and 'World' in name else b'zzz'
        blob += i.to_bytes(2, 'little') + key.ljust(24, b'\0')
    write_file(a, '0:/NES/SEARCH.IDX', bytes(blob))
    assert a.call('NesLibrary_Search', put(a, 'mario')) == 3
    assert a.call('NesLibrary_Count') == 3
    # A sidecar from a different library is ignored, not trusted.
    stale = bytearray(b'NESIDX1\0' + (2).to_bytes(4, 'little'))
    stale += (0).to_bytes(2, 'little') + b'zzz'.ljust(24, b'\0')
    stale += (1).to_bytes(2, 'little') + b'zzz'.ljust(24, b'\0')
    write_file(a, '0:/NES/SEARCH.IDX', bytes(stale))
    assert a.call('NesLibrary_Search', put(a, 'mario')) == 3   # falls back to the catalog

    # Chinese substring matches UTF-8 bytes exactly.
    cjk = pack_files()
    cjk['中文游戏 - 测试 (CN).NES'] = cjk['Super Mario Bros. (World).nes']
    cjk.pop('TITLES.DB', None)
    b = SdArm(cjk)
    assert b.boot() == 0
    assert b.call('NesLibrary_Search', put(b, '中文')) == 1
    assert b.names() == ['中文游戏 - 测试 (CN).NES']

    # Pinyin: tools/make_pinyin.py fills the record field; the firmware matches it.
    cjk_files = {
        '蝙蝠侠 - 幻想汉化 (CN).NES': cjk['中文游戏 - 测试 (CN).NES'],
        'Super Mario Bros. (World).nes': cjk['Super Mario Bros. (World).nes'],
    }
    c = SdArm(cjk_files)
    assert c.boot() == 0
    catalog = bytearray(file_data(c, '0:/NES/CATALOG.IDX'))
    marker = '蝙蝠侠'.encode('utf-8')
    idx = catalog.find(marker)
    assert idx > 0, 'catalog has no Chinese path'
    rec = 32 + ((idx - 12) // 312) * 312
    catalog[rec + 270:rec + 310] = b'bianfuxia bfx'.ljust(40, b'\0')
    write_file(c, '0:/NES/CATALOG.IDX', bytes(catalog))
    write_file(c, '0:/NES/SEARCH.IDX', b'NESIDX1\0\x02\0\0\0' +
               b'\0\0' + b'english label'.ljust(24, b'\0') +
               b'\x01\0' + b'mario'.ljust(24, b'\0'))
    assert c.boot() == 0
    assert c.call('NesLibrary_Search', put(c, 'bian')) == 1, c.names()
    assert '蝙蝠侠' in c.names()[0]
    assert c.call('NesLibrary_Search', put(c, 'bfx')) == 1
    assert c.call('NesLibrary_Search', put(c, 'mario')) == 1
    assert c.call('NesLibrary_Load', 0) == 0

    # No match restores the full list instead of an empty menu.
    assert a.call('NesLibrary_Search', put(a, 'zzzz')) == 0
    assert a.call('NesLibrary_SearchFailed') == 0
    assert a.call('NesLibrary_ViewActive') == 0
    assert a.call('NesLibrary_Count') == total

    # An empty query is the same as clearing.
    assert a.call('NesLibrary_Search', put(a, 'mario')) == 3
    assert a.call('NesLibrary_Search', put(a, '')) == 0
    assert a.call('NesLibrary_Count') == total
    a.io_error = True
    assert a.call('NesLibrary_Search', put(a, 'mario')) == 0
    assert a.call('NesLibrary_SearchFailed') == 1
    a.io_error = False
    assert a.call('NesLibrary_Search', put(a, 'mario')) == 3
    assert a.call('NesLibrary_SearchFailed') == 0

    report = {'result': 'PASS', 'hardware_tested': False, 'entries': total,
              'checks': ['case-insensitive ASCII search', 'UTF-8 substring search',
                         'filtered view drives Count/Game/Load', 'no match restores the full list',
                         'empty query clears the filter'],
              'axf_sha256': hashlib.sha256((ROOT / 'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    (ROOT / 'Tests/nes_output/search_results.json').write_text(json.dumps(report, indent=2))
    print(f'PASS search: {total} entries, mario -> 3, CJK -> 1')


if __name__ == '__main__':
    main()
