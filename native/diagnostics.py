"""Local bounded diagnostics. Never record prompts, audio, tokens or exception text."""
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import sys
import threading
import time
import traceback


class QuietHandler(RotatingFileHandler):
    def handleError(self, record):
        pass  # A logging failure must never stop the animation or audio loop.


class Diagnostics:
    def __init__(self, name, directory=None, max_bytes=2*1024*1024, backups=3):
        self.path = (Path(directory) if directory else Path.home()/'.dsh-companion/logs')/(name+'.jsonl')
        self.lock = threading.RLock()
        self.seen = {}
        self.pulses = {}
        self.closed = threading.Event()
        self.logger = logging.Logger('companion.'+name)
        self.logger.propagate = False
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handler = QuietHandler(self.path, maxBytes=max_bytes, backupCount=backups, encoding='utf-8')
            handler.setFormatter(logging.Formatter('%(message)s'))
            self.logger.addHandler(handler)
        except OSError:
            self.logger.addHandler(logging.NullHandler())

    def event(self, event, *, exc=None, interval=0, **fields):
        try:
            now = time.monotonic()
            with self.lock:
                key = (event, fields.get('loop'), type(exc).__name__ if exc else None)
                if interval and now-self.seen.get(key, -float('inf')) < interval:
                    return
                self.seen[key] = now
            row = dict(time=time.strftime('%Y-%m-%dT%H:%M:%S%z'), monotonic=round(now, 3),
                       pid=os.getpid(), thread=threading.current_thread().name, event=event, **fields)
            if exc is not None:
                row['errorType'] = type(exc).__name__
                for key in ('errno', 'winerror', 'code'):
                    if isinstance(getattr(exc, key, None), int):row[key] = getattr(exc, key)
                # Frame locations suffice for diagnosis; messages and locals may contain user text.
                row['stack'] = [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                                for f in traceback.extract_tb(exc.__traceback__)]
            self.logger.info(json.dumps(row, ensure_ascii=False))
        except Exception:
            pass

    def pulse(self, loop, **state):
        now = time.monotonic()
        with self.lock:
            old = self.pulses.get(loop)
            self.pulses[loop] = dict(at=now, thread=threading.get_ident(), state=state, stalled=False,
                                     reported=old['reported'] if old else now)
            if old and old['stalled']:
                self.event('loop.recovered', loop=loop, delaySeconds=round(now-old['at'], 2))
            if not old or old['state'] != state:
                self.event('state.changed', loop=loop, **state)
            elif now-old['reported'] >= 60:
                self.event('heartbeat', loop=loop, **state)
                self.pulses[loop]['reported'] = now

    def check_stalls(self, timeout=10):
        with self.lock:
            for loop, pulse in self.pulses.items():
                elapsed = time.monotonic()-pulse['at']
                if elapsed < timeout or pulse['stalled']:
                    continue
                pulse['stalled'] = True
                frame = sys._current_frames().get(pulse['thread'])
                stack = [dict(file=Path(f.filename).name, line=f.lineno, function=f.name)
                         for f in traceback.extract_stack(frame)] if frame else []
                self.event('loop.stalled', loop=loop, delaySeconds=round(elapsed, 2),
                           state=pulse['state'], stack=stack)

    def start(self):
        def watch():
            while not self.closed.wait(2):
                self.check_stalls()
        threading.Thread(target=watch, name='diagnostics-watchdog', daemon=True).start()

    def install_hooks(self):
        previous = sys.excepthook
        def uncaught(kind, value, tb):
            self.event('process.exception', exc=value)
            previous(kind, value, tb)
        sys.excepthook = uncaught
        prior_thread = threading.excepthook
        def thread_error(args):
            self.event('thread.exception', exc=args.exc_value)
            prior_thread(args)
        threading.excepthook = thread_error

    def close(self):
        self.closed.set()
        for handler in self.logger.handlers:
            handler.close()


diagnostics = Diagnostics('voice')
