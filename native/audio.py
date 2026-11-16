"""PortAudio microphone and bounded-energy utterance segmentation."""
from array import array
from collections import deque
import io
import math
import queue
import wave
import sounddevice as sd

RATE = 16000
FRAME_MS = 30


def rms(pcm):
    values = array('h', pcm)
    return math.sqrt(sum(x*x for x in values)/max(1, len(values))) / 32768


def wav_bytes(pcm):
    target = io.BytesIO()
    with wave.open(target, 'wb') as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(RATE)
        stream.writeframes(pcm)
    return target.getvalue()


def devices():
    # Prefer WASAPI; do not display every duplicate MME/DirectSound endpoint.
    apis = sd.query_hostapis()
    all_devices = sd.query_devices()
    wasapi = {i for i, api in enumerate(apis) if 'WASAPI' in api['name']}
    return [{'id': i, 'name': d['name']} for i, d in enumerate(all_devices)
            if d['max_input_channels'] > 0 and (not wasapi or d['hostapi'] in wasapi)]


class Segmenter:
    def __init__(self, silence_ms=800):
        self.silence_ms = silence_ms
        self.pre = deque(maxlen=10)
        self.frames = []
        self.quiet = 0
        self.voiced = 0
        self.noise = .002
        self.continuation = False

    def feed(self, pcm):
        energy = rms(pcm)
        loud = energy > max(.009, self.noise * 2.5)
        if not self.frames and not loud:
            self.noise = .98*self.noise + .02*min(energy, .012)
        if loud and not self.frames:
            self.frames = list(self.pre)
            self.pre.clear()
        if self.frames or loud:
            self.frames.append(pcm)
            self.quiet = 0 if loud else self.quiet + FRAME_MS
            self.voiced += FRAME_MS if loud else 0
            # This bounds a single ASR chunk, not a user's command. The worker joins chunks.
            if self.quiet >= self.silence_ms or len(self.frames)*FRAME_MS >= 12000:
                pcm = b''.join(self.frames)
                continuing = self.quiet < self.silence_ms
                result = (pcm, continuing) if self.voiced >= 150 or self.continuation else None
                self.frames, self.quiet, self.voiced = [], 0, 0
                self.continuation = continuing
                if continuing:
                    self.frames = [b'']
                return result
        else:
            self.pre.append(pcm)
        return None


class Microphone:
    def __init__(self, device=None):
        if isinstance(device, str):
            matches = [d['id'] for d in devices() if d['name'] == device]
            if len(matches) != 1:
                raise ValueError('microphone-device-unavailable')
            device = matches[0]
        self.frames = queue.Queue(maxsize=400)
        self.overflow = False
        # A callback merely copies PCM; no recognition or network work runs here.
        def capture(data, count, timing, status):
            if status.input_overflow:
                self.overflow = True
            try:
                self.frames.put_nowait(bytes(data))
            except queue.Full:
                self.overflow = True
        info = sd.query_devices(device, 'input')
        api = sd.query_hostapis(info['hostapi'])['name']
        extra = sd.WasapiSettings(auto_convert=True) if 'WASAPI' in api else None
        self.stream = sd.RawInputStream(samplerate=RATE, channels=1, dtype='int16',
                                       blocksize=RATE*FRAME_MS//1000, device=device,
                                       extra_settings=extra, callback=capture)
        self.stream.start()

    def close(self):
        self.stream.stop()
        self.stream.close()
