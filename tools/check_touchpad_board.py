"""Read small live diagnostic state; do not capture video or inject controls."""
from pathlib import Path
import struct,json,time,hashlib
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
root=Path(__file__).resolve().parents[1]
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 symbols=list(ELFFile(f).get_section_by_name('.symtab').iter_symbols())
 sym={s.name:s['st_value'] for s in symbols if s.name}
 touch=next(s['st_value'] for s in symbols if s.name=='state' and s['st_size']==16)
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
options={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':100000,'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=options) as session:
 t=session.target;t.halt()
 try:
  values=struct.unpack('<HHBB2xII',bytes(t.read_memory_block8(touch,16)))
  report={'touchpad':dict(zip(['raw','baseline','ready','pressed','samples','errors'],values)),
   'nes':{n:t.read32(sym[n]) for n in ['nes_faults','nes_logic_hz','nes_draw_hz','nes_logic_total']},
   'cfsr':t.read32(0xe000ed28),'hfsr':t.read32(0xe000ed2c),'tim2_psc':t.read32(0x40000028),
   'gpioa_moder':hex(t.read32(0x40020000)),'hardware_scope':'live calibration/idle state; physical touch press not controlled',
   'bin_sha256':hashlib.sha256((root/'Release/NesFire_v0.3.bin').read_bytes()).hexdigest()}
 finally:t.resume()
(root/'Release/board_touchpad_v0.3.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
