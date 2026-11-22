"""Exercise the cover library on the board and leave SMB2 selected in the menu."""
from pathlib import Path
import struct,json,time,hashlib
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
root=Path(__file__).resolve().parents[1]
m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
image=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 sy={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach',
      'auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,
      'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
rows=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as session:
 t=session.target
 def pad(v):t.halt();t.write8(sy['nes_test_pad'],v);t.resume()
 def sample(expected):
  t.halt()
  try:
   index,count,first,audio,touch=struct.unpack('<hBBBB',bytes(t.read_memory_block8(sy['menu'],6)))
   row={'index':index,'count':count,'first':first,'audio_ok':audio,'touch_ok':touch,
        'app_state':t.read8(sy['app_state']),'redraw_us':t.read32(sy['nes_menu_redraw_us']),
        'updates':t.read32(sy['nes_menu_updates']),'faults':t.read32(sy['nes_faults']),
        'cfsr':t.read32(0xe000ed28),'hfsr':t.read32(0xe000ed2c),
        'audio_dma_errors':t.read32(sy['nes_audio_dma_errors'])}
   assert index==expected and row['app_state']==0 and count==3,row
   assert row['faults']==row['cfsr']==row['hfsr']==row['audio_dma_errors']==0,row
   assert row['redraw_us']<200000,row
   rows.append(row);print(json.dumps(row),flush=True)
  finally:t.resume()
 def move(v,expected):
  pad(v);time.sleep(.12);pad(0);time.sleep(.15);sample(expected)
 try:
  assert bytes(t.read_memory_block8(0x08000000,256))==image[:256]
  t.reset();time.sleep(3);sample(0)
  move(32,1);move(32,2);move(32,0);move(16,2);move(16,1)
 finally:pad(0)
report={'result':'PASS','version':m['version'],'hardware_tested':True,
        'scope':'board navigation, cover redraw timing and runtime flags; visual layout rendered separately from actual ARM LCD calls',
        'bin_sha256':hashlib.sha256(image).hexdigest(),'max_redraw_us':max(r['redraw_us'] for r in rows),'rows':rows}
(root/'Release'/('board_poster_menu_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print('PASS: cover menu navigation/scroll/wrap; SMB2 selected; input released',flush=True)
