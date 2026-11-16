"""Cancellable local neural speech; models survive ordinary playback stops."""
import base64
import queue
import threading
from diagnostics import diagnostics
import time
import sounddevice as sd
from cosy_engine import CosyEngine, VOICE


class Speaker:
    def __init__(self):
        self.queue = queue.Queue()
        self.lock = threading.RLock()
        self.generation = 0
        self.playing = False
        self.text = ''
        self.closed = False
        self.last_error = None
        self.completed_at = 0
        self.engine = CosyEngine()
        threading.Thread(target=self._run, daemon=True).start()

    def voices(self):
        return [VOICE]

    def status(self):
        return self.engine.status()

    def configure(self, active):
        if active:
            self.engine.start()
        elif self.engine.status()['phase'] != 'off':
            self.stop()
            self.engine.close()

    def stop(self):
        with self.lock:
            self.generation += 1
            self.playing = False
            self.text = ''
            self.engine.cancel()

    def speak(self, text, config, complete=None):
        self.stop()
        self.last_error = None
        with self.lock:
            generation = self.generation
        self.queue.put((generation, text, dict(config), complete))

    def _run(self):
        while not self.closed:
            item = self.queue.get()
            if item is None:
                return
            generation, text, config, complete = item
            output = None
            try:
                with self.lock:
                    if generation != self.generation:
                        continue
                    self.text, self.playing = text, True
                    stream = self.engine.stream(text, config)
                for packet in stream:
                    if generation != self.generation:
                        continue
                    pcm = base64.b64decode(packet['pcmBase64'])
                    sample_rate = packet['sampleRate']
                    if output is None:
                        output = sd.RawOutputStream(samplerate=sample_rate, channels=1, dtype='int16', blocksize=0)
                        output.start()
                    block_bytes = max(2, sample_rate//50*2)
                    for start in range(0, len(pcm), block_bytes):
                        if generation != self.generation:
                            output.abort()
                            break
                        output.write(pcm[start:start+block_bytes])
                if generation == self.generation:
                    if output is not None:
                        output.stop()
                    if complete:
                        complete()
            except Exception as error:
                diagnostics.event('synthesis.failed',exc=error,interval=30)
                if generation == self.generation:
                    self.last_error = 'cosy-synthesis-failed'
                    if complete:
                        complete()
            finally:
                if output is not None:
                    output.close()
                with self.lock:
                    if generation == self.generation:
                        self.playing = False
                        self.completed_at = time.monotonic()

    def close(self):
        self.closed = True
        self.stop()
        self.engine.close()
        self.queue.put(None)
