"""Explicit synthetic local speech test; emits a reviewable WAV sample."""
import base64
import json
from pathlib import Path
import sys
import time
import wave
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
from cosy_engine import CosyEngine

ROOT=Path(__file__).resolve().parents[1]
engine=CosyEngine()
report=dict(engine='CosyVoice3',humanVoiceVerified=False)
try:
    started=time.monotonic();engine.start()
    while engine.status()['phase']=='loading' and time.monotonic()-started<180:time.sleep(.2)
    assert engine.status()['phase']=='ready',engine.status()
    report['device']=engine.status()['device']
    report['loadSeconds']=round(time.monotonic()-started,2)
    results=[]
    for name,text,rate in [('cosy-wake','我在。',0),('cosy-demo','我在呀。今天想聊些什么？你也可以叫我帮忙。',0),('cosy-rate','好呀，我们慢慢来。',-2)]:
        started=time.monotonic();blocks=[];first=None;sample_rate=None
        for packet in engine.stream(text,dict(voice='',rate=rate,volume=80)):
            if first is None:first=round(time.monotonic()-started,2)
            sample_rate=packet['sampleRate'];blocks.append(base64.b64decode(packet['pcmBase64']))
        audio=b''.join(blocks)
        assert sample_rate and len(audio)>sample_rate//2 and any(audio)
        with wave.open(str(ROOT/'qa'/f'{name}.wav'),'wb') as output:
            output.setnchannels(1);output.setsampwidth(2);output.setframerate(sample_rate);output.writeframes(audio)
        results.append(dict(name=name,firstAudioSeconds=first,totalSeconds=round(time.monotonic()-started,2),audioSeconds=round(len(audio)/2/sample_rate,2),sampleRate=sample_rate))
        print(json.dumps(results[-1]),flush=True)
    report['samples']=results
    report['sameProcessReused']=True
finally:
    engine.close()
report['closed']=engine.status()['phase']=='off'
(ROOT/'qa'/'cosy-live.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False,indent=2))
