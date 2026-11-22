"""Exercise the linked Cortex-M scheduler with deterministic DWT frame timings."""
import struct

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0

from test_mmc3_arm import NesArm


class Scheduler(NesArm):
    HCLK = 168_000_000
    COUNTER = 0xE0001004

    def __init__(self):
        super().__init__()
        self.clock = 0
        self.frames = []
        self.draw_cost = self.skip_cost = 0
        self.set_word(self.addr('SystemCoreClock'), self.HCLK)
        self.set_word(self.addr('stats_due'), 60_000)
        self.u.mem_write(self.addr('loaded'), b'\x01')
        self.u.mem_write(self.addr('app_state'), b'\x01')
        self.u.mem_map(0x40000000, 0x30000)
        self.set_word(0x40020410, 1 << 7)  # release SW
        for name, callback in [('Joystick_Get', self.joystick), ('PixelFont_Text', self._skip),
                               ('Nes_Frame', self.advance_frame)]:
            location = self.addr(name) & ~1
            self.u.hook_add(UC_HOOK_CODE, callback, begin=location, end=location)

    def set_word(self, address, value):
        self.u.mem_write(address, struct.pack('<I', value & 0xFFFFFFFF))

    def joystick(self, uc, *args):
        uc.reg_write(UC_ARM_REG_R0, 0x20018000)
        self._skip(uc, *args)

    def advance_frame(self, uc, *args):
        draw = bool(uc.reg_read(UC_ARM_REG_R0))
        self.frames.append(draw)
        self.clock += (self.draw_cost if draw else self.skip_cost) * (self.HCLK // 1_000_000)
        self.set_word(self.COUNTER, self.clock)
        self._skip(uc, *args)

    def run_for(self, seconds, draw_us, skip_us):
        first = len(self.frames)
        self.draw_cost, self.skip_cost = draw_us, skip_us
        end = self.clock + self.HCLK * seconds
        while self.clock < end:
            self.set_word(self.COUNTER, self.clock)
            self.set_word(self.addr('uwTick'), self.clock // (self.HCLK // 1000))
            self.call('NesApp_Poll')
            self.clock += self.HCLK // 4000
        return self.frames[first:]


def main():
    app = Scheduler()
    for floor, draw, skip, expected in [
            (1, 15_999, 4500, 1), (1, 16_001, 4500, 2),
            (1, 35_000, 2000, 3), (1, 46_300, 4550, 4),
            (1, 59_000, 6500, 6), (1, 60_000, 16_000, 8),
            (1, 16_040, 17_000, 1), (3, 0, 0, 3), (10, 8000, 3000, 8)]:
        assert app.call('NesPort_RenderDivisor', floor, draw, skip) == expected

    # Cost transitions occur inside one running game. The v0.42 SMB3 sample
    # supplies the 46.3 / 4.55 ms case. Only the scheduler runs on this clock.
    for draw_us, skip_us, divisor in [(10_000, 4550, 1), (46_300, 4550, 4),
                                       (35_000, 2000, 3), (59_000, 6500, 6),
                                       (90_000, 4000, 8),
                                       (10_000, 4550, 1)]:
        app.run_for(2, draw_us, skip_us)
        before = app.r32(app.addr('nes_clock_drops'))
        frames = app.run_for(2, draw_us, skip_us)
        assert 117 <= len(frames) <= 123, (draw_us, len(frames))
        assert abs(sum(frames) - 120 / divisor) <= 2, (draw_us, sum(frames))
        assert app.r32(app.addr('nes_clock_drops')) == before
        draws = [i for i, visible in enumerate(frames) if visible]
        assert all(b - a == divisor for a, b in zip(draws, draws[1:])), draws
        print(f'PASS draw/skip {draw_us}/{skip_us} us, '
              f'{len(frames)} logic / {sum(frames)} draw per 2 s')

    # A logic-only frame that already exceeds budget still executes, and the
    # longest display interval continues publishing frames.
    frames = app.run_for(2, 60_000, 18_000)
    assert len(frames) > 60 and sum(frames) > 7
    assert app.r32(app.addr('nes_effective_render_divisor')) == 8


if __name__ == '__main__':
    main()
