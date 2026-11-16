"""Verify cancellation and persistent model reuse without loading GPU weights."""
import base64
from pathlib import Path
import queue
import sys
import threading
import time
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'native'))
from speaker import Speaker


class Engine:
    def __init__(self):
        self.phase='ready'
        self.requests=queue.Queue()
        self.targets=[]
        self.starts=0
    def status(self):return dict(phase=self.phase,error=None)
    def start(self):self.starts+=1
    def stream(self,text,config):
        target=queue.Queue();self.targets.append(target);self.requests.put((text,target))
        def packets():
            while (packet:=target.get()) is not None:yield packet
        return packets()
    def cancel(self):
        for target in self.targets:target.put(None)
        self.targets=[]
    def close(self):self.phase='off';self.cancel()


class Output:
    writes=[]
    def __init__(self,**kwargs):pass
    def start(self):pass
    def stop(self):pass
    def abort(self):pass
    def close(self):pass
    def write(self,pcm):self.writes.append(pcm)


class SpeakerTests(unittest.TestCase):
    def test_cancelled_generation_never_plays_or_completes_and_next_reply_reuses_engine(self):
        with patch('speaker.CosyEngine',Engine),patch('speaker.sd.RawOutputStream',Output):
            Output.writes=[]
            speaker=Speaker();completed=[]
            try:
                config=dict(voice='',rate=0,volume=80)
                engine=speaker.engine
                speaker.speak('旧回答',config,lambda:completed.append('old'))
                _,old=engine.requests.get(timeout=2)
                speaker.stop()
                old.put(dict(pcmBase64=base64.b64encode(b'old!').decode(),sampleRate=24000));old.put(None)
                speaker.speak('新回答',config,lambda:completed.append('new'))
                _,new=engine.requests.get(timeout=2)
                new.put(dict(pcmBase64=base64.b64encode(b'new!').decode(),sampleRate=24000));new.put(None)
                deadline=time.monotonic()+2
                while speaker.playing and time.monotonic()<deadline:time.sleep(.01)
                self.assertEqual(completed,['new'])
                self.assertEqual(Output.writes,[b'new!'])
                self.assertIs(speaker.engine,engine)
                self.assertEqual(engine.phase,'ready')
                speaker.configure(False)
                self.assertEqual(engine.phase,'off')
            finally:speaker.close()


if __name__=='__main__':unittest.main()
