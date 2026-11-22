"""Build an isolated STM32F407 SD validation image with installed Arm Compiler 6 tools."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]
PROJECT = ROOT / 'Project'
NAME = 'Fire_F407ZG'


def arm_run(arm_bin, tool, *options):
    executable = arm_bin / (tool + ('.exe' if os.name == 'nt' else ''))
    result = subprocess.run([executable, *map(str, options)], cwd=PROJECT, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, errors='replace')
    return result.returncode, result.stdout


def scatter_file(target, stage):
    cpu = target.findtext('TargetOption/TargetCommonOption/Cpu')
    rom_addr, rom_size = re.search(r'\bIROM\((0x[\da-fA-F]+),(0x[\da-fA-F]+)\)', cpu).groups()
    ram_addr, ram_size = re.search(r'\bIRAM\((0x[\da-fA-F]+),(0x[\da-fA-F]+)\)', cpu).groups()
    scatter = stage / (NAME + '.sct')
    scatter.write_text(f'''LR_IROM1 {rom_addr} {rom_size} {{
  ER_IROM1 {rom_addr} {rom_size} {{
    *.o (RESET, +First)
    *(InRoot$$Sections)
    .ANY (+RO)
    .ANY (+XO)
  }}
  RW_IRAM1 {ram_addr} {ram_size} {{ .ANY (+RW +ZI) }}
}}
''', encoding='ascii')
    return scatter


def build(args, stage, log):
    target = ET.parse(PROJECT / (NAME + '.uvprojx')).find('Targets/Target')
    arm_options = target.find('TargetOption/TargetArmAds')
    comp = arm_options.find('Cads/VariousControls')
    assembly = arm_options.find('Aads/VariousControls')
    includes = [flag for part in comp.findtext('IncludePath').split(';') if part
                for flag in ('-I', str((PROJECT / part.replace('\\', '/')).resolve()))]
    asm_includes = [flag for part in assembly.findtext('IncludePath').split(';') if part
                    for flag in ('-I', str((PROJECT / part.replace('\\', '/')).resolve()))]
    defines = ['-D' + value for value in comp.findtext('Define').split(',') if value]
    source_files = [(PROJECT / entry.findtext('FilePath').replace('\\', '/')).resolve()
                    for entry in target.findall('Groups/Group/Files/File')
                    if entry.findtext('FileType') in ('1', '2')]
    compiler_args = ['--target=arm-arm-none-eabi', '-mcpu=cortex-m4', '-mfpu=fpv4-sp-d16',
                     '-mfloat-abi=hard', '-std=gnu11', '-g', '-funsigned-char', '-fshort-enums',
                     '-fshort-wchar', '-fdata-sections', '-ffunction-sections', '-D__MICROLIB',
                     *comp.findtext('MiscControls').split(), *includes, *defines]
    asm_args = ['--cpu=Cortex-M4.fp.sp', '--pd', '__MICROLIB SETA 1', '--debug', *asm_includes]

    def compile_file(source):
        output = stage / (source.stem + '.o')
        if source.suffix == '.s':
            result = arm_run(args.arm_bin, 'armasm', *asm_args, '-o', output, source)
        else:
            result = arm_run(args.arm_bin, 'armclang', *compiler_args, '-c', '-o', output, source)
        return source.name, output, result

    version_code, version_text = arm_run(args.arm_bin, 'armclang', '--version')
    log.write(version_text + '\n')
    if version_code or not re.search(r'Compiler(?: for Embedded)? 6\.', version_text, re.IGNORECASE):
        raise RuntimeError('An available Arm Compiler 6 installation is required.')
    with ThreadPoolExecutor(max_workers=min(os.cpu_count() or 2, 8)) as executor:
        objects = list(executor.map(compile_file, source_files))
    for source, output, (code, message) in objects:
        if code or message or not output.is_file():
            log.write(f'{source} (exit {code})\n{message}\n')
    if any(code or not output.is_file() or re.search(r'\bwarning:', message, re.IGNORECASE)
           for _, output, (code, message) in objects):
        raise RuntimeError('Arm validation compilation reported errors or warnings.')

    axf = stage / (NAME + '.axf')
    map_path = stage / (NAME + '.map')
    scatter = scatter_file(target, stage)
    code, message = arm_run(args.arm_bin, 'armlink', '--cpu=Cortex-M4.fp.sp',
                            *(obj for _, obj, _ in objects), '--library_type=microlib', '--strict',
                            '--scatter', scatter, '--summary_stderr', '--map', '--symbols',
                            '--info', 'summarysizes', '--list', map_path, '-o', axf)
    log.write(message)
    if code or re.search(r'\bwarning:', message, re.IGNORECASE):
        raise RuntimeError('Arm validation link reported errors or warnings.')
    for suffix, format_arg in (('.bin', '--bin'), ('.hex', '--i32')):
        code, message = arm_run(args.arm_bin, 'fromelf', format_arg, '--output', stage / (NAME + suffix), axf)
        log.write(message)
        if code:
            raise RuntimeError(f'Arm validation conversion failed for {suffix}.')
    for suffix in ('.axf', '.bin', '.hex', '.map'):
        artifact = stage / (NAME + suffix)
        if not artifact.is_file():
            raise RuntimeError(f'Arm validation output is missing: {artifact.name}')
    for suffix in ('.axf', '.bin', '.hex', '.map'):
        shutil.copyfile(stage / (NAME + suffix), args.output_dir / (args.prefix + suffix))
    print(f'{len(objects)} sources compiled and linked with Arm Compiler 6.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--arm-bin', required=True, type=Path, help='installed Arm Compiler 6 bin directory')
    parser.add_argument('--output-dir', required=True, type=Path, help='separate validation output directory')
    parser.add_argument('--prefix', default=NAME, help='base name for the validation artifacts')
    args = parser.parse_args()
    args.arm_bin = args.arm_bin.resolve()
    args.output_dir = args.output_dir.resolve()
    if not args.arm_bin.is_dir() or not re.fullmatch(r'[a-zA-Z0-9._-]+', args.prefix):
        parser.error('Select an Arm Compiler 6 bin directory and a simple filename prefix.')
    args.output_dir.mkdir(parents=True, exist_ok=True)
    log_path = args.output_dir / (args.prefix + '.validation.log')
    try:
        with (TemporaryDirectory(prefix='arm-validation-', dir=args.output_dir) as stage,
              log_path.open('w', encoding='utf-8') as log):
            build(args, Path(stage), log)
    except (OSError, RuntimeError) as exc:
        print(f'{exc}\nSee {log_path}', file=sys.stderr)
        return 1
    print(log_path)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
