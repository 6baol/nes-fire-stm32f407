"""Authorized live SD menu/load test. No card writes; never halt during SD I/O.
Synthetic buttons are released on all exits. Leaves SMB3 running, no pause.
"""
from pathlib import Path
import json,time,hashlib,struct
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

root=Path(__file__).resolve().parents[1]
m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
image=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    sy={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach',
      'auto_unlock':False,'resume_on_disconnect':False,'cache.enable_memory':False,
      'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
report={'version':m['version'],'hardware_tested':True,'card_writes':False,'samples':[],
        'firmware_sha256':hashlib.sha256(image).hexdigest(),
        'scope':'live SD state, menu and loaded ROM verification; not LCD photo/headphone recording'}
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as session:
    t=session.target
    def value(name):return t.read32(sy[name])
    def pad(v):t.write8(sy['nes_test_pad'],v)
    def sample(tag):
        row={n:value(n) for n in ['sd_last_error','sd_init_attempts','sd_read_retries','sd_blocks_read','sd_bus_width',
             'sd_count','nes_sd_file_reads','nes_faults','nes_logic_hz','nes_draw_hz','nes_clock_drops','nes_apu_queue_drops','nes_audio_dma_errors']}
        row.update(tag=tag,sd_active=t.read8(sy['sd_active']),app_state=t.read8(sy['app_state']),
                   index=struct.unpack('<h',bytes(t.read_memory_block8(sy['menu'],2)))[0],
                   cfsr=t.read32(0xe000ed28),hfsr=t.read32(0xe000ed2c))
        report['samples'].append(row);print(json.dumps(row),flush=True)
        assert row['nes_faults']==row['cfsr']==row['hfsr']==row['nes_audio_dma_errors']==0,row
        return row
    try:
        assert bytes(t.read_memory_block8(0x08000000,256))==image[:256]
        end=time.monotonic()+20
        while time.monotonic()<end:
            if t.read8(sy['sd_active'])==1:break
            time.sleep(.5)
        time.sleep(1)
        row=sample('boot');assert row['sd_active']==1 and row['sd_count']==5 and row['app_state']==0,row
        for step in range(5):
            pad(0);time.sleep(.15);t.write8(sy['menu_axis_armed'],1);pad(32);time.sleep(.25);pad(0);time.sleep(.35)
            row=sample('cover_'+str(step));assert row['index']==(step+1)%5,row
        for _ in range(2):
            t.write8(sy['menu_axis_armed'],1);pad(32);time.sleep(.3);pad(0);time.sleep(.2)
        row=sample('select_smb3');assert row['index']==2,row
        pad(1);time.sleep(.2);pad(0)
        end=time.monotonic()+30
        while time.monotonic()<end:
            time.sleep(1);row=sample('load_smb3')
            if row['app_state']==1:break
        else:raise RuntimeError('SD ROM load timed out')
        raw=(root/'Roms/SMB3.nes').read_bytes();actual=bytearray()
        for offset in range(0,len(raw),1024):actual.extend(t.read_memory_block8(0x6c060000+offset,min(1024,len(raw)-offset)))
        assert bytes(actual)==raw,'SD-loaded ROM differs from source'
        report['smb3_sd_rom_sha256']=hashlib.sha256(actual).hexdigest()
        time.sleep(3);before=value('sd_blocks_read');row=sample('smb3_running');time.sleep(2)
        assert value('sd_blocks_read')==before,'SD access during gameplay'
        assert row['nes_logic_hz']>=55 and row['nes_draw_hz']>=15,row
        report['result']='PASS';report['no_sd_reads_during_gameplay']=True
    except Exception as exc:
        report['result']='FAIL';report['error']=str(exc)
        raise
    finally:
        pad(0)
        (root/'Release'/('board_sd_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
