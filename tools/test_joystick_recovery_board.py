"""Observe joystick health; optional controlled injection of the HAL ADC error flag."""
from pathlib import Path
import argparse,json,struct,time,hashlib
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--inject-driver-error',action='store_true');args=p.parse_args()
root=Path(__file__).resolve().parents[1];m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
image=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes();local={};sy={};field_offset=None
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 elf=ELFFile(f);file=''
 for s in elf.get_section_by_name('.symtab').iter_symbols():
  if s['st_info']['type']=='STT_FILE':file=s.name
  if s.name:sy[s.name]=s['st_value']
  if file=='bsp_joystick.c':local[s.name]=s['st_value']
 for cu in elf.get_dwarf_info().iter_CUs():
  for die in cu.iter_DIEs():
   if die.tag=='DW_TAG_typedef' and die.attributes.get('DW_AT_name') and die.attributes['DW_AT_name'].value==b'ADC_HandleTypeDef':
    st=die.get_DIE_from_attribute('DW_AT_type')
    for c in st.iter_children():
     if c.tag=='DW_TAG_member' and c.attributes['DW_AT_name'].value==b'State':field_offset=c.attributes['DW_AT_data_member_location'].value
    break
  if field_offset is not None:break
assert field_offset is not None
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
results=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as sess:
 t=sess.target;assert bytes(t.read_memory_block8(0x08000000,256))==image[:256]
 def sample():
  return dict(zip(['raw_x','raw_y','center_x','center_y','x','y','calibrated','healthy','errors','pairs','max_gap_ms'],struct.unpack('<4H2fBB2x3I',bytes(t.read_memory_block8(local['state'],32)))))
 before=sample()
 for _ in range(20):
  if before['calibrated'] and before['healthy']:break
  time.sleep(.2);before=sample()
 assert before['calibrated'] and before['healthy'],before
 center=(before['center_x'],before['center_y']);print('Initial calibrated centre:',center,flush=True)
 if args.inject_driver_error:
  for i in range(3):
   address=local['adc']+field_offset
   t.halt()
   try:
    state=t.read32(address);t.write32(address,state|0x10)
    assert t.read32(address)&0x10
   finally:t.resume()
   time.sleep(.15)
   current=sample();current['adc_error_flag_after_recovery']=bool(t.read32(address)&0x10)
   assert current['calibrated'] and current['healthy'] and not current['adc_error_flag_after_recovery'],current
   assert (current['center_x'],current['center_y'])==center,current
   results.append(current);print('Recovered injection',i+1,json.dumps(current),flush=True)
 report={'version':m['version'],'result':'PASS','method':'live board; controlled HAL ADC software error-flag injection, not physical ADC failure' if args.inject_driver_error else 'read only','bin_sha256':hashlib.sha256(image).hexdigest(),'initial':before,'recoveries':results,'logic_hz':t.read32(sy['nes_logic_hz']),'draw_hz':t.read32(sy['nes_draw_hz']),'cpu_faults':t.read32(sy['nes_faults']),'dma_errors':t.read32(sy['nes_audio_dma_errors'])}
(root/'Release'/('joystick_recovery_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
print(json.dumps(report,indent=2))
