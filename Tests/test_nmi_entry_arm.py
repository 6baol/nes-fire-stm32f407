"""Pending vblank NMI must pre-empt a CPU slice and consume seven cycles."""
import struct
from test_mmc3_arm import NesArm

a=NesArm();prg=bytearray([0xea])*32768
prg[:5]=bytes.fromhex('e6 10 4c 00 80')
prg[0x100:0x103]=bytes.fromhex('e6 11 40')
prg[-6:]=struct.pack('<HHH',0x8100,0x8000,0x8100)
rom=b'NES\x1a'+bytes([2,1])+bytes(10)+prg+bytes(8192)
assert a.load(rom)==0
ram=a.r32(a.addr('NES_RAM'));before=a.r32(a.addr('clocks'))
a.u.mem_write(a.addr('cpunmi'),struct.pack('<I',1))
a.call('run6502',256)
assert a.read8(ram+0x10)==0,'Mainline executed before pending NMI was dispatched'
assert a.read8(ram+0x11)==0,'NMI latency did not consume the slice'
assert a.r32(a.addr('clocks'))-before==7,'NMI latency absent from CPU/APU clock'
assert a.r32(a.addr('cpunmi'))==0
a.call('run6502',30*256)
assert a.read8(ram+0x11)==1,'NMI handler did not execute/return'
assert a.read8(ram+0x10)>0,'RTI did not resume interrupted code'
assert a.r32(a.addr('nes_faults'))==0
print('PASS: pending NMI pre-empts slice, costs 7 cycles, handler/RTI resume mainline')
