"""FDS wavetable, envelopes, modulation and timestamped APU mix on real ARM."""
import struct,json,hashlib,wave
import numpy as np
from test_mmc3_arm import NesArm,ROOT

def synth():
    a=NesArm();a.u.mem_write(a.addr('MapperNo'),struct.pack('<I',20));a.call('apu_init')
    return a
def w(a,addr,value):a.call('FdsIo_Write',addr,value)
def r(a,addr):return a.call('FdsIo_Read',addr)
def time(a,cycles):a.u.mem_write(a.addr('clocks'),struct.pack('<I',cycles))
a=synth();w(a,0x4089,128);w(a,0x4040,25)
assert r(a,0x4040)==0
w(a,0x4023,3);assert r(a,0x4040)==0
w(a,0x4040,25);assert r(a,0x4040)==0,'Wave RAM writable without write gate'
w(a,0x4089,128);w(a,0x4040,255);assert r(a,0x4040)==63
w(a,0x4089,0);w(a,0x4040,0);assert r(a,0x4040)==63
w(a,0x4023,1);w(a,0x4089,128);w(a,0x4040,7)
w(a,0x4023,3);assert r(a,0x4040)==63
# New documented envelope period: 8*(e+1)*(master+1); master zero halts.
w(a,0x4083,0);w(a,0x408a,1);w(a,0x4080,128);w(a,0x4080,64)
time(a,15);assert r(a,0x4090)==64
time(a,16);assert r(a,0x4090)==65
w(a,0x4080,0);time(a,32);assert r(a,0x4090)==64
w(a,0x4084,128);w(a,0x4084,64);time(a,48);assert r(a,0x4092)==65
w(a,0x408a,0);time(a,10000);assert r(a,0x4092)==65
w(a,0x408a,1);w(a,0x4080,191);w(a,0x4080,64);time(a,20000)
assert r(a,0x4090)==127,'Manual gain above 32 incorrectly increased/wrapped'
w(a,0x4080,0);time(a,20016);assert r(a,0x4090)==126
w(a,0x4083,128);time(a,30000);assert r(a,0x4090)==126,'Halted wave advanced envelope'
# Long CPU intervals may overflow a 32-bit envelope sum. The optimized
# normal path must retain the wide fallback when the CPU clock wraps.
long=synth();w(long,0x4023,3);w(long,0x4083,0);w(long,0x408a,255)
w(long,0x4080,159);w(long,0x4080,63)
time(long,65536);assert r(long,0x4090)==95
time(long,65520);assert r(long,0x4090)==64,'Envelope sum overflow lost elapsed ticks'
# An odd playback step still addresses a *pair* of modulation steps.
odd=synth();w(odd,0x4023,3);w(odd,0x4086,255);w(odd,0x4087,15)
time(odd,32);assert r(odd,0x4095)==0
w(odd,0x4087,143);w(odd,0x4088,3);w(odd,0x4087,15)
time(odd,1024);assert r(odd,0x4095)==4,'Odd-position write missed first half of pair'
time(odd,1040);assert r(odd,0x4095)==4
time(odd,1056);assert r(odd,0x4095)==0,'Odd-position write corrupted the following entry'

def tone(master=0,counter=0,gain=0,modulated=False):
    a=synth();w(a,0x4023,3);w(a,0x4083,128);w(a,0x4089,128)
    for i in range(64):w(a,0x4040+i,0 if i<32 else 63)
    w(a,0x4080,160);w(a,0x4084,128|gain);w(a,0x4085,counter&127)
    w(a,0x4087,128)
    if modulated:
        for i in range(32):w(a,0x4088,1 if i<16 else 7)
        w(a,0x4086,30);w(a,0x4087,0)
    w(a,0x4089,master);w(a,0x4082,1031&255);w(a,0x4083,1031>>8)
    buf=0x6c0a0000;a.call('apu_process',buf,11025)
    pcm=bytes(a.u.mem_read(buf,11025));samples=np.frombuffer(pcm,dtype=np.uint8).astype(float)[200:]
    spectrum=np.abs(np.fft.rfft((samples-samples.mean())*np.hanning(len(samples))))
    freq=np.fft.rfftfreq(len(samples),1/11025);band=(freq>100)&(freq<1000)
    peak=freq[np.flatnonzero(band)[np.argmax(spectrum[band])]]
    assert a.r32(a.addr('nes_apu_queue_drops'))==0
    return a,pcm,peak,float(samples.ptp() if hasattr(samples,'ptp') else np.ptp(samples))
base,pcm,hz,amp=tone();assert abs(hz-440)<2 and amp>12,(hz,amp)
base.call('FdsAudio_Apply',0x4089,128)
held=[base.call('FdsAudio_Sample',162<<16) for _ in range(64)]
assert len(set(held))==1 and held[0]!=0,'Wave-write mode did not hold the last output'
base.call('FdsAudio_Apply',0x4080,128)
assert base.call('FdsAudio_Sample',162<<16)==0,'Direct volume zero was not immediate'
_,mod_pcm,mod_hz,_=tone(counter=16,gain=16)
assert abs(mod_hz-550)<2,'Static modulation pitch formula/gating incorrect'
amps=[]
for setting,ratio in [(1,2/3),(2,1/2),(3,2/5)]:
    _,_,_,value=tone(master=setting);assert abs(value/amp-ratio)<.06,(setting,value/amp);amps.append(value)
_,vibrato,_,_=tone(gain=8,modulated=True);assert vibrato!=pcm,'Mod table did not affect audio'
# Writes at future CPU timestamps take effect through the normal APU queue.
b=synth();w(b,0x4023,3);w(b,0x4089,128)
for i in range(64):w(b,0x4040+i,63 if i&32 else 0)
w(b,0x4080,160);w(b,0x4082,7);w(b,0x4083,4);w(b,0x4089,0)
time(b,16000);w(b,0x4080,128)
b.call('apu_process',0x6c0a0000,1000)
queued=np.frombuffer(bytes(b.u.mem_read(0x6c0a0000,1000)),dtype=np.uint8)
assert np.ptp(queued[:80])>10 and np.ptp(queued[300:])==0
out=ROOT/'Tests/nes_output/fds_wavetable_440hz.wav'
with wave.open(str(out),'wb') as wav:wav.setnchannels(1);wav.setsampwidth(1);wav.setframerate(11025);wav.writeframes(pcm)
report={'result':'PASS','hardware_tested':False,'scope':'real ARM FDS registers/APU mixer; synthetic waveform, not headphone recording',
        'tone_hz':hz,'static_modulated_hz':mod_hz,'pcm_range':[min(pcm),max(pcm)],
        'checks':['I/O and wave write gates','wave readback and 6-bit clamp','write-mode output hold and immediate mute','volume/mod envelopes and halt','long interval overflow fallback','odd-position modulation writes preserve paired entries',
                  'manual gain saturation','440Hz wavetable','550Hz static modulation','master-volume ratios',
                  'programmed modulation table','timestamped writes in APU queue','no APU queue drops'],
        'axf_sha256':hashlib.sha256((ROOT/'Project/Output/Fire_F407ZG.axf').read_bytes()).hexdigest()}
(ROOT/'Tests/nes_output/fds_audio_results.json').write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
