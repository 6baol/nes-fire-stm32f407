"""Program the published firmware over CMSIS-DAP and verify all Flash bytes."""
import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def read_complete(target,address,size):
    result=bytearray()
    for offset in range(0,size,1024):
        result.extend(target.read_memory_block8(address+offset,min(1024,size-offset)))
    return bytes(result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-only', action='store_true')
    parser.add_argument('--probe', default='FS-00000000')
    parser.add_argument('--frequency', type=int, default=100000)
    parser.add_argument('--manifest', type=Path, default=ROOT/'Release/manifest.json',
                        help='release manifest; artifacts are resolved beside it')
    parser.add_argument('--pack', type=Path, help='local Keil.STM32F4xx_DFP pack')
    parser.add_argument('--check-files', action='store_true',
                        help='check the release files without connecting to the probe')
    args = parser.parse_args()
    manifest_path = args.manifest.resolve()
    release = manifest_path.parent
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig'))
    version = manifest['version']
    prefix = manifest['firmware_prefix']
    if any(not re.fullmatch(r'[A-Za-z0-9._-]+', value) or value in ('.', '..') for value in (version, prefix)):
        raise ValueError('Invalid version or firmware prefix in release manifest.')
    images = {}
    for ext in ('hex', 'bin'):
        path = release/(prefix+'.'+ext)
        images[ext] = path.read_bytes()
        if hashlib.sha256(images[ext]).hexdigest() != manifest['files'][path.name]['sha256']:
            raise RuntimeError('Release hash mismatch: '+path.name)
    expected = images['bin']
    if not expected or len(expected) > 0x100000:
        raise RuntimeError('Firmware outside STM32F407ZG 1 MiB Flash.')
    if args.check_files:
        print(f'RELEASE FILES VERIFIED: {prefix}, {len(expected)} bytes')
        return

    from pyocd.core.helpers import ConnectHelper
    from pyocd.core.target import Target

    hardware_reset = getattr(Target.ResetType,"HARDWARE",None) or Target.ResetType.HW
    pack = args.pack
    if pack is None:
        for pattern, base in (('.tools/packs/Keil.STM32F4xx_DFP*.pack', ROOT.parent),
                              ('*/4-*/MDK-KEIL与芯片包/芯片包/Keil.STM32F4xx_DFP.2.15.0.pack', ROOT.parent)):
            pack = next(base.glob(pattern), None)
            if pack is not None:
                break
    if pack is None or not pack.is_file():
        raise FileNotFoundError('STM32F4xx Device Family Pack not found. Supply --pack.')
    options = {'target_override':'stm32f407zgtx','pack':[str(pack)],'frequency':args.frequency,
               'connect_mode':'halt','auto_unlock':False,'resume_on_disconnect':False,
               'cache.enable_memory':False,'cmsis_dap.limit_packets':True,'cmsis_dap.deferred_transfers':False}
    session = ConnectHelper.session_with_chosen_probe(unique_id=args.probe, options=options)
    if session is None:
        raise RuntimeError('CMSIS-DAP not found.')
    with session:
        target = session.target
        target.halt()
        if target.read32(0xE0042000) & 0xFFF != 0x413:
            raise RuntimeError('Unexpected STM32 device ID.')
        if not args.verify_only:
            # Reset application clocks/peripherals before running the RAM Flash algorithm.
            target.reset_and_halt(hardware_reset)
            # F407: four 16 KiB sectors, one 64 KiB, then 128 KiB sectors.
            ends = [0x4000,0x8000,0xc000,0x10000,0x20000,0x40000,0x60000,0x80000,0xa0000,0xc0000,0xe0000,0x100000]
            size = next(end for end in ends if end >= len(expected))
            backup = ROOT.parent/'backups'/('flash_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.bin')
            backup.parent.mkdir(exist_ok=True)
            previous=read_complete(target,0x08000000,size)
            backup.write_bytes(previous)
            print('Saved touched sectors:',backup,flush=True)
            region = target.memory_map.get_region_for_address(0x08000000)
            builder = region.flash.get_flash_builder()
            builder.enable_double_buffer(False)
            builder.add_data(0x08000000,list(expected))
            tail=previous[len(expected):]
            if tail.strip(b'\xff'):
                builder.add_data(0x08000000+len(expected),list(tail))
            print('Programming with one Flash buffer...',flush=True)
            last_progress = [-1]
            def progress(fraction):
                percent = int(fraction*10)*10
                if percent != last_progress[0]:
                    print('Flash progress:',percent,'%',flush=True)
                    last_progress[0] = percent
            builder.program(chip_erase='sector',smart_flash=False,fast_verify=False,progress_cb=progress)
            print('Flash programming completed.',flush=True)
            target.reset_and_halt(hardware_reset)
        print('Reading back',len(expected),'bytes...',flush=True)
        actual = read_complete(target,0x08000000,len(expected))
        if actual != expected:
            raise RuntimeError('Flash readback mismatch; target left halted.')
        report = {'version':version,'programmer':f'pyOCD CMSIS-DAP / SWD {args.frequency}Hz',
                  'bytes_verified':len(actual),'sha256':hashlib.sha256(actual).hexdigest(),
                  'full_readback_match':True,'verify_only':args.verify_only}
        if not args.verify_only:
            if read_complete(target,0x08000000+len(expected),len(tail)) != tail:
                raise RuntimeError('Preserved sector tail readback mismatch; target left halted.')
            report.update(backup=str(backup),sector_bytes_verified=size,
                          preserved_tail_bytes=len(tail))
        report_path = release/('dap_download_v'+version+'.json')
        if report_path.exists():
            report_path = report_path.with_name(report_path.stem+'_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.json')
        report_path.write_text(
            json.dumps(report,indent=2),encoding='utf-8')
        print('FULL FLASH READBACK VERIFIED:',prefix,flush=True)
        if args.verify_only:
            target.resume()
        else:
            target.reset(hardware_reset)


if __name__ == '__main__':
    main()
