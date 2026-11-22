"""Boot embedded SMB2 over SWD, validate basic controls and capture PPU output.
This is a board test. A PPU capture is not a camera image of the physical LCD.
Injected controls are always released, including on exceptions.
"""
import json,struct,time,hashlib
from pathlib import Path
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
image=(root/'Release'/(manifest['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    sym={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,
      'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,
      'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
report={'version':manifest['version'],'hardware_tested':True,'bin_sha256':hashlib.sha256(image).hexdigest(),
        'scope':'live board SWD state and PPU capture; LCD appearance and headphone audibility require user confirmation','samples':[]}
names=['nes_faults','nes_logic_hz','nes_draw_hz','nes_logic_total','nes_clock_drops',
       'nes_audio_ready','nes_audio_dma_errors','nes_audio_blocks','nes_audio_nonzero',
       'nes_audio_peak','nes_audio_max_us','nes_apu_queue_drops','nes_fds_bytes','nes_fds_reads']
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as session:
    t=session.target
    def pad(value):
        t.halt();t.write8(sym['nes_test_pad'],value);t.resume()
    def state(tag):
        t.halt()
        try:
            ram=t.read32(sym['NES_RAM'])
            row={n:t.read32(sym[n]) for n in names}
            row.update(tag=tag,app_state=t.read8(sym['app_state']),mode=t.read8(ram+0x770),
                       task=t.read8(ram+0x772),sub=t.read8(ram+0xe),
                       x=t.read8(ram+0x86)+256*t.read8(ram+0x6d),y=t.read8(ram+0xce),
                       cfsr=t.read32(0xe000ed28),hfsr=t.read32(0xe000ed2c))
            report['samples'].append(row);print(json.dumps(row),flush=True)
            return row
        finally:t.resume()
    def wait_for(tag,predicate,seconds=55):
        end=time.monotonic()+seconds
        while time.monotonic()<end:
            time.sleep(2);row=state(tag)
            assert row['nes_faults']==0 and row['cfsr']==0 and row['hfsr']==0,row
            if predicate(row):return row
        raise RuntimeError('Timed out: '+tag)
    def capture(tag):
        t.halt();before=t.read32(sym['nes_capture_ready']);t.write32(sym['nes_capture_request'],1);t.resume()
        for _ in range(20):
            time.sleep(.25);t.halt()
            if t.read32(sym['nes_capture_ready'])!=before:break
            t.resume()
        else:raise RuntimeError('PPU capture timed out')
        try:
            data=bytearray()
            for off in range(0,256*240*2,1024):
                data.extend(t.read_memory_block8(0x6c040000+off,min(1024,256*240*2-off)))
        finally:t.resume()
        rgb=bytearray()
        for (c,) in struct.iter_unpack('<H',data):
            rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
        dest=root/'Release'/('board_smb2_'+tag+'.ppm')
        dest.write_bytes(b'P6\n256 240\n255\n'+rgb)
        report[tag+'_capture_sha256']=hashlib.sha256(data).hexdigest()
    try:
        assert bytes(t.read_memory_block8(0x08000000,256))==image[:256]
        t.reset();time.sleep(3)
        state('menu')
        entries=manifest['rom']['games']
        index=next(i for i,g in enumerate(entries) if g['name'].lower().endswith('.fds'))
        t.halt();t.write16(sym['menu'],index);t.resume()
        pad(1);time.sleep(.3);pad(0)
        wait_for('boot',lambda r:r['app_state']==1 and r['mode']==0 and r['task']==4)
        capture('title')
        pad(8);time.sleep(.15);pad(0)
        before=wait_for('start',lambda r:r['mode']==1 and r['task']==4 and r['sub']==8)
        pad(0x82);time.sleep(.8);pad(0)
        moved=state('right')
        assert moved['x']>before['x'],('right input failed',before,moved)
        # B+A remains held together for the jump test; release before reading the result.
        ground=moved['y'];pad(0x83);time.sleep(.15);pad(0)
        jumped=state('jump')
        assert jumped['y']<ground-5,('jump input failed',ground,jumped)
        capture('gameplay')
        row=wait_for('steady',lambda r:r['nes_logic_hz']>0,seconds=8)
        assert row['nes_logic_hz']>=55 and row['nes_audio_dma_errors']==0 and row['nes_apu_queue_drops']==0,row
        pad(8);time.sleep(.15);pad(0);time.sleep(.1)
        ram=t.read32(sym['NES_RAM']);report['paused_for_review']=bool(t.read8(ram+0x776)&1)
        report['result']='PASS';print('SMB2 BOARD PASS',flush=True)
    except Exception as exc:
        report['result']='FAIL';report['error']=str(exc);raise
    finally:
        pad(0)
        (root/'Release'/('board_smb2_v'+manifest['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
