import sys
from pathlib import Path
import unittest
from array import array
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'native'))
from dialogue import Dialogue
from audio import Segmenter, wav_bytes


class DialogueTest(unittest.TestCase):
    def setUp(self):
        self.time = 10
        self.dialogue = Dialogue(lambda: self.time)

    def test_background_never_runs_commands(self):
        self.assertEqual(self.dialogue.accept('打开浏览器')['kind'], 'ignore')
        self.assertEqual(self.dialogue.accept('新闻里提到嗨大肥鱼')['kind'], 'ignore')

    def test_wake_inline_homophone_followup_expiry(self):
        self.assertEqual(self.dialogue.accept('嗨，大肥鱼！')['kind'], 'wake')
        event = self.dialogue.accept('嗨大飞鱼，跑到右边去')
        self.assertEqual(event['kind'], 'command')
        self.assertEqual(event['text'], '跑到右边去')
        self.dialogue.complete(event['generation'])
        self.assertEqual(self.dialogue.accept('然后停下')['kind'], 'command')
        self.dialogue.complete(self.dialogue.generation)
        self.time += 16
        self.assertEqual(self.dialogue.accept('打开浏览器')['kind'], 'ignore')

    def test_stale_results_cancellation_and_echo(self):
        self.dialogue.accept('嗨大肥鱼')
        event = self.dialogue.accept('讲个故事')
        self.dialogue.spoken = '很久以前，有一只鲸鱼。'
        self.assertEqual(self.dialogue.accept('有一只鲸鱼', playing=True)['kind'], 'echo')
        self.dialogue.remember_spoken('大肥鱼正在看书。')
        self.assertEqual(self.dialogue.accept('大肥鱼正在看书', playing=True)['kind'], 'echo')
        self.assertEqual(self.dialogue.accept('停止')['kind'], 'cancel')
        self.assertFalse(self.dialogue.complete(event['generation']))
        self.assertEqual(self.dialogue.accept('休息吧')['kind'], 'sleep')

    def test_segmenter_discards_click_and_joins_long_utterance(self):
        quiet = b'\0'*960
        loud = array('h', [4000, -4000]*240).tobytes()
        segmenter = Segmenter(300)
        segmenter.feed(loud)
        self.assertFalse(any(segmenter.feed(quiet) for _ in range(15)))
        segments = []
        for _ in range(420):
            segment = segmenter.feed(loud)
            if segment:
                segments.append(segment)
        for _ in range(15):
            segment = segmenter.feed(quiet)
            if segment:
                segments.append(segment)
        self.assertEqual([item[1] for item in segments], [True, False])
        self.assertEqual(wav_bytes(quiet)[:4], b'RIFF')


if __name__ == '__main__':
    unittest.main()
