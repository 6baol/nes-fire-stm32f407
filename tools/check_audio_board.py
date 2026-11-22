"""Read the current audio firmware state while the CPU keeps running."""
from pathlib import Path
import json,time,hashlib
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper
root=Path(__file__).resolve().parents[1]
m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
bin=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes()
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
 sy={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach','auto_unlock':False,'resume_on_disconnect':True,'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
rows=[]
with ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts) as s:
 t=s.target
 assert bytes(t.read_memory_block8(0x08000000,256))==bin[:256], 'Board vectors do not match AXF'
 for i in range(5):
  row={n:t.read32(sy[n]) for n in ['nes_audio_ready','nes_audio_blocks','nes_audio_dma_errors','nes_audio_codec_error','nes_audio_nonzero','nes_audio_peak','nes_audio_max_us','nes_apu_queue_drops','nes_faults','nes_logic_hz','nes_draw_hz','nes_logic_total','nes_render_divisor','nes_draw_frame_us','nes_skip_frame_us','nes_clock_drops']}
  row.update(wall_seconds=time.monotonic(),dma_ndtr=t.read32(0x40026074),i2scfgr=hex(t.read32(0x4000381c)),i2spr=hex(t.read32(0x40003820)),cfsr=t.read32(0xe000ed28),hfsr=t.read32(0xe000ed2c))
  print(json.dumps(row),flush=True);rows.append(row);time.sleep(2)
report={'version':m['version'],'bin_sha256':hashlib.sha256(bin).hexdigest(),'scope':'WM8978 I2C ACK and live I2S/DMA/synthesis counters; audibility requires listener confirmation','rows':rows}
(root/'Release'/('board_audio_v'+m['version']+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
