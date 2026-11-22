"""Pinned independent NES tests on actual compiled ARM firmware; no board.
Exit 1 for failures; --record allows a deliberately incomplete baseline.
Never modifies a test ROM or imports it into the user's game library.
"""
import argparse,hashlib,json,re,struct,time
from pathlib import Path
from unicorn import UC_HOOK_CODE
from unicorn.arm_const import *
from test_mmc3_arm import NesArm,ROOT,STOP

BASE=ROOT/'Tests/standard'
DEFAULTS=[
 'instr_test-v5/rom_singles/01-basics.nes',
 'instr_test-v5/rom_singles/02-implied.nes',
 'instr_test-v5/rom_singles/03-immediate.nes',
 'instr_test-v5/rom_singles/12-jmp_jsr.nes',
 'instr_test-v5/rom_singles/13-rts.nes',
 'instr_test-v5/rom_singles/15-brk.nes',
 'instr_misc/rom_singles/01-abs_x_wrap.nes',
 'instr_misc/rom_singles/02-branch_wrap.nes',
 'instr_timing/rom_singles/2-branch_timing.nes',
 'cpu_interrupts_v2/rom_singles/1-cli_latency.nes',
 'ppu_vbl_nmi/rom_singles/01-vbl_basics.nes',
 'ppu_vbl_nmi/rom_singles/04-nmi_control.nes',
 'apu_test/rom_singles/1-len_ctr.nes',
 'apu_test/rom_singles/7-dmc_basics.nes',
]

def assets():
    manifest=json.loads((BASE/'manifest.json').read_text(encoding='utf-8'))
    records={f['path']:f for f in manifest['files']}
    for name,f in records.items():
        p=(BASE/'roms'/name).resolve()
        assert p.is_relative_to((BASE/'roms').resolve())
        d=p.read_bytes();assert len(d)==f['bytes'] and hashlib.sha256(d).hexdigest()==f['sha256'],name
    return manifest,records

def pc(a):return (a.r32(a.addr('cpu_data')+124)-a.r32(a.addr('cpu_data')+132))&65535

def blargg(name,max_frames):
    a=NesArm();raw=(BASE/'roms'/name).read_bytes();start=time.monotonic()
    faults=[]
    def fault(u,*args):
        if len(faults)<4:faults.append({'arg0':u.reg_read(UC_ARM_REG_R0),'arg1':u.reg_read(UC_ARM_REG_R1)})
    a.u.hook_add(UC_HOOK_CODE,fault,begin=a.addr('debug_6502')&~1,end=a.addr('debug_6502')&~1)
    row={'test':name,'kind':'blargg','result':'TIMEOUT','frame_limit':max_frames}
    load=a.load(raw);row['load_code']=load
    if load:row['result']='LOAD_REJECTED';return row
    sram=a.r32(a.addr('NES_SRAM'));status=None;message='';signature=False
    try:
        for frame in range(1,max_frames+1):
            a.call('Nes_Frame',0)
            # Audio consumer runs at the virtual frame's sample count, never
            # using board DMA; its lack of cycle-level CPU coupling remains visible.
            samples=frame*11025//60-(frame-1)*11025//60
            a.call('apu_process',0x6c070000,samples)
            data=bytes(a.u.mem_read(sram,512));signature=data[1:4]==b'\xde\xb0\x61'
            if signature:
                status=data[0];message=data[4:].split(b'\0')[0].decode('ascii','replace')
                if status<128:
                    row['result']='PASS' if status==0 else 'FAIL';break
                if status==129:row['result']='RESET_REQUIRED';break
            if faults:row['result']='CPU_FAULT';break
        row.update(frames=frame,status=status,protocol_signature=signature,message=message,pc=f'{pc(a):04X}',faults=faults)
    except Exception as exc:row.update(result='EXECUTION_ERROR',error=str(exc),faults=faults)
    row['seconds']=round(time.monotonic()-start,3)
    return row

