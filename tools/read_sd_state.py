"""Read SD diagnostics from a running target; no halt/reset/Flash programming."""
import json,struct,hashlib,time
from pathlib import Path
from elftools.elf.elffile import ELFFile
from pyocd.core.helpers import ConnectHelper

root=Path(__file__).resolve().parents[1]
with (root/'Project/Output/Fire_F407ZG.axf').open('rb') as f:
    symbols={s.name:s['st_value'] for s in ELFFile(f).get_section_by_name('.symtab').iter_symbols() if s.name}
m=json.loads((root/'Release/manifest.json').read_text(encoding='utf-8-sig'))
expected=(root/'Release'/(m['firmware_prefix']+'.bin')).read_bytes()
pack=next(root.parent.glob('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack'))
opts={'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':1000000,'connect_mode':'attach',
      'auto_unlock':False,'resume_on_disconnect':False,'cache.enable_memory':False,
      'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
session=ConnectHelper.session_with_chosen_probe(unique_id='FS-00000000',options=opts)
if session is None:raise SystemExit('CMSIS-DAP not available')
with session:
    t=session.target
    report={'reset':False,'halt_requested':False,'flash_written':False,'state':str(t.get_state())}
    report['flash_vectors_match']=bytes(t.read_memory_block8(0x08000000,256))==expected[:256]
    report['sdio']={n:hex(t.read32(0x40012c00+off)) for n,off in [('POWER',0),('CLKCR',4),('ARG',8),('CMD',12),('RESPCMD',16),('RESP1',20),('DCTRL',44),('STA',52)]}
    report['cpu_faults']={n:hex(t.read32(address)) for n,address in [('ICSR',0xe000ed04),('CFSR',0xe000ed28),('HFSR',0xe000ed2c),('MMFAR',0xe000ed34),('BFAR',0xe000ed38),('PCSR',0xe000101c)]}
    report['rcc']={n:hex(t.read32(0x40023800+off)) for n,off in [('CR',0),('PLLCFGR',4),('CFGR',8),('APB2ENR',0x44)]}
    report['gpioc']={n:hex(t.read32(0x40020800+off)) for n,off in [('MODER',0),('PUPDR',12),('IDR',16),('AFRH',36)]}
    report['gpiod']={n:hex(t.read32(0x40020c00+off)) for n,off in [('MODER',0),('PUPDR',12),('IDR',16),('AFRL',32)]}
    if report['flash_vectors_match']:
        for name,size in [('g_sd_handle',132),('g_sd_card_info',32),('sd_initialised',1),('sd_active',1),('sd_count',4),('app_state',1),('nes_sd_file_reads',4),('status',4),('uwTick',4),('nes_audio_blocks',4)]:
            if name in symbols:report[name]=bytes(t.read_memory_block8(symbols[name],size)).hex()
        ptr=t.read32(symbols['status']);report['status_text']=bytes(t.read_memory_block8(ptr,80)).split(b'\0')[0].decode('ascii','replace')
        report['ticks']=[t.read32(symbols['uwTick'])];time.sleep(.2);report['ticks'].append(t.read32(symbols['uwTick']))
        handle=bytes.fromhex(report['g_sd_handle'])
        report['sd_handle_words']=[hex(v) for v in struct.unpack('<33I',handle)]
    (root/'Release/sd_readonly_state.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps(report,indent=2))
