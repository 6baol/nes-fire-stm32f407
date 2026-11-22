"""SWD runtime checks and one-shot video captures; always release injected input."""
from pathlib import Path
import json,struct,time,hashlib
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
root=Path(__file__).resolve().parents[1]
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 tab=ELFFile(f).get_section_by_name('.symtab');sym={s.name:s['st_value'] for s in tab.iter_symbols() if s.name}
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
options={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':100000,'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
reports=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=options) as session:
 t=session.target
 def setpad(value):t.halt();t.write8(sym['nes_test_pad'],value);t.resume()
 def snapshot(name):
  t.halt();t.write32(sym['nes_capture_request'],1);before=t.read32(sym['nes_capture_ready']);t.resume()
  for attempt in range(10):
   time.sleep(.5);t.halt();ready=t.read32(sym['nes_capture_ready'])
   if ready!=before:break
   t.resume()
  else:raise RuntimeError('Capture not completed')
  report={'scene':name,'capture':ready,'pc':hex(t.read_core_register('pc')),'xpsr':hex(t.read_core_register('xpsr')),
     'faults':t.read32(sym['nes_faults']),'logic_hz':t.read32(sym['nes_logic_hz']),'draw_hz':t.read32(sym['nes_draw_hz']),
     'logic_total':t.read32(sym['nes_logic_total']),'draw_total':t.read32(sym['nes_draw_total']),
     'lcd_id':hex(t.read32(sym['lcd_id'])) if 'lcd_id' in sym else None,
     'cfsr':hex(t.read32(0xe000ed28)),'hfsr':hex(t.read32(0xe000ed2c))}
  ram=t.read32(sym['NES_RAM']);report['ram_0_32']=bytes(t.read_memory_block8(ram,32)).hex()
  image=b''.join(bytes(t.read_memory_block8(0x6c040000+offset,min(1024,256*240*2-offset))) for offset in range(0,256*240*2,1024));t.resume()
  rgb=bytearray()
  for (c,) in struct.iter_unpack('<H',image):rgb.extend((((c>>11)&31)*255//31,((c>>5)&63)*255//63,(c&31)*255//31))
  (root/'Release'/('board_'+name+'.ppm')).write_bytes(b'P6\n256 240\n255\n'+rgb)
  report['video_sha256']=hashlib.sha256(image).hexdigest();reports.append(report);print(json.dumps(report),flush=True)
  (root/'Release/board_smb_partial.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
 try:
  t.reset()
  time.sleep(3)
  t.halt();print('Runtime preflight:', {n:t.read32(sym[n]) for n in ['nes_logic_total','nes_draw_total','nes_faults']}, 'PC',hex(t.read_core_register('pc')),'CFSR',hex(t.read32(0xe000ed28)),flush=True);t.resume()
  snapshot('title')
  setpad(8);time.sleep(.2);setpad(0);time.sleep(3);snapshot('start')
  setpad(128);time.sleep(.8);setpad(129);time.sleep(.1);snapshot('jump');setpad(0);time.sleep(.3);snapshot('move_jump')
 finally:
  setpad(0);t.reset()
(root/'Release/board_smb.json').write_text(json.dumps({'hardware_tested':True,'method':'live SWD globals and requested PPU RGB565 capture (not LCD photo)','reports':reports},indent=2),encoding='utf-8')