def nestest(limit=8991):
    a=NesArm();raw=(BASE/'roms/other/nestest.nes').read_bytes();assert a.load(raw)==0
    a.call('cpu_start_fds',0xc000) # entry setter only; Mapper remains NROM
    base=a.addr('cpu_data');ram=a.r32(a.addr('NES_RAM'))
    # The published automation trace specifies these starting registers; this
    # is an explicit harness fixture, not a claim about hardware power-on state.
    a.u.mem_write(base+100,struct.pack('<I',1));a.u.mem_write(base+120,struct.pack('<I',4))
    a.u.mem_write(base+128,struct.pack('<I',ram+0x1fd));a.u.mem_write(a.addr('clocks'),struct.pack('<I',7))
    expected=[]
    pattern=re.compile(r'^([0-9A-F]{4}).* A:([0-9A-F]{2}) X:([0-9A-F]{2}) Y:([0-9A-F]{2}) P:([0-9A-F]{2}) SP:([0-9A-F]{2}).* CYC:(\d+)')
    for line in (BASE/'roms/other/nestest.log').read_text(encoding='ascii').splitlines()[:limit]:
        match=pattern.match(line);assert match,line
        values=match.groups();expected.append(dict(zip(['PC','A','X','Y','P','SP','CYC'],[int(v,16) for v in values[:6]]+[int(values[6])])))
    handlers=set(v&~1 for v in struct.unpack('<256I',a.u.mem_read(a.addr('op_table'),1024)))
    row={'test':'other/nestest.nes','kind':'reference_trace','result':'TIMEOUT','requested_lines':len(expected),
         'initial_state':'C000 A00 X00 Y00 P24 SPFD CYC7, per published automation log'}
    compared=0;first_cycle=None
    def check(u,address,size,data):
        nonlocal compared,first_cycle
        if address not in handlers:return
        nz=u.reg_read(UC_ARM_REG_R3);flags=u.reg_read(UC_ARM_REG_R8)
        actual={'PC':(u.reg_read(UC_ARM_REG_R9)-a.r32(base+132)-1)&65535,
                'A':u.reg_read(UC_ARM_REG_R5)>>24,'X':u.reg_read(UC_ARM_REG_R6)>>24,'Y':u.reg_read(UC_ARM_REG_R7)>>24,
                'P':32|(flags&0x4d)|(128 if nz&0x80000000 else 0)|(2 if not(nz&255) else 0),
                'SP':a.read8(base+128),'CYC':a.r32(a.addr('clocks'))}
        want=expected[compared]
        if actual['CYC']!=want['CYC'] and first_cycle is None:first_cycle={'line':compared+1,'expected':want,'actual':actual.copy()}
        if any(actual[k]!=want[k] for k in ('PC','A','X','Y','P','SP')):
            row.update(result='FAIL',first_functional_mismatch={'line':compared+1,'expected':want,'actual':actual});u.emu_stop();return
        compared+=1
        if compared==len(expected):row['result']='PASS' if first_cycle is None else 'FAIL';u.emu_stop()
    a.u.hook_add(UC_HOOK_CODE,check,begin=min(handlers),end=max(handlers))
    try:a.call('run6502',100000*256)
    except RuntimeError:
        if row['result']=='TIMEOUT':raise
    row.update(functional_lines_matched=compared,first_cycle_mismatch=first_cycle)
    return row

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('tests',nargs='*');parser.add_argument('--frames',type=int,default=600)
    parser.add_argument('--nestest',action='store_true');parser.add_argument('--trace-lines',type=int,default=8991)
    parser.add_argument('--record',action='store_true');parser.add_argument('--out',type=Path,default=ROOT/'Tests/nes_output/standard_results.json')
    args=parser.parse_args();manifest,records=assets();results=[]
    if args.nestest:results.append(nestest(args.trace_lines));print(json.dumps(results[-1]),flush=True)
    tests=args.tests or ([] if args.nestest else DEFAULTS)
    for name in tests:
        if name not in records:parser.error('Not a pinned test asset: '+name)
        row=blargg(name,args.frames);results.append(row);print(json.dumps(row),flush=True)
    counts={k:sum(r['result']==k for r in results) for k in sorted({r['result'] for r in results})}
    report={'result':'PASS' if all(r['result']=='PASS' for r in results) else 'INCOMPLETE','hardware_tested':False,
            'upstream':{'repository':manifest['repository'],'commit':manifest['commit']},'counts':counts,'tests':results,
            'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
    args.out.parent.mkdir(exist_ok=True,parents=True);args.out.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print('SUMMARY',json.dumps(counts),flush=True)
    raise SystemExit(0 if args.record or report['result']=='PASS' else 1)
if __name__=='__main__':main()
