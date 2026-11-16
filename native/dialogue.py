"""Conversation state independent of audio hardware and network adapters."""
import re
import time
from pypinyin import lazy_pinyin


def normalize(text):
    return ''.join(re.findall(r'[\w\u3400-\u9fff]', text.lower()))


def syllables(text):
    return tuple(lazy_pinyin(normalize(text)))


class Dialogue:
    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.wake_words = ['嗨大肥鱼', '大肥鱼']
        self.followup = 15
        self.deadline = 0
        self.generation = 0
        self.busy = False
        self.spoken = ''
        self.echoes = []

    def configure(self, config):
        self.wake_words = config['wakeWords']
        self.followup = config['followupSeconds']

    def reset(self):
        self.generation += 1
        self.deadline = 0
        self.busy = False
        self.spoken = ''
        self.echoes = []

    def remember_spoken(self, text):
        self.spoken = text
        self.echoes = [(at, old) for at, old in self.echoes if self.clock()-at < 10][-2:]
        self.echoes.append((self.clock(), text))

    def listen(self):
        self.deadline = self.clock() + self.followup

    def phase(self):
        return 'thinking' if self.busy else 'listening' if self.clock() < self.deadline else 'standby'

    def accept(self, text, playing=False):
        text = text.strip()
        clean = normalize(text)
        if not clean:
            return {'kind': 'ignore'}
        # Check echo before wake matching: a spoken answer may itself begin with the pet's name.
        candidates = [self.spoken] if playing and self.spoken else []
        candidates += [old for at, old in self.echoes if self.clock()-at < 3]
        for old in candidates:
            spoken = normalize(old)
            if clean in spoken or (len(clean) >= 4 and spoken in clean):
                return {'kind': 'echo'}
        # Match a prefix only. Homophones are allowed without fuzzy deletion of syllables.
        wake = None
        for phrase in self.wake_words:
            count = len(normalize(phrase))
            if syllables(clean[:count]) == syllables(phrase):
                wake = clean[count:]
                break
        active = self.busy or self.clock() < self.deadline
        if wake is None and not active:
            return {'kind': 'ignore'}
        content = wake if wake is not None else text
        if normalize(content) in ('停止', '停下', '别说了', '停止播放', '取消', '取消任务'):
            self.generation += 1
            self.busy = False
            self.listen()
            return {'kind': 'cancel', 'generation': self.generation}
        if normalize(content) in ('再见', '结束对话', '不用了', '休息吧'):
            self.reset()
            return {'kind': 'sleep', 'generation': self.generation}
        self.generation += 1
        self.busy = bool(normalize(content))
        self.listen()
        return {'kind': 'command' if self.busy else 'wake', 'text': content,
                'generation': self.generation}

    def complete(self, generation):
        if generation != self.generation:
            return False
        self.busy = False
        self.listen()
        return True
