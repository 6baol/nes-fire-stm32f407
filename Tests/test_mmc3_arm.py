"""Mapper 4 tests against the actual Keil ARM firmware in Unicorn."""
from pathlib import Path
import struct
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_MODE_MCLASS, UC_HOOK_CODE
from unicorn.arm_const import *

ROOT = Path(__file__).resolve().parents[1]
SCRATCH = 0x6C080000
STOP = 0x080FF000


def make_mmc3_rom(prg_banks=8, chr_banks=16):
    prg = bytearray([0xEA]) * (prg_banks * 0x2000)
    chr_data = bytearray(chr_banks * 0x400)
    for bank in range(chr_banks):
        chr_data[bank * 0x400:(bank + 1) * 0x400] = bytes([bank]) * 0x400
    for bank in range(prg_banks):
        prg[bank * 0x2000 + 0x100] = bank
    # Reset selects bank 0 at $8000 and jumps into it.  Bank 0 replaces itself
    # with bank 2; the continuation at $800A exists only in bank 2.
    prg[-0x2000:-0x2000 + 13] = bytes.fromhex(
        'a9 00 8d 00 80 a9 00 8d 01 80 4c 00 80')
    prg[0:10] = bytes.fromhex('a9 06 8d 00 80 a9 02 8d 01 80')
    prg[2 * 0x2000 + 0x0A:2 * 0x2000 + 0x11] = bytes.fromhex(
        'a9 42 85 10 4c 0e 80')
    prg[-6:] = struct.pack('<HHH', 0xE000, 0xE000, 0xE000)
    header = b'NES\x1a' + bytes([prg_banks // 2, chr_banks // 8, 0x40, 0]) + bytes(8)
    return bytes(header + prg + chr_data)


class NesArm:
    def __init__(self):
        self.u = Uc(UC_ARCH_ARM, UC_MODE_THUMB | UC_MODE_MCLASS)
        for base, size in [(0x08000000, 0x100000), (0x20000000, 0x20000),
                           (0x10000000, 0x10000), (0x6C000000, 0x100000),
                           (0xE0000000, 0x100000)]:
            self.u.mem_map(base, size)
        self.u.mem_write(0xE000ED88, struct.pack('<I', 0x00F00000))
        with (ROOT / 'Project/Output/Fire_F407ZG.axf').open('rb') as stream:
            elf = ELFFile(stream)
            for section in elf.iter_sections():
                if (section['sh_flags'] & 2 and section['sh_type'] != 'SHT_NOBITS'
                        and section['sh_size']):
                    self.u.mem_write(section['sh_addr'], section.data())
            self.symbols = {s.name: s['st_value']
                            for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
        self.u.mem_write(STOP, b'\x00\xbe')
        self.line_count = 0
        self.input_hook=self.u.hook_add(UC_HOOK_CODE, self._skip, begin=self.addr('NesPort_Input') & ~1,
                        end=self.addr('NesPort_Input') & ~1)
        self.u.hook_add(UC_HOOK_CODE, self._line, begin=self.addr('NesPort_Line') & ~1,
                        end=self.addr('NesPort_Line') & ~1)

    def addr(self, name):
        return self.symbols[name]

    def _skip(self, uc, address, size, data):
        uc.reg_write(UC_ARM_REG_PC, uc.reg_read(UC_ARM_REG_LR))

    def _line(self, uc, address, size, data):
        self.line_count += 1
        self._skip(uc, address, size, data)

    def call(self, name, *args):
        return self.invoke(self.addr(name), name, *args)

    def invoke(self, address, label, *args):
        self.u.reg_write(UC_ARM_REG_SP, 0x2001FFF0)
        self.u.reg_write(UC_ARM_REG_LR, STOP | 1)
        for reg, value in zip([UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2, UC_ARM_REG_R3], args):
            self.u.reg_write(reg, value)
        self.u.emu_start(address | 1, STOP, count=30000000)
        if self.u.reg_read(UC_ARM_REG_PC) != STOP:
            raise RuntimeError('Instruction budget exhausted in ' + label)
        return self.u.reg_read(UC_ARM_REG_R0)

    def load(self, rom):
        self.u.mem_write(SCRATCH, rom)
        return self.call('Nes_Load', SCRATCH, len(rom))

    def r32(self, address):
        return struct.unpack('<I', self.u.mem_read(address, 4))[0]

    def read8(self, address):
        return self.u.mem_read(address, 1)[0]

    def mapper_write(self, address, data):
        return self.call('asm_Mapper_Write', data, address)

    def cpu_read(self, address):
        table = self.addr('cpu_data') + (17 + (address >> 13)) * 4
        return self.read8(self.r32(table) + address)

    def ppu_bank(self, index, decoded=False):
        # ppu_data's fixed ARM layout: pointers follow its 4 KiB nametables.
        offset = 4160 + (12 if decoded else 0) * 4 + index * 4
        return self.r32(self.r32(self.addr('ppu')) + offset)

    def hsync(self, scanline=0):
        mapper = self.r32(self.addr('NES_Mapper'))
        callback = self.r32(mapper + 20)
        return self.invoke(callback, 'MAPPER.HSync', scanline)


def test_mmc3_loader(arm):
    rom = make_mmc3_rom()
    assert arm.load(rom) == 0, 'valid Mapper 4 iNES image was rejected'


def test_prg_live_switch(arm):
    assert arm.load(make_mmc3_rom()) == 0
    arm.call('run6502', 2000 * 256)
    ram = arm.r32(arm.addr('NES_RAM'))
    assert arm.read8(ram + 0x10) == 0x42, '6502 did not continue in the new PRG bank'
    assert arm.r32(arm.addr('nes_faults')) == 0


def test_prg_modes_and_dmc(arm):
    assert arm.load(make_mmc3_rom()) == 0
    arm.mapper_write(0x8000, 6)
    arm.mapper_write(0x8001, 2)
    arm.mapper_write(0x8000, 7)
    arm.mapper_write(0x8001, 3)
    assert [arm.cpu_read(a) for a in (0x8100, 0xA100, 0xC100, 0xE100)] == [2, 3, 6, 7]
    assert arm.call('Nes_ApuReadDmc', 0x8100) == 2
    assert arm.call('Nes_ApuReadDmc', 0xA100) == 3
    arm.mapper_write(0x8000, 0x46)
    assert [arm.cpu_read(a) for a in (0x8100, 0xA100, 0xC100, 0xE100)] == [6, 3, 2, 7]
    assert arm.call('Nes_ApuReadDmc', 0xC100) == 2


def select_chr_registers(arm, invert=0):
    for reg, value in enumerate([6, 8, 1, 3, 5, 7]):
        arm.mapper_write(0x8000, invert | reg)
        arm.mapper_write(0x8001, value)


def assert_chr_layout(arm, expected):
    raw = arm.r32(arm.addr('VROM_banks'))
    decoded = arm.r32(arm.addr('VROM_tiles'))
    assert [arm.ppu_bank(i) for i in range(8)] == [raw + b * 0x400 for b in expected]
    assert [arm.ppu_bank(i, True) for i in range(8)] == [decoded + b * 0x400 for b in expected]


def test_chr_modes_and_alignment(arm):
    assert arm.load(make_mmc3_rom()) == 0
    select_chr_registers(arm)
    assert_chr_layout(arm, [6, 7, 8, 9, 1, 3, 5, 7])
    arm.call('PPU_WriteToPort', 0, 0x2006)
    arm.call('PPU_WriteToPort', 0, 0x2006)
    arm.call('PPU_ReadFromPort', 0x2007)
    assert arm.call('PPU_ReadFromPort', 0x2007) == 6
    select_chr_registers(arm, 0x80)
    assert_chr_layout(arm, [1, 3, 5, 7, 6, 7, 8, 9])
    arm.mapper_write(0x8000, 0x80)  # odd 2 KiB register values round down
    arm.mapper_write(0x8001, 9)
    assert_chr_layout(arm, [1, 3, 5, 7, 8, 9, 8, 9])
    arm.mapper_write(0x8000, 2)
    arm.mapper_write(0x8001, 0xFF)
    assert arm.cpu_read(0x8100) == 0  # unrelated PRG mapping is unchanged
    assert arm.ppu_bank(4) == arm.r32(arm.addr('VROM_banks')) + 15 * 0x400


def test_mirroring_control(arm):
    assert arm.load(make_mmc3_rom()) == 0
    nametables = arm.ppu_bank(8)
    arm.mapper_write(0xA000, 0)  # CIRAM A10 = PPU A10: vertical mirroring
    assert [arm.ppu_bank(i) for i in range(8, 12)] == [
        nametables, nametables + 0x400, nametables, nametables + 0x400]
    arm.mapper_write(0xA000, 1)  # CIRAM A10 = PPU A11: horizontal mirroring
    assert [arm.ppu_bank(i) for i in range(8, 12)] == [
        nametables, nametables, nametables + 0x400, nametables + 0x400]

    # Check the externally observable $2007 aliases, including mirrored
    # register addresses and ignored high data bits, rather than just pointers.
    def address(value):
        arm.call('PPU_ReadFromPort', 0x2002)
        arm.call('PPU_WriteToPort', value >> 8, 0x2006)
        arm.call('PPU_WriteToPort', value & 255, 0x2006)

    for mode, expected in ((0, [0x33, 0x44, 0x33, 0x44]),
                           (1, [0x22, 0x22, 0x44, 0x44])):
        arm.mapper_write(0xBFFE, 0xFE | mode)
        for index, value in enumerate((0x11, 0x22, 0x33, 0x44)):
            address(0x2000 + index * 0x400)
            arm.call('PPU_WriteToPort', value, 0x2007)
        actual = []
        for index in range(4):
            address(0x2000 + index * 0x400)
            arm.call('PPU_ReadFromPort', 0x2007)  # buffered read
            actual.append(arm.call('PPU_ReadFromPort', 0x2007))
        assert actual == expected, ('MMC3 nametable aliasing', mode, actual)


def make_mmc3_program(code):
    rom = bytearray(make_mmc3_rom())
    assert len(code) < 0x1FFA
    fixed = 16 + 7 * 0x2000
    rom[fixed:fixed + len(code)] = code
    return bytes(rom)


def test_sram_protection_through_6502(arm):
    code = bytearray(bytes.fromhex(
        'a9 80 8d 01 a0 '  # enable RAM, write $55
        'a9 55 8d 00 60 '
        'a9 c0 8d 01 a0 '  # write protect: $AA must be ignored
        'a9 aa 8d 00 60 '
        'ad 00 60 85 10 '
        'a9 00 8d 01 a0 '  # disable: reads return zero, $77 is ignored
        'ad 00 60 85 11 '
        'a9 77 8d 00 60 '
        'a9 80 8d 01 a0 '
        'ad 00 60 85 12 '))
    code += bytes([0x4C, len(code) & 0xFF, 0xE0 + (len(code) >> 8)])
    assert arm.load(make_mmc3_program(code)) == 0
    arm.call('run6502', 3000 * 256)
    ram = arm.r32(arm.addr('NES_RAM'))
    sram = arm.r32(arm.addr('NES_SRAM'))
    assert [arm.read8(ram + i) for i in (0x10, 0x11, 0x12)] == [0x55, 0, 0x55]
    assert arm.read8(sram) == 0x55
    assert arm.r32(arm.addr('nes_faults')) == 0


def test_chr_ram_banking(arm):
    assert arm.load(make_mmc3_rom(chr_banks=0)) == 0
    assert arm.r32(arm.addr('VROM_1K_SIZE')) == 8
    arm.mapper_write(0x8000, 2)
    arm.mapper_write(0x8001, 1)
    assert arm.ppu_bank(4) == arm.r32(arm.addr('VROM_banks')) + 0x400
    arm.call('PPU_WriteToPort', 0x10, 0x2006)
    arm.call('PPU_WriteToPort', 0, 0x2006)
    arm.call('PPU_WriteToPort', 0xFF, 0x2007)
    assert arm.read8(arm.r32(arm.addr('VROM_banks')) + 0x400) == 0xFF
    assert any(arm.u.mem_read(arm.ppu_bank(4, True), 16))


def test_irq_registers_and_pending(arm):
    assert arm.load(make_mmc3_rom()) == 0
    irq = arm.addr('cpuirq')
    arm.mapper_write(0xC000, 2)
    arm.mapper_write(0xC001, 0)
    arm.mapper_write(0xE001, 0)
    arm.hsync()
    arm.hsync()
    assert arm.read8(irq) == 0
    arm.hsync()
    assert arm.read8(irq) == 1, 'latched counter did not assert IRQ at zero'
    arm.u.mem_write(irq, b'\x00')  # the CPU core clears its input on acceptance
    arm.mapper_write(0xE001, 0)
    assert arm.read8(irq) == 1, 'mapper pending level was lost with CPU acceptance'
    arm.mapper_write(0xE000, 0)
    assert arm.read8(irq) == 0
    arm.mapper_write(0xE001, 0)
    assert arm.read8(irq) == 0, 'acknowledge did not clear pending'
    arm.mapper_write(0xC000, 0)
    arm.mapper_write(0xC001, 0)
    arm.hsync()
    assert arm.read8(irq) == 1, 'zero reload must assert on its first clock'
    arm.mapper_write(0xE000, 0)
    arm.mapper_write(0xC001, 0)
    arm.hsync()
    assert arm.read8(irq) == 0, 'disabled IRQ must not assert'
    arm.mapper_write(0xE001, 0)
    assert arm.read8(irq) == 0
    arm.hsync()
    assert arm.read8(irq) == 1


def make_irq_rom():
    main = bytes.fromhex(
        '78 '                    # SEI during setup
        'a9 18 8d 01 20 '       # enable background and sprites
        'a9 00 8d 00 c0 '       # latch = 0: one request per clock
        'a9 00 8d 01 c0 '
        'a9 01 8d 01 e0 '       # enable MMC3 IRQ
        '58 4c 16 e0')           # CLI and idle
    rom = bytearray(make_mmc3_program(main))
    fixed = 16 + 7 * 0x2000
    handler = bytes.fromhex(
        'e6 20 '                # count the IRQ
        'a9 00 8d 00 e0 '       # acknowledge and disable
        'a9 01 8d 01 e0 '       # re-enable
        '40')                    # RTI
    rom[fixed + 0x100:fixed + 0x100 + len(handler)] = handler
    rom[16 + 8 * 0x2000 - 2:16 + 8 * 0x2000] = struct.pack('<H', 0xE100)
    return bytes(rom)


def test_irq_frame_integration(arm):
    rom = make_irq_rom()
    ram = arm.r32(arm.addr('NES_RAM'))
    snapshots = []
    for draw in (0, 1):
        assert arm.load(rom) == 0
        arm.line_count = 0
        arm.call('Nes_Frame', draw)
        count = arm.read8(ram + 0x20)
        assert 200 <= count <= 241, f'unexpected scanline IRQ count: {count}'
        snapshots.append(bytes(arm.u.mem_read(ram, 0x800)))
        assert arm.line_count == (240 if draw else 0)
        assert arm.r32(arm.addr('nes_faults')) == 0
    assert snapshots[0] == snapshots[1], 'draw skipping changed CPU/IRQ state'
    arm.mapper_write(0xE000, 0)
    arm.call('PPU_WriteToPort', 0, 0x2001)
    arm.u.mem_write(ram + 0x20, b'\x00')
    arm.call('Nes_Frame', 0)
    assert arm.read8(ram + 0x20) == 0, 'rendering disabled still clocked IRQ'


def main():
    arm = NesArm()
    test_mmc3_loader(arm)
    test_prg_live_switch(arm)
    test_prg_modes_and_dmc(arm)
    test_chr_modes_and_alignment(arm)
    test_mirroring_control(arm)
    test_sram_protection_through_6502(arm)
    test_chr_ram_banking(arm)
    test_irq_registers_and_pending(arm)
    test_irq_frame_integration(arm)
    print('PASS: MMC3 mapping, SRAM, IRQ registers and frame integration')


if __name__ == '__main__':
    main()
