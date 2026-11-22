from pathlib import Path
import json,struct,time
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
root=Path(__file__).resolve().parents[1];local={};sy={};file=''
manifest=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols():
  if s['st_info']['type']=='STT_FILE':file=s.name
  if s.name:sy[s.name]=s['st_value']
  if file=='bsp_joystick.c':local[s.name]=s['st_value']
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
rows=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as sess:
 t=sess.target
 for i in range(8):
  row=dict(zip(['raw_x','raw_y','center_x','center_y','x','y','calibrated','healthy','errors','pairs','max_gap_ms'],struct.unpack('<4H2fBB2x3I',bytes(t.read_memory_block8(local['state'],32)))))
  row.update(samples=t.read16(local['samples']),pad=t.read8(sy['PADdata']),gpioa_moder=hex(t.read32(0x40020000)),logic=t.read32(sy['nes_logic_hz']),draw=t.read32(sy['nes_draw_hz']),faults=t.read32(sy['nes_faults']))
  row.update({n:t.read32(sy[n]) for n in ['nes_render_divisor','nes_draw_frame_us','nes_skip_frame_us','nes_clock_drops'] if n in sy})
  rows.append(row);print(json.dumps(row),flush=True);time.sleep(.5)
(root/'Release'/('joystick_audio_v'+manifest['version']+'.json')).write_text(json.dumps(rows,indent=2),encoding='utf-8')
