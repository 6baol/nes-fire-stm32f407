"""Run original SMB3 on the real Keil ARM core in Unicorn, not on a board."""
import hashlib
import json
import struct
from PIL import Image

from unicorn import UC_HOOK_CODE
from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R1, UC_ARM_REG_R2

from test_mmc3_arm import NesArm, ROOT

ROM_SHA256 = '6ea0777ca520ba7ad7b0ea0f6452140d59aa0b1dffe5045cb1e8020dde10c267'
PCM_SCRATCH = 0x6C0F8000
OUT = ROOT / 'Tests/nes_output'


class Smb3Arm(NesArm):
    def __init__(self):
        super().__init__()
        self.frame = bytearray(256 * 240)
        self.palette = [0] * 64
        self.apu_log = []
        self.frame_no = 0
        self.u.hook_add(UC_HOOK_CODE, self._capture_line,
                        begin=self.addr('NesPort_Line') & ~1,
                        end=self.addr('NesPort_Line') & ~1)
        for name in ('Apu_Write', 'Apu_Write4015'):
            self.u.hook_add(UC_HOOK_CODE, self._capture_apu_write,
                            begin=self.addr(name) & ~1, end=self.addr(name) & ~1)

    def _capture_apu_write(self, uc, address, size, data):
        self.apu_log.append((self.frame_no, uc.reg_read(UC_ARM_REG_R1),
                             uc.reg_read(UC_ARM_REG_R0)))

    def _capture_line(self, uc, address, size, data):
        y = uc.reg_read(UC_ARM_REG_R0)
        source = uc.reg_read(UC_ARM_REG_R1)
        palette = uc.reg_read(UC_ARM_REG_R2)
        self.frame[y * 256:(y + 1) * 256] = uc.mem_read(source, 256)
        self.palette[:] = struct.unpack('<64H', uc.mem_read(palette, 128))

    def pc(self):
        cpu = self.addr('cpu_data')
        return (self.r32(cpu + 124) - self.r32(cpu + 132)) & 0xFFFF

    def save_frame(self, name):
        rgb = bytearray()
        for value in self.frame:
            colour = self.palette[value & 63]
            rgb.extend((((colour >> 11) & 31) * 255 // 31,
                        ((colour >> 5) & 63) * 255 // 63,
                        (colour & 31) * 255 // 31))
        path = OUT / (name + '.ppm')
        path.write_bytes(b'P6\n256 240\n255\n' + rgb)
        # Keep the displayed PNG in sync with the current AXF output.
        Image.frombytes('RGB', (256, 240), bytes(rgb)).save(path.with_suffix('.png'))
        return path

    def assert_status_panel(self):
        # Stable white borders of the three item-card slots at the bottom.
        # Reversed MMC3 CIRAM mapping renders ground tiles here instead.
        white = 0xF79E  # NES white converted to this firmware's RGB565 palette
        for left in (173, 197, 221):
            for x in range(left + 1, left + 21):
                assert self.palette[self.frame[198 * 256 + x] & 63] == white, \
                    ('SMB3 status panel border missing', x, 198)

    def assert_world_map(self):
        # The world-map frame has two long peach borders. Check the rendered
        # scene rather than the incidental PC where a CPU time slice ended.
        for y in (28, 29, 188, 189):
            for x in (32,64,96,128,160,192,224,238):
                assert self.palette[self.frame[y*256+x]&63]==0xFDF6, \
                    ('SMB3 world-map border missing',x,y)


def run_smb3(raw, capture=True):
    arm = Smb3Arm()
    assert arm.load(raw) == 0, 'original SMB3 was rejected by Nes_Load'
    arm.u.mem_write(arm.addr('nes_faults'), b'\0' * 4)
    arm.u.mem_write(arm.addr('nes_apu_queue_drops'), b'\0' * 4)
    ram = arm.r32(arm.addr('NES_RAM'))
    pcm = bytearray()
    samples_before = 0
    frame_no = 0

    def advance(draw=0):
        nonlocal frame_no, samples_before
        arm.frame_no = frame_no
        arm.call('Nes_Frame', draw if capture else 0)
        frame_no += 1
        samples = frame_no * 11025 // 60 - samples_before
        samples_before += samples
        arm.call('apu_process', PCM_SCRATCH, samples)
        pcm.extend(arm.u.mem_read(PCM_SCRATCH, samples))

    def show(name):
        path = arm.save_frame(name)
        print(f'frame={frame_no} pc=${arm.pc():04X} colours={len(set(arm.frame))} '
              f'faults={arm.r32(arm.addr("nes_faults"))} screenshot={path.name}', flush=True)

    def run(count, name=None):
        for index in range(count):
            advance(int(capture and name is not None and index == count - 1))
        if capture and name:
            show(name)

    def press(mask, name):
        arm.u.mem_write(arm.addr('PADdata'), bytes([mask]))
        run(4)
        arm.u.mem_write(arm.addr('PADdata'), b'\0')
        run(90, name)

    checkpoints = {59, 179, 299, 359, 419}
    for boot_frame in range(480):
        advance(int(capture and boot_frame in checkpoints))
        if capture and boot_frame in checkpoints:
            show(f'smb3_boot_{boot_frame + 1:04d}')
    press(0x08, 'smb3_title_menu')
    press(0x08, 'smb3_map_card')
    run(214, 'smb3_world_map')
    if capture:
        arm.assert_world_map()
    press(0x80, 'smb3_map_right')
    press(0x10, 'smb3_map_level1')
    press(0x01, 'smb3_level1')
    run(120, 'smb3_level1_ready')
    if capture:
        arm.assert_status_panel()

    def position():
        return (arm.read8(ram + 0x90) + 256 * arm.read8(ram + 0x75),
                arm.read8(ram + 0xA2))

    before = position()
    arm.u.mem_write(arm.addr('PADdata'), b'\x80')
    run(12, 'smb3_move_right')
    after = position()
    assert after[0] > before[0], ('right did not move SMB3 player', before, after)

    ground = after[1]
    arm.u.mem_write(arm.addr('PADdata'), b'\x83')
    jump = []
    for _ in range(8):
        run(1)
        jump.append(position()[1])
    assert min(jump) < ground - 8, ('B+A did not lift SMB3 player', ground, jump)

    arm.u.mem_write(arm.addr('PADdata'), b'\x82')
    run(30, 'smb3_run_right')
    run_after = position()
    assert run_after[0] > after[0] + 20, ('B+right did not run', after, run_after)
    arm.u.mem_write(arm.addr('PADdata'), b'\0')
    run(1)

    faults = arm.r32(arm.addr('nes_faults'))
    drops = arm.r32(arm.addr('nes_apu_queue_drops'))
    assert faults == 0, 'CPU faults in SMB3 flow'
    assert drops == 0, 'APU queue overflow in SMB3 flow'
    assert max(pcm) - min(pcm) > 32, 'SMB3 gameplay audio is silent'
    assert any(reg not in (16, 21) for _, reg, _ in arm.apu_log), 'no melodic APU writes'
    mmc3_names = ('mmc3_bank_select', 'mmc3_irq_counter', 'mmc3_irq_latch',
                  'mmc3_irq_reload', 'mmc3_irq_enabled', 'mmc3_irq_pending',
                  'mmc3_sram_control', 'cpuirq')
    return {
        'ram_state': bytes(arm.u.mem_read(ram, 0x800)),
        'mapper_state': bytes(arm.u.mem_read(arm.addr('mmc3_regs'), 8)) +
                        bytes(arm.read8(arm.addr(name)) for name in mmc3_names),
        'pc': arm.pc(),
        'position_before': before,
        'position_right': after,
        'position_run': run_after,
        'jump_y': jump,
        'pcm_range': [min(pcm), max(pcm)],
        'cpu_faults': faults,
        'apu_queue_drops': drops,
        'apu_writes': len(arm.apu_log),
        'total_frames': frame_no,
        'line_count': arm.line_count,
    }


def main():
    raw = (ROOT / 'Roms/SMB3.nes').read_bytes()
    assert len(raw) == 393232
    assert hashlib.sha256(raw).hexdigest() == ROM_SHA256
    OUT.mkdir(exist_ok=True)
    drawn = run_smb3(raw, capture=True)
    skipped = run_smb3(raw, capture=False)
    assert drawn['ram_state'] == skipped['ram_state'], 'draw skipping changed SMB3 CPU RAM'
    assert drawn['mapper_state'] == skipped['mapper_state'], 'draw skipping changed MMC3 state'
    assert drawn['pc'] == skipped['pc'], 'draw skipping changed the 6502 PC'
    assert skipped['line_count'] == 0
    print(f'SMB3 positions: {drawn["position_before"]} -> {drawn["position_right"]} '
          f'-> {drawn["position_run"]}; jump Y={drawn["jump_y"]}')
    report = {
        'result': 'PASS',
        'scope': 'original SMB3 on actual Keil ARM instructions under Unicorn; not a board test',
        'rom_sha256': ROM_SHA256,
        'axf_sha256': hashlib.sha256((ROOT / 'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest(),
        'boot_frames': 480,
        'total_frames': drawn['total_frames'],
        'title_menu_reached': True,
        'world_map_reached': True,
        'level_1_1_reached': True,
        'position_before': drawn['position_before'],
        'position_right': drawn['position_right'],
        'position_run': drawn['position_run'],
        'b_a_jump_y': drawn['jump_y'],
        'pcm_range': drawn['pcm_range'],
        'apu_writes': drawn['apu_writes'],
        'cpu_faults': drawn['cpu_faults'],
        'apu_queue_drops': drawn['apu_queue_drops'],
        'draw_skip_ram_match': True,
        'draw_skip_mmc3_match': True,
        'draw_skip_pc_match': True,
        'status_panel_border_checked': True,
        'irq_model': 'scanline-level A12 approximation, not dot-exact MMC3',
        'hardware_tested': False,
    }
    (OUT / 'smb3_boot_results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
