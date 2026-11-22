"""Regression for the ARM library, using only the synthetic FAT32 disk."""
from pathlib import Path
import tempfile

from sd_arm_harness import SdArm, pack_files
from test_search_arm import file_data, put, write_file
from prepare_library import inspect_catalog

ALL, COMPATIBLE, UNSUPPORTED, FAVORITES, RECENT = range(5)


def set_filter(arm, mode):
    arm.call('NesLibrary_SetFilter', mode)
    for _ in range(2 * arm.call('NesLibrary_FilterPending')):
        if not arm.call('NesLibrary_FilterPending'):
            break
        arm.call('NesLibrary_AdvanceFilter')
    assert arm.call('NesLibrary_FilterPending') == 0
    return arm.call('NesLibrary_Count')


def main():
    sample = pack_files()['Super Mario Bros. (World).nes']
    files = {
        '01 Mario (USA).nes': sample,
        '02 Mario - bad mapper.nes': sample[:6] + bytes([0x90]) + sample[7:],
        'famicom/03 勇者 - Densetsu e... (Japan).NeS': sample,
        '_LEGACY/ignored.NES': sample,
    }
    arm = SdArm(files)
    assert arm.boot() == 0
    assert len(arm.names()) == 3
    mario, bad, quest = arm.names()
    assert 'e...' in quest
    assert arm.call('NesLibrary_Compatibility', 1, 0, 0) == 0
    assert arm.call('NesLibrary_SetFilter', COMPATIBLE) == 0
    assert arm.call('NesLibrary_FilterPending') == 3
    arm.call('NesLibrary_AdvanceFilter')
    assert arm.call('NesLibrary_FilterPending') == 1
    arm.call('NesLibrary_SetFilter', ALL)
    assert arm.call('NesLibrary_FilterPending') == 0
    assert arm.names() == [mario, bad, quest]
    assert set_filter(arm, COMPATIBLE) == 2
    assert arm.names() == [mario, quest]
    assert arm.call('NesLibrary_Search', put(arm, 'mario')) == 1
    assert arm.names() == [mario]
    assert arm.call('NesLibrary_Search', put(arm, 'missing')) == 0
    assert arm.names() == [mario, quest]
    set_filter(arm, UNSUPPORTED)
    assert arm.names() == [bad]
    mapper = 0x6c100f00
    assert arm.call('NesLibrary_Compatibility', 0, 0, mapper) == 0xFFFFFFFE
    assert arm.r32(mapper) == 9

    with tempfile.TemporaryDirectory() as temp:
        rom_root = Path(temp)
        for name, data in files.items():
            path = rom_root / name
            path.parent.mkdir(exist_ok=True)
            path.write_bytes(data)
        _, rows, sidecar = inspect_catalog(rom_root, file_data(arm, '0:/NES/CATALOG.IDX'))
        assert [(row['status'], row['mapper']) for row in rows] == [(1, 0), (-2, 9), (1, 0)]
    write_file(arm, '0:/NES/COMPAT.IDX', sidecar)
    assert arm.boot() == 0
    before = arm.blocks_read
    assert arm.call('NesLibrary_Compatibility', 1, 0, mapper) == 0xFFFFFFFE
    assert arm.blocks_read == before and arm.r32(mapper) == 9
    assert arm.call('NesLibrary_SetFilter', UNSUPPORTED) == 1
    assert arm.call('NesLibrary_FilterPending') == 0
    assert arm.names() == [bad]
    invalid = sidecar[:-1] + bytes([sidecar[-1] ^ 1])
    write_file(arm, '0:/NES/COMPAT.IDX', invalid)
    assert arm.boot() == 0
    assert arm.call('NesLibrary_Compatibility', 1, 0, mapper) == 0

    catalog = file_data(arm, '0:/NES/CATALOG.IDX')
    recovery = SdArm({**files, 'CATALOG.IDX': b'INCOMPLETE', 'CATALOG.BAK': catalog})
    assert recovery.boot() == 0
    assert recovery.names() == [mario, bad, quest]
    assert recovery.blocks_written == 0
    stale = sidecar[:12] + b'\0\0\0\0' + sidecar[16:]
    write_file(arm, '0:/NES/COMPAT.IDX', stale)
    assert arm.boot() == 0
    assert arm.call('NesLibrary_Compatibility', 1, 0, mapper) == 0

    assert arm.call('NesLibrary_ToggleFavorite', 2) == 1
    assert arm.call('NesLibrary_IsFavorite', 2) == 1
    assert arm.call('NesLibrary_Load', 0) == 0
    live_rom = bytes(arm.u.mem_read(0x6c060000, len(sample)))
    assert arm.call('NesLibrary_RecordPlayed', 0) == 0
    assert bytes(arm.u.mem_read(0x6c060000, len(sample))) == live_rom
    arm.call('NesLibrary_EnterMenu')
    assert arm.call('NesLibrary_Load', 2) == 0
    assert arm.call('NesLibrary_RecordPlayed', 2) == 0
    assert arm.boot() == 0
    arm.call('NesLibrary_SetFilter', RECENT)
    assert arm.names() == [quest, mario]
    arm.call('NesLibrary_SetFilter', FAVORITES)
    assert arm.names() == [quest]

    # Slot 0 is newest after three writes. A corrupt slot falls back to slot 1.
    write_file(arm, '0:/NES/PREFS0.DAT', b'POWER LOSS')
    assert arm.boot() == 0
    arm.call('NesLibrary_SetFilter', RECENT)
    assert arm.names() == [mario]
    arm.call('NesLibrary_SetFilter', FAVORITES)
    assert arm.names() == [quest]
    assert arm.call('NesLibrary_ToggleFavorite', 0) == 0
    assert not arm.names()
    assert arm.boot() == 0
    arm.call('NesLibrary_SetFilter', FAVORITES)
    assert not arm.names()

    overflow = SdArm({f'R{i:04}.NES': b'\0' * 16 for i in range(2050)})
    assert overflow.boot() == 0
    assert overflow.call('NesLibrary_Count') == 2048
    assert overflow.call('NesLibrary_OverflowCount') == 2
    assert overflow.call('NesLibrary_Search', put(overflow, 'R2047')) == 1
    assert overflow.names() == ['R2047.NES']
    assert overflow.boot() == 0
    assert overflow.call('NesLibrary_OverflowCount') == 2

    print('PASS full-path catalog, compatibility + search, metadata, preferences, and 2048-entry cap')


if __name__ == '__main__':
    main()
