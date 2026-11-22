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
# Live observations are non-atomic; no writes to application RAM or Flash.
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    local={};file=''
    for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols():
        if s['st_info']['type']=='STT_FILE':file=s.name
        if file=='bsp_joystick.c' and s.name:local[s.name]=s['st_value']
report={'version':m['version'],'reset':False,'halt_requested':False,'flash_written':False,'ram_written':False,'samples':[]}
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=options) as session:
    t=session.target
    actual=bytearray()
    print('Verifying current firmware before reading symbols...',flush=True)
    for off in range(0,len(expected),1024):actual.extend(t.read_memory_block8(0x08000000+off,min(1024,len(expected)-off)))
    assert bytes(actual)==expected,'Firmware differs; no symbol reads attempted'
    report['full_flash_match']=True
    print('Flash matches. Sampling input and frame timing for about 8 seconds...',flush=True)
    for i in range(24):
        row={n:t.read32(sy[n]) for n in ['MapperNo','nes_logic_hz','nes_draw_hz','nes_logic_total','nes_draw_frame_us','nes_skip_frame_us','nes_clock_drops','nes_faults','nes_apu_queue_drops']}
        for n in ['nes_effective_render_divisor','nes_mmc5_cache_misses']:
            if n in sy:row[n]=t.read32(sy[n])
        row.update(sample=i,app_state=t.read8(sy['app_state']),pad=t.read8(sy['PADdata']),gpio=[t.read32(a) for a in [0x40020010,0x40020810,0x40020410]])
        values=struct.unpack('<4H2fBB2x3I',bytes(t.read_memory_block8(local['state'],32)))
        row['joystick']=dict(zip(['raw_x','raw_y','center_x','center_y','x','y','calibrated','healthy','errors','pairs','max_gap_ms'],values))
        report['samples'].append(row)
        if i in (0,12,23):print(json.dumps(row),flush=True)
        time.sleep(.25)
(root/'Release'/('input_readonly_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('Saved read-only input/frame report.',flush=True)
