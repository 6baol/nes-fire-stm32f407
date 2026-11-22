"""Check Mapper 16 boards and large-ROM capture bounds on the built ARM firmware."""
import struct
import sys

from sd_arm_harness import SdArm
from test_mmc3_arm import NesArm, ROOT, make_mmc3_rom

sys.path.insert(0, str(ROOT / 'tools'))
from embed_roms import classify_header


def mapper16_rom(submapper):
    base = 0x6000 if submapper == 4 else 0x8000
    wrong = 0x8000 if submapper == 4 else 0x6000
    # Execute from the fixed bank. A write in the wrong register window must
    # leave $8000 unchanged. The valid register alias must select PRG bank 1.
    code = bytes((0xA9, 1, 0x8D, 0x18, wrong >> 8, 0xAD, 0, 0x80, 0x85, 0x10,
                  0xA9, 1, 0x8D, 0x18, base >> 8, 0xAD, 0, 0x80, 0x85, 0x11,
                  0xAD, 0xFF, 0x7F, 0x85, 0x12, 0x4C, 0x19, 0xC0))
    prg = bytearray(4 * 0x4000)
    for bank in range(4):
        prg[bank * 0x4000] = 0x40 + bank
    prg[-0x4000:-0x4000 + len(code)] = code
    prg[-6:] = struct.pack('<HHH', 0xC000, 0xC000, 0xC000)
    chr_rom = b''.join(bytes((bank,)) * 1024 for bank in range(8))
    return b'NES\x1a' + bytes((4, 1, 0, 0x18, submapper << 4)) + bytes(7) + prg + chr_rom


def verify_cpu(board):
    board.call('run6502', 100 * 256)
    ram = board.r32(board.addr('NES_RAM'))
    assert bytes(board.u.mem_read(ram + 0x10, 3)) == b'\x40\x41\0'
    assert board.r32(board.addr('nes_faults')) == 0


def check_irq(board, submapper):
    via = 'asm_Mapper_WriteLow' if submapper == 4 else 'asm_Mapper_Write'
    base = 0x6000 if submapper == 4 else 0x8000
    start = board.r32(board.addr('clocks'))
    board.call(via, 2, base + 0x0B)
    board.call(via, 0, base + 0x0C)
    board.call(via, 1, base + 0x0A)
    board.u.mem_write(board.addr('clocks'), struct.pack('<I', start + 2))
    board.call('MAP16_UpdateIRQ')
    assert board.read8(board.addr('cpuirq')) == 0
    board.u.mem_write(board.addr('clocks'), struct.pack('<I', start + 3))
    board.call('MAP16_UpdateIRQ')
    assert board.read8(board.addr('cpuirq')) == 1
    board.call(via, 0, base + 0x0A)
    assert board.read8(board.addr('cpuirq')) == 0


def check_import_parity(board):
    raw = mapper16_rom(4)
    header = raw[:16]
    cases = [(header, len(raw)), (header, len(raw) - 1), (b'bad header' + bytes(6), len(raw))]
    for offset, value in ((6, 2), (6, 4), (6, 8), (7, 0x19), (8, 0xA4), (10, 0x20), (12, 1)):
        changed = bytearray(header)
        changed[offset] = value
        cases.append((bytes(changed), len(raw)))
    cases.append((b'NES\x1a' + bytes((4, 1, 0x30, 0)) + bytes(8), len(raw)))
    cases.append((b'FDS\x1a\x02' + bytes(11), 16 + 2 * 65500))
    for h, size in cases:
        source, result = 0x6C080000, 0x6C080020
        board.u.mem_write(source, h)
        status = board.call('NesImport_Header', source, size, result)
        _, mapper, submapper, fds = struct.unpack('<IHBB', board.u.mem_read(result, 8))
        host = classify_header(h, size)
        assert struct.unpack('<i', struct.pack('<I', status))[0] == host.status
        assert (mapper, submapper, bool(fds)) == (host.mapper, host.submapper, host.fds)
        if not host.status and not fds:
            assert bytes(board.u.mem_read(result + 10, 16)) == host.header


def main():
    arm = NesArm()
    check_import_parity(arm)
    print('PASS firmware and PC header classifications match')
    for submapper in (4, 5):
        raw = mapper16_rom(submapper)
        assert arm.load(raw) == 0
        verify_cpu(arm)
        check_irq(arm, submapper)
        print(f'PASS Mapper 16.{submapper} CPU register routing and IRQ')

    raw = mapper16_rom(5)
    for offset, flag in ((6, 2), (10, 0x20)):
        rejected = bytearray(raw)
        rejected[offset] = flag
        assert arm.load(bytes(rejected)) == 11
    legacy = bytearray(raw)
    legacy[7:9] = b'\x10\0'
    assert arm.load(bytes(legacy)) == 11
    print('PASS EEPROM and unidentified legacy boards rejected')

    paged = bytearray(mapper16_rom(4))
    paged[16:21] = bytes.fromhex('a9 01 8d 08 60')
    paged[16 + 0x4000 + 5:16 + 0x4000 + 12] = bytes.fromhex('a9 42 85 10 4c 09 80')
    paged[16 + 0x10000 - 4:16 + 0x10000 - 2] = struct.pack('<H', 0x8000)
    assert arm.load(bytes(paged)) == 0
    arm.call('run6502', 100 * 256)
    assert arm.read8(arm.r32(arm.addr('NES_RAM')) + 0x10) == 0x42
    print('PASS low register can switch the currently executing PRG bank')

    sd = SdArm({'FCG.NES': mapper16_rom(4)})
    assert sd.boot() == 0
    assert sd.call('NesLibrary_Load', sd.game_index('FCG.NES')) == 0
    verify_cpu(sd)
    print('PASS NES 2.0 subtype survives the FAT32 load path')

    rom_address = 0x6C022000
    large = make_mmc3_rom(chr_banks=256)
    arm.u.mem_write(rom_address, large)
    assert arm.call('Nes_Load', rom_address, len(large)) == 0
    check = 'Nes_CaptureRangeAvailable'
    assert arm.call(check, 0x6C040000, 256 * 240 * 2) == 0
    assert arm.call(check, rom_address + len(large), 2) == 1
    assert arm.call(check, rom_address - 2, 2) == 1
    assert arm.call(check, rom_address - 2, 3) == 0
    print('PASS large-CHR capture overlap and exact range boundaries')


if __name__ == '__main__':
    main()
