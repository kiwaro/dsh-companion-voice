"""Headless pet voice worker. No conversation input panel or browser lifetime."""
import argparse
import base64
import queue
import threading
import time
import uuid
from diagnostics import diagnostics
from audio import Microphone, Segmenter, devices, wav_bytes
from dialogue import Dialogue
from speaker import Speaker
from transport import Transport


class Worker:
    def __init__(self, transport):
        self.transport = transport
        self.dialogue = Dialogue()
        self.speaker = Speaker()
        self.lock = threading.RLock()
        self.config = None
        self.revision = None
        self.ready = False
        self.running = True
        self.phase = 'off'
        self.last_error = None
        self.microphone = None
        self.device = None
        self.capture_epoch = 0
        self.binding = None
        self.audio_queue = queue.Queue(maxsize=4)
        self.input_devices = devices()
        try:
            self.voices = self.speaker.voices()
        except Exception as error:
            diagnostics.event('voices.failed',exc=error)
            self.voices = []
            self.last_error = 'local-voices-unavailable'

    def heartbeat(self):
        diagnostics.pulse('heartbeat',phase=self.phase)
        while self.running:
            try:
                if not self.transport.valid():
                    diagnostics.event('connection.invalidated')
                    self.running = False
                    break
                result = self.transport.post('/heartbeat', dict(phase=self.phase, devices=self.input_devices,
                    voices=self.voices, microphone=self.microphone is not None,
                    lastError=self.last_error or self.speaker.last_error or self.speaker.status()['error'], synthesis=self.speaker.status()))
                config = result['settings']
                preparation = (result.get('recognizer') or {}).get('preparation', {}).get('phase')
                available = config['enabled'] and bool((result.get('pet') or {}).get('enabled')) and preparation in ('ready', 'standby')
                self.speaker.configure(available)
                synthesis = self.speaker.status()
                ready = available and synthesis['phase'] == 'ready'
                pet = result.get('pet') or {}
                binding = (pet.get('hostGeneration'), pet.get('ownerEpoch'))
                with self.lock:
                    # Any configuration or pet availability change invalidates buffered speech.
                    if self.revision != result['revision'] or self.ready != ready or self.binding != binding:
                        self.dialogue.reset()
                        self.capture_epoch += 1
                        self.speaker.stop()
                        try:
                            self.transport.post('/cancel', {})
                        except Exception:
                            pass
                    self.config = {**config, 'voice': config['voice'] if config['voice'] in self.voices else ''}
                    self.revision = result['revision']
                    self.ready = ready
                    self.binding = binding
                    self.dialogue.configure(config)
                if config['enabled'] and not ready:
                    self.phase = 'preparing' if result.get('recognizer') else 'recognizer-unavailable'
                    if not (result.get('pet') or {}).get('enabled'):
                        self.phase = 'pet-offline'
                    elif preparation in ('failed', 'cancelled'):
                        self.phase = 'error'
                        self.last_error = 'recognizer-prepare-failed'
                    elif available:
                        self.phase = 'voice-error' if synthesis['phase'] == 'error' else 'voice-preparing'
                preview = result.get('preview')
                if preview and ready:
                    self.dialogue.remember_spoken('我在呀。今天想聊些什么？你也可以叫我帮忙。')
                    self.speaker.speak('我在呀。今天想聊些什么？你也可以叫我帮忙。', preview['settings'])
                diagnostics.pulse('heartbeat',phase=self.phase,ready=ready,microphone=self.microphone is not None,
                                  synthesis=synthesis['phase'],error=self.last_error or self.speaker.last_error or synthesis['error'],revision=self.revision)
            except Exception as error:
                diagnostics.event('connection.failed',exc=error,interval=30)
                diagnostics.pulse('heartbeat',connected=False)
                with self.lock:
                    self.ready = False
                    self.capture_epoch += 1
                    self.dialogue.reset()
                self.speaker.stop()
                self.last_error = 'host-disconnected'
            time.sleep(1)

    def cancel(self):
        self.speaker.stop()
        try:
            return self.transport.post('/cancel', {}).get('status') == 'cancelled'
        except Exception as error:
            diagnostics.event('command.cancel-failed',exc=error,interval=30)
            self.last_error = 'cancel-failed'
            return False

    def utterances(self):
        partial = ''
        partial_epoch = None
        while self.running:
            try:
                epoch, pcm, continuing = self.audio_queue.get(timeout=.2)
            except queue.Empty:
                continue
            if epoch != partial_epoch:
                partial, partial_epoch = '', epoch
            with self.lock:
                if not self.ready or epoch != self.capture_epoch:
                    partial = ''
                    continue
            try:
                result = self.transport.post('/asr', {'audioBase64': base64.b64encode(wav_bytes(pcm)).decode()}, timeout=180)
                with self.lock:
                    if not self.ready or epoch != self.capture_epoch:
                        partial = ''
                        continue
                partial += result.get('text', '')
                if continuing:
                    continue
                text, partial = partial, ''
                self.heard(text)
            except Exception as error:
                diagnostics.event('recognition.failed',exc=error,interval=30)
                partial = ''
                self.last_error = 'recognition-failed'

    def heard(self, text):
        with self.lock:
            if not self.ready:
                return
            self.dialogue.spoken = self.speaker.text
            playing = self.speaker.playing or time.monotonic()-self.speaker.completed_at < 1
            event = self.dialogue.accept(text, playing)
            if event['kind'] in ('ignore', 'echo'):
                return
            self.last_error = None
        cancelled = self.cancel()
        if event['kind'] in ('cancel', 'sleep'):
            return
        if event['kind'] == 'wake':
            self.transport.post('/announce', {})
            self.dialogue.remember_spoken('我在。')
            self.speaker.speak('我在。', self.config, lambda: self.finish(event['generation']))
        else:
            if not cancelled:
                self.last_error = 'previous-command-cancelling'
                self.finish(event['generation'])
                return
            threading.Thread(target=self.command, args=(event,), daemon=True).start()

    def command(self, event):
        with self.lock:
            if event['generation'] != self.dialogue.generation or not self.ready:
                return
        started=time.monotonic()
        request_id='voice:'+str(uuid.uuid4())
        diagnostics.event('command.started',requestId=request_id)
        try:
            result = self.transport.post('/command', dict(requestId=request_id, text=event['text']), timeout=None)
            diagnostics.event('command.finished',requestId=request_id,status=result.get('status'),elapsedSeconds=round(time.monotonic()-started,2))
            with self.lock:
                if event['generation'] != self.dialogue.generation or not self.ready:
                    return
                text = result.get('text') or result.get('message')
                if result.get('status') == 'cancelled':
                    self.finish(event['generation'])
                    return
                if not text:
                    text = '这次没有完成，请再说一遍。'
                self.dialogue.remember_spoken(text)
                self.speaker.speak(text, self.config, lambda: self.finish(event['generation']))
        except Exception as error:
            diagnostics.event('command.failed',exc=error,requestId=request_id,elapsedSeconds=round(time.monotonic()-started,2))
            with self.lock:
                if event['generation'] == self.dialogue.generation:
                    self.last_error = 'command-failed'
                    self.finish(event['generation'])

    def finish(self, generation):
        with self.lock:
            self.dialogue.complete(generation)

    def run(self):
        diagnostics.event('worker.start')
        threading.Thread(target=self.heartbeat, daemon=True).start()
        threading.Thread(target=self.utterances, daemon=True).start()
        segmenter = Segmenter()
        previous_epoch = -1
        next_attempt = 0
        try:
            while self.running:
                diagnostics.pulse('capture',phase=self.phase,error=self.last_error)
                with self.lock:
                    ready, config, epoch = self.ready, self.config, self.capture_epoch
                device = config['device'] if config else None
                if self.microphone and (not ready or device != self.device or previous_epoch != epoch):
                    self.microphone.close()
                    self.microphone = None
                if not ready:
                    if not config or not config['enabled']:
                        self.phase = 'off'
                    time.sleep(.1)
                    continue
                if not self.microphone:
                    if time.monotonic() < next_attempt:
                        time.sleep(.1)
                        continue
                    try:
                        self.microphone = Microphone(device)
                        self.device = device
                        previous_epoch = epoch
                        segmenter = Segmenter(config['silenceMs'])
                        self.last_error = None
                    except Exception as error:
                        diagnostics.event('microphone.failed',exc=error,interval=30)
                        self.last_error = 'microphone-unavailable'
                        self.phase = 'error'
                        next_attempt = time.monotonic()+5
                        continue
                self.phase = 'speaking' if self.speaker.playing else self.dialogue.phase()
                try:
                    frame = self.microphone.frames.get(timeout=.15)
                except queue.Empty:
                    continue
                if self.microphone.overflow:
                    diagnostics.event('audio.overflow',interval=30)
                    # Never execute a truncated recording after losing frames.
                    self.last_error = 'audio-overflow'
                    self.microphone.overflow = False
                    segmenter = Segmenter(config['silenceMs'])
                    continue
                segment = segmenter.feed(frame)
                if segment:
                    try:
                        self.audio_queue.put_nowait((epoch, *segment))
                    except queue.Full:
                        diagnostics.event('recognition.backlog',interval=30)
                        self.last_error = 'recognition-backlog'
                        with self.lock:
                            self.capture_epoch += 1
        finally:
            diagnostics.event('worker.stop')
            self.running = False
            if self.microphone:
                self.microphone.close()
            self.speaker.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--connection', required=True)
    arguments = parser.parse_args()
    diagnostics.install_hooks()
    diagnostics.start()
    diagnostics.event('process.start')
    try:Worker(Transport(arguments.connection)).run()
    finally:diagnostics.close()
