"""Settings store and audio software gain against the actual Keil firmware.

SETTINGS.BIN is exercised through ARM FatFs on the synthetic FAT32 card; the
audio path runs the real NesAudio_Render with only the APU sample source
stubbed, so the Q8 gain arithmetic is what the board runs.
"""
import hashlib
import json
import struct
import zlib

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_LR, UC_ARM_REG_PC, UC_ARM_REG_R0, UC_ARM_REG_R1

from test_mmc3_arm import NesArm, ROOT
from sd_arm_harness import SdArm


def read_file(arm, path, size=64):
    fil, name, got, buf = 0x6c100000, 0x6c100400, 0x6c100800, 0x6c080000
    arm.u.mem_write(name, path.encode() + b'\0')
    assert arm.call('f_open', fil, name, 1) == 0
    assert arm.call('f_read', fil, buf, size, got) == 0
    data = bytes(arm.u.mem_read(buf, arm.r32(got)))
    assert arm.call('f_close', fil) == 0
    return data


def write_file(arm, path, payload):
    fil, name, got = 0x6c100000, 0x6c100400, 0x6c100800
    arm.u.mem_write(name, path.encode() + b'\0')
    assert arm.call('f_open', fil, name, 10) == 0
    arm.u.mem_write(0x6c080000, payload)
    assert arm.call('f_write', fil, 0x6c080000, len(payload), got) == 0
    assert arm.r32(got) == len(payload)
    assert arm.call('f_close', fil) == 0


def settings(arm, addr, version, landscape, volume, output):
    arm.u.mem_write(addr, bytes((version, landscape, volume, output)))


def persisted(landscape, volume, output, version=1):
    body = bytes((version, landscape, volume, output))
    return body + struct.pack('<I', zlib.crc32(body) & 0xffffffff)


def settings_store():
    arm = SdArm()
    assert arm.boot() == 0
    buf = 0x6c100f00
    assert arm.call('NesLibrary_LoadSettings', buf) == 0, 'missing file must not load'
    assert arm.call('NesLibrary_SaveSettings', 0) == 0xffffffff, 'null settings must be rejected'

    settings(arm, buf, 1, 1, 55, 0)
    assert arm.call('NesLibrary_SaveSettings', buf) == 0
    raw = read_file(arm, '0:/NES/SETTINGS.BIN', 8)
    assert len(raw) == 8 and raw == persisted(1, 55, 0), raw
    assert arm.call('NesLibrary_LoadSettings', buf) == 1
    assert bytes(arm.u.mem_read(buf, 4)) == bytes((1, 1, 55, 0))

    # Out-of-range writes are clamped on the way in.
    settings(arm, buf, 1, 2, 200, 3)
    assert arm.call('NesLibrary_SaveSettings', buf) == 0
    assert read_file(arm, '0:/NES/SETTINGS.BIN', 8) == persisted(1, 100, 2)

    # A damaged record is ignored rather than applied.
    for bad in (persisted(1, 55, 0)[:4] + b'\0\0\0\0',
                persisted(0, 55, 0, version=2),
                persisted(2, 55, 0),
                persisted(0, 101, 0),
                persisted(0, 55, 3)):
        write_file(arm, '0:/NES/SETTINGS.BIN', bad)
        assert arm.call('NesLibrary_LoadSettings', buf) == 0, bad

    write_file(arm, '0:/NES/SETTINGS.BIN', b'SHORT')
    assert arm.call('NesLibrary_LoadSettings', buf) == 0

    write_file(arm, '0:/NES/SETTINGS.BIN', persisted(1, 0, 2))
    assert arm.call('NesLibrary_LoadSettings', buf) == 1
    assert bytes(arm.u.mem_read(buf, 4)) == bytes((1, 1, 0, 2))

    # A card write error only loses persistence: the truncated record fails the
    # CRC/length check and the next boot uses the built-in defaults.
    settings(arm, buf, 1, 0, 30, 1)
    arm.write_error = True
    assert arm.call('NesLibrary_SaveSettings', buf) == 0xffffffff
    arm.write_error = False
    assert arm.call('NesLibrary_LoadSettings', buf) == 0, 'damaged record was applied'
    settings(arm, buf, 1, 1, 0, 2)
    assert arm.call('NesLibrary_SaveSettings', buf) == 0
    assert arm.call('NesLibrary_LoadSettings', buf) == 1
    assert bytes(arm.u.mem_read(buf, 4)) == bytes((1, 1, 0, 2))

    empty = SdArm({})
    assert empty.boot() != 0
    assert empty.call('NesLibrary_LoadSettings', buf) == 0
    assert empty.call('NesLibrary_SaveSettings', buf) == 0xffffffff


def audio_gain():
    arm = NesArm()
    arm.u.mem_map(0x40000000, 0x30000)
    assert arm.call('NesAudio_GetVolume') == 70, 'default volume changed'

    calls = [0]

    def apu(uc, address, size, data):
        count = uc.reg_read(UC_ARM_REG_R1)
        uc.mem_write(uc.reg_read(UC_ARM_REG_R0), bytes([192]) * count)
        calls[0] += 1
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    handle = arm.u.hook_add(UC_HOOK_CODE, apu,
                            begin=arm.addr('apu_process') & ~1,
                            end=arm.addr('apu_process') & ~1)

    def render(volume):
        arm.call('NesAudio_SetVolume', volume)
        arm.u.mem_write(0x40026004, struct.pack('<I', 0x10))
        arm.call('DMA1_Stream4_IRQHandler')
        left, right = struct.unpack('<hh', arm.u.mem_read(arm.addr('dma_pcm'), 4))
        assert left == right, 'mono sample was not duplicated'
        return left

    # (192-128)*128 = 8192 before gain; gain is round(volume*256/100).
    assert render(100) == 8192
    assert render(50) == 4096
    assert render(70) == 5728
    assert render(0) == 0
    assert arm.call('NesAudio_GetVolume') == 0
    assert render(101) == 8192, 'volume must clamp to 100'
    assert arm.call('NesAudio_GetVolume') == 100
    assert calls[0] == 5, 'volume 0 must still drain the APU'

    arm.u.hook_del(handle)


def main():
    settings_store()
    audio_gain()
    report = {
        'result': 'PASS',
        'scope': 'ARM FatFs settings record and NesAudio_Render gain, no board',
        'checks': [
            'missing/short/corrupt SETTINGS.BIN ignored',
            'version, orientation, volume and output validated',
            'out-of-range values clamped before write',
            'card write error only loses persistence; a later save recovers',
            'no card reports no persistence without failing runtime',
            'default volume 70, 0/50/70/100/101 gain mapping',
            'volume 0 still drains the APU queue',
        ],
        'axf_sha256': hashlib.sha256((ROOT / 'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest(),
    }
    out = ROOT / 'Tests/nes_output'
    out.mkdir(exist_ok=True)
    (out / 'settings_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
