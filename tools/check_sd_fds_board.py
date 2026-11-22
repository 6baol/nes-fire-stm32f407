"""Live SD/FDS regression; reset allowed, no halt and no card writes.

Runs after flashing the matching release. All injected buttons are released.
PPU captures are memory copies, not photographs of the physical LCD.
"""
import hashlib,json,struct,time
from pathlib import Path
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

root=Path(__file__).resolve().parents[1]
m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
image=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    sy={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,
      'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':False,
      'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
report={'version':m['version'],'firmware_sha256':hashlib.sha256(image).hexdigest(),
        'hardware_tested':True,'card_writes':False,'halt_requested':False,'samples':[],
        'scope':'SD-loaded FDS boot, 1-1, controls and PPU memory capture; not LCD photo or audio recording'}
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as session:
    t=session.target
    def value(n):return t.read32(sy[n])
    def pad(v):t.write8(sy['nes_test_pad'],v)
    def sample(tag):
        row={n:value(n) for n in ['sd_last_error','sd_init_attempts','sd_read_retries','sd_blocks_read',
             'nes_faults','nes_logic_hz','nes_draw_hz','nes_clock_drops','nes_apu_queue_drops',
             'nes_audio_dma_errors','nes_audio_blocks','nes_audio_nonzero','nes_fds_bytes','nes_fds_reads']}
        ram=value('NES_RAM')
        row.update(tag=tag,app_state=t.read8(sy['app_state']),sd_active=t.read8(sy['sd_active']),
                   mode=t.read8(ram+0x770),task=t.read8(ram+0x772),sub=t.read8(ram+0xe),
                   x=t.read8(ram+0x86)+256*t.read8(ram+0x6d),y=t.read8(ram+0xce),
                   cfsr=t.read32(0xe000ed28),hfsr=t.read32(0xe000ed2c))
        report['samples'].append(row);print(json.dumps(row),flush=True)
        assert row['nes_faults']==row['cfsr']==row['hfsr']==row['nes_audio_dma_errors']==0,row
        return row
    def wait(tag,predicate,seconds=45):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            time.sleep(1);row=sample(tag)
            if predicate(row):return row
        raise RuntimeError('Timed out: '+tag)
    def capture(tag):
        before=value('nes_capture_ready');t.write32(sy['nes_capture_request'],1)
        end=time.monotonic()+3
        while value('nes_capture_ready')==before:
            if time.monotonic()>end:raise RuntimeError('Capture timed out')
            time.sleep(.1)
        raw=bytearray()
        for off in range(0,256*240*2,1024):
            raw.extend(t.read_memory_block8(0x6c040000+off,min(1024,256*240*2-off)))
        rgb=bytearray()
        for (c,) in struct.iter_unpack('<H',raw):
            rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
        dest=root/'Release'/('board_sd_fds_'+tag+'_'+m['version']+'.ppm')
        dest.write_bytes(b'P6\n256 240\n255\n'+rgb)
        report[tag+'_capture_sha256']=hashlib.sha256(raw).hexdigest()
    try:
        assert bytes(t.read_memory_block8(0x08000000,256))==image[:256]
        t.reset();time.sleep(2)
        row=wait('reboot',lambda r:r['sd_active']==1 and r['app_state']==0,20)
        assert value('sd_count')==5
        t.write8(sy['menu_axis_armed'],1);pad(32);time.sleep(.25);pad(0);time.sleep(.5)
        assert t.read16(sy['menu'])==1
        pad(1);time.sleep(.2);pad(0)
        wait('title',lambda r:r['app_state']==1 and r['mode']==0 and r['task']==4)
        # Start immediately. Live SWD copying takes seconds and must not allow
        # the title to enter its attract demo before this button edge.
        pad(8);time.sleep(.15);pad(0)
        before=wait('level_1_1',lambda r:r['mode']==1 and r['task']==4 and r['sub']==8)
        pad(0x82);time.sleep(.8);pad(0);moved=sample('right')
        assert moved['x']>before['x'],('Movement failed',before,moved)
        ground=moved['y'];pad(0x83);time.sleep(.15);pad(0);jumped=sample('run_jump')
        assert jumped['y']<ground-5,('Jump failed',ground,jumped)
        capture('gameplay')
        source=(root/'Roms/Super Mario Bros. 2 (Japan) (En).fds').read_bytes()
        actual=bytearray()
        for off in range(0,len(source),1024):
            actual.extend(t.read_memory_block8(0x6c060000+off,min(1024,len(source)-off)))
        assert actual==source,'FDS preload differs from source'
        report['fds_preload_sha256']=hashlib.sha256(actual).hexdigest()
        time.sleep(2);row=sample('steady')
        assert row['nes_logic_hz']>=55 and row['nes_apu_queue_drops']==0,row
        blocks=value('sd_blocks_read');time.sleep(2)
        assert value('sd_blocks_read')==blocks,'SD accesses during gameplay'
        report.update(result='PASS',no_sd_reads_during_gameplay=True)
    except Exception as exc:
        report.update(result='FAIL',error=str(exc));raise
    finally:
        pad(0)
        (root/'Release'/('board_sd_fds_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
