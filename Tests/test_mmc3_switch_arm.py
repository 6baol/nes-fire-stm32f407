"""Check SMB3 -> SMB1 -> SMB2 FDS -> SMB3 dispatch/IRQ restoration on ARM."""
import json
import sys

from test_mmc3_arm import NesArm, ROOT, SCRATCH

sys.path.insert(0, str(ROOT / 'tools'))
import embed_roms  # noqa: E402

OUT = ROOT / 'Tests/nes_output'


def dispatch(arm):
    cpu = arm.addr('cpu_data')
    reads = [arm.r32(cpu + (1 + index) * 4) for index in range(3, 7)]
    writes = [arm.r32(cpu + (9 + index) * 4) for index in range(3, 7)]
    maps = [arm.r32(cpu + (17 + index) * 4) for index in range(3, 8)]
    return reads, writes, maps


def pc(arm):
    cpu = arm.addr('cpu_data')
    return (arm.r32(cpu + 124) - arm.r32(cpu + 132)) & 0xFFFF


def main():
    smb3 = (ROOT / 'Roms/SMB3.nes').read_bytes()
    smb1 = embed_roms.normalize((ROOT / 'Roms/smb.nes').read_bytes())
    fds = (ROOT / 'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes()
    bios = (ROOT / 'Roms/disksys.rom').read_bytes()
    arm = NesArm()
    stages = []

    assert arm.load(smb3) == 0
    assert arm.r32(arm.addr('MapperNo')) == 4
    assert pc(arm) == 0xFF40
    normal = dispatch(arm)
    arm.mapper_write(0xC000, 0)
    arm.mapper_write(0xC001, 0)
    arm.mapper_write(0xE001, 0)
    arm.hsync()
    assert arm.read8(arm.addr('cpuirq')) == 1
    arm.mapper_write(0xA001, 0)
    stages.append('SMB3 IRQ pending and SRAM disabled')

    rc = arm.load(smb1)
    assert rc == 0, f'SMB1 load after SMB3 failed with rc={rc}'
    assert arm.r32(arm.addr('MapperNo')) == 0
    assert arm.read8(arm.addr('cpuirq')) == 0, 'MMC3 IRQ leaked into SMB1'
    current = dispatch(arm)
    assert current[:2] == normal[:2], 'SMB1 did not restore cartridge SRAM dispatch'
    assert current[2][0] == normal[2][0], 'SMB1 $6000 mapping is stale'
    for _ in range(2):
        arm.call('Nes_Frame', 0)
    assert arm.r32(arm.addr('nes_faults')) == 0
    stages.append('SMB1 normal cartridge dispatch')

    arm.u.mem_write(SCRATCH, fds)
    arm.u.mem_write(0x6C090000, bios)
    assert arm.call('Nes_LoadDisk', SCRATCH, len(fds), 0x6C090000, len(bios)) == 0
    assert arm.r32(arm.addr('MapperNo')) == 20
    fds_dispatch = dispatch(arm)
    assert fds_dispatch[:2] != normal[:2], 'FDS did not install PRG RAM handlers'
    assert fds_dispatch[2][0] != normal[2][0], 'FDS did not replace $6000 mapping'
    for _ in range(2):
        arm.call('Nes_Frame', 0)
    assert arm.r32(arm.addr('nes_faults')) == 0
    stages.append('SMB2 FDS PRG RAM dispatch')

    assert arm.load(smb3) == 0
    assert arm.r32(arm.addr('MapperNo')) == 4
    assert pc(arm) == 0xFF40, 'SMB3 reset vector did not use restored fixed bank'
    assert arm.read8(arm.addr('cpuirq')) == 0, 'FDS IRQ leaked into SMB3'
    assert arm.read8(arm.addr('mmc3_irq_enabled')) == 0
    assert arm.read8(arm.addr('mmc3_irq_pending')) == 0
    assert arm.read8(arm.addr('mmc3_sram_control')) == 0x80
    restored = dispatch(arm)
    assert restored[:2] == normal[:2], 'FDS PRG RAM handlers leaked into SMB3'
    assert restored[2][0] == normal[2][0], 'FDS $6000 mapping leaked into SMB3'
    for _ in range(2):
        arm.call('Nes_Frame', 0)
    assert arm.r32(arm.addr('nes_faults')) == 0
    stages.append('SMB3 restored with cleared IRQ and writable SRAM')

    report = {
        'result': 'PASS',
        'sequence': ['SMB3', 'SMB1', 'SMB2 FDS', 'SMB3'],
        'checks': stages,
        'cpu_faults': 0,
        'scope': 'actual Keil ARM instructions under Unicorn; not a board test',
        'hardware_tested': False,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / 'mmc3_switch_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
