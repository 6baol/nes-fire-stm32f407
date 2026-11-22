"""Observe touch input on the current firmware without stopping the CPU."""
from pathlib import Path
import argparse,struct,json,time,hashlib
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
p=argparse.ArgumentParser();p.add_argument('--seconds',type=float,default=45);args=p.parse_args()
root=Path(__file__).resolve().parents[1]
manifest=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
image=(root/'Release'/(manifest['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 file='';local={};symbols={}
 for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols():
  if s['st_info']['type']=='STT_FILE':file=s.name
  if s.name:symbols[s.name]=s['st_value']
  if file=='bsp_touchpad.c':local[s.name]=s['st_value']
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
rows=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as session:
 t=session.target
 assert bytes(t.read_memory_block8(0x08000000,256))==image[:256], 'Live vectors do not match current AXF'
 print('READY: observing live touch input, CPU stays running',flush=True)
 start=time.monotonic()
 while time.monotonic()-start<args.seconds:
  vals=struct.unpack('<HHBB2xII',bytes(t.read_memory_block8(local['state'],16)))
  row=dict(zip(['raw','baseline','ready','pressed','samples','errors'],vals))
  row.update(seconds=round(time.monotonic()-start,2),pad=t.read8(symbols['PADdata']),
      irq=t.read32(symbols['touchpad_irq_count']),presses=t.read32(symbols['touchpad_press_count']),releases=t.read32(symbols['touchpad_release_count']))
  rows.append(row);print(json.dumps(row),flush=True);time.sleep(.35)
 report={'version':manifest['version'],'bin_sha256':hashlib.sha256(image).hexdigest(),'rows':rows}
(root/'Release'/('touchpad_trace_v'+manifest['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
