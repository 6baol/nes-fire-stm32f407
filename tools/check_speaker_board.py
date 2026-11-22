"""Read-only running-board speaker check. No reset, halt, keys or programming.

Codec registers are the RAM mirror of acknowledged I2C writes, not analog
measurements. A listener must confirm audible speaker output.
"""
import hashlib,json,struct,time
from pathlib import Path
import hid
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

root=Path(__file__).resolve().parents[1]
m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
expected=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    sy={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
# Bound the initial probe query; this older HID firmware can stop replying
# even while Windows still enumerates it. Do not wait forever for a probe.
devices=hid.enumerate(0xc251,0xf001)
if not devices:raise SystemExit('Fire CMSIS-DAP is not connected.')
d=hid.device()
try:
    d.open_path(devices[0]['path']);d.write([0,0,0xff]+[0]*62);reply=d.read(64,2000)
    if len(reply)<4 or reply[0]!=0 or reply[1]!=2:raise SystemExit('CMSIS-DAP did not reply; reconnect probe USB.')
finally:d.close()
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
options={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,
         'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':False,
         'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
report={'version':m['version'],'reset':False,'halt_requested':False,'flash_written':False,
        'ram_written':False,'card_writes_requested':False,'samples':[],
        'scope':'running MCU Flash readback, audio counters and I2C register mirror; no listener/analog validation'}
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=options) as session:
    t=session.target
    def value(n):return t.read32(sy[n])
    try:
        print('Reading running target Flash without halting...',flush=True)
        actual=bytearray()
        for off in range(0,len(expected),1024):
            actual.extend(t.read_memory_block8(0x08000000+off,min(1024,len(expected)-off)))
        report['bytes_verified']=len(actual);report['actual_sha256']=hashlib.sha256(actual).hexdigest()
        report['full_flash_match']=bytes(actual)==expected
        assert report['full_flash_match'],'Running firmware differs from current published BIN; RAM symbols not used'
        print('Full Flash matches',m['version'],flush=True)
        for i in range(6):
            row={n:value(n) for n in ['nes_audio_ready','nes_audio_blocks','nes_audio_codec_error',
                 'nes_audio_dma_errors','nes_audio_nonzero','nes_audio_peak','nes_audio_max_us',
                 'nes_apu_queue_drops','nes_faults','nes_logic_hz','nes_draw_hz','nes_clock_drops',
                 'sd_last_error','sd_read_retries','sd_write_retries','sd_count']}
            regs=struct.unpack('<58H',bytes(t.read_memory_block8(sy['nes_audio_codec_regs'],116)))
            row.update(sample=i,state=str(t.get_state()),audio_output=t.read8(sy['audio_output']),
                       audio_suspended=t.read8(sy['nes_audio_suspended']),app_state=t.read8(sy['app_state']),
                       sd_active=t.read8(sy['sd_active']),cfsr=t.read32(0xe000ed28),hfsr=t.read32(0xe000ed2c),
                       codec_regs={str(n):hex(regs[n]) for n in [1,2,3,10,43,49,52,53,54,55]})
            row['speaker_route_active']=bool(row['audio_output']==1 and regs[2]&0x180==0 and
                regs[3]&0x60==0x60 and regs[43]&0x10 and regs[52]&0x40 and regs[53]&0x40 and
                not regs[54]&0x40 and not regs[55]&0x40 and regs[54]&63==regs[55]&63)
            report['samples'].append(row);print(json.dumps(row),flush=True)
            if i<5:time.sleep(1.5)
        report['audio_dma_advancing']=report['samples'][-1]['nes_audio_blocks']>report['samples'][0]['nes_audio_blocks']
        report['speaker_route_active']=all(s['speaker_route_active'] for s in report['samples'])
        report['errors_zero']=all(s[n]==0 for s in report['samples'] for n in
             ['nes_audio_codec_error','nes_audio_dma_errors','nes_apu_queue_drops','nes_faults','cfsr','hfsr'])
        report['result']='PASS' if report['audio_dma_advancing'] and report['speaker_route_active'] and report['errors_zero'] else 'CHECK REQUIRED'
    except Exception as exc:
        report.update(result='FAIL',error=str(exc));raise
    finally:
        (root/'Release'/('board_speaker_readonly_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
