"""Persistent private stdio engine; stopping playback keeps weights resident."""
import json
from pathlib import Path
import queue
import subprocess
import threading
import uuid

ROOT = Path(__file__).resolve().parents[1]
VOICE = 'CosyVoice · 官方参考女声'


class CosyEngine:
    def __init__(self):
        self.lock = threading.RLock()
        self.process = None
        self.pending = {}
        self.phase, self.error, self.device = 'off', None, None

    def status(self):
        with self.lock:
            return dict(engine='cosyvoice3', phase=self.phase, error=self.error, device=self.device)

    def start(self):
        with self.lock:
            if self.process is not None or self.phase == 'error':
                return
            python = ROOT/'.cosyvenv'/'Scripts'/'python.exe'
            if not python.exists():
                self.phase, self.error = 'error', 'cosy-runtime-missing'
                return
            self.phase, self.error = 'loading', None
            try:
                process = subprocess.Popen([str(python), '-I', '-X', 'utf8', str(ROOT/'native'/'cosy_server.py')],
                    cwd=ROOT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                    text=True, encoding='utf-8', creationflags=subprocess.CREATE_NO_WINDOW)
                self.process = process
                threading.Thread(target=self._read, args=(process,), daemon=True).start()
            except OSError:
                self.phase, self.error = 'error', 'cosy-start-failed'

    def _read(self, process):
        try:
            for line in process.stdout:
                try:
                    packet = json.loads(line)
                    if not isinstance(packet, dict) or 'kind' not in packet:
                        continue
                except ValueError:
                    # Native inference libraries may write non-protocol startup messages.
                    continue
                with self.lock:
                    if self.process is not process:
                        return
                    if packet['kind'] == 'ready':
                        self.phase, self.error, self.device = 'ready', None, packet['device']
                    elif packet['kind'] == 'fatal':
                        self.phase, self.error = 'error', 'cosy-load-failed'
                    else:
                        target = self.pending.get(packet.get('id'))
                        if target:
                            target.put(packet)
        except (OSError, ValueError, KeyError):
            pass
        finally:
            with self.lock:
                if self.process is process:
                    self.process = None
                    self.phase, self.error = 'error', self.error or 'cosy-process-exited'
                    for target in self.pending.values():
                        target.put(dict(kind='error', error=self.error))
            process.wait()

    def _send(self, packet):
        with self.lock:
            if not self.process or self.process.poll() is not None:
                raise RuntimeError('cosy-not-ready')
            self.process.stdin.write(json.dumps(packet, ensure_ascii=False)+'\n')
            self.process.stdin.flush()

    def stream(self, text, config):
        request_id, target = str(uuid.uuid4()), queue.Queue()
        with self.lock:
            if self.phase != 'ready':
                raise RuntimeError('cosy-not-ready')
            self.pending[request_id] = target
            try:
                self._send(dict(operation='speak', id=request_id, text=text,
                    voice=config.get('voice') or VOICE, rate=config['rate'], volume=config['volume']))
            except Exception:
                self.pending.pop(request_id, None)
                raise
        def packets():
            try:
                while True:
                    try:
                        packet = target.get(timeout=1)
                    except queue.Empty:
                        if self.status()['phase'] != 'ready':
                            raise RuntimeError('cosy-not-ready')
                        continue
                    if packet['kind'] == 'done':
                        return
                    if packet['kind'] == 'error':
                        raise RuntimeError('cosy-synthesis-failed')
                    yield packet
            finally:
                with self.lock:
                    self.pending.pop(request_id, None)
        return packets()

    def cancel(self):
        with self.lock:
            if self.process and self.phase == 'ready':
                for request_id in list(self.pending):
                    try:
                        self._send(dict(operation='cancel', id=request_id))
                    except OSError:
                        pass

    def close(self):
        with self.lock:
            process, self.process = self.process, None
            self.phase, self.error, self.device = 'off', None, None
            for target in self.pending.values():
                target.put(dict(kind='error'))
        if process:
            try:
                process.stdin.close()
                process.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                process.kill()
                process.wait(timeout=5)
