"""Explicit local smoke: synthetic speech -> official ASR -> real pet action.

No raw microphone recording is stored. This does not replace a human voice test.
"""
import base64
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, ProxyHandler, Request
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'native'))
from transport import Transport
from audio import wav_bytes
from worker import Worker

ROOT = Path(__file__).resolve().parents[1]
PROFILE = Path.home()/'.dsh/profiles/desktop'
transport = Transport(PROFILE/'data/dsh-companion-voice/connection.json')
pet_connection = json.loads(next((Path.home()/'.dsh-companion/connections').glob('*.json')).read_text())
origin = pet_connection['origin']
opener=build_opener(ProxyHandler({}))


def state():
    with opener.open(origin+'/api/dsh-companion-voice/status', timeout=10) as response:
        return json.load(response)


def synthesize(text):
    script = '''[Console]::InputEncoding=[Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$s=[System.Speech.Synthesis.SpeechSynthesizer]::new()
$s.SelectVoice('Microsoft Huihui Desktop')
$m=[IO.MemoryStream]::new()
$f=[System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(16000,[System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,[System.Speech.AudioFormat.AudioChannel]::Mono)
$s.SetOutputToAudioStream($m,$f)
$r=[Console]::ReadLine() | ConvertFrom-Json
$s.Speak([string]$r.text)
[Console]::WriteLine([Convert]::ToBase64String($m.ToArray()))
$s.Dispose();$m.Dispose()
'''
    encoded = base64.b64encode(script.encode('utf-16le')).decode()
    process = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-EncodedCommand', encoded],
        input=json.dumps({'text':text}, ensure_ascii=False)+'\n', capture_output=True, text=True, encoding='utf-8',
        timeout=30, creationflags=subprocess.CREATE_NO_WINDOW, check=True)
    return wav_bytes(b'\0'*9600+base64.b64decode(process.stdout.strip())+b'\0'*9600)


def transcribe(text):
    started = time.monotonic()
    result = transport.post('/asr', {'audioBase64':base64.b64encode(synthesize(text)).decode()}, timeout=180)
    return result['text'], round(time.monotonic()-started, 2)


def wait_until(predicate, seconds=60):
    deadline = time.monotonic()+seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.1)
    raise RuntimeError('verification-timeout')


report = {'verifiedAt':time.strftime('%Y-%m-%d %H:%M:%S'), 'input':'synthetic-local-Chinese-speech', 'humanVoiceVerified':False}
original_post=transport.post
def observed_post(route, data, timeout=15):
    result=original_post(route,data,timeout)
    if route=='/command':
        report['commandResult']=result
        print('COMMAND RESULT '+json.dumps(result,ensure_ascii=False),flush=True)
    return result
transport.post=observed_post
def runtime_state():
    path=Path(tempfile.gettempdir())/'dsh-companion-lanxi-desktop-runtime.json'
    for _ in range(30):
        try:
            return json.loads(path.read_text(encoding='utf-8'))
        except (OSError,ValueError):
            time.sleep(.03)
    raise RuntimeError('pet-runtime-unavailable')

worker = Worker(transport)
try:
    # Let the production worker finish startup before this test sends a command.
    # Its startup transition invalidates old turns, including an early QA turn.
    wait_until(lambda:state()['runtime']['phase']=='standby' and state()['runtime'].get('synthesis',{}).get('phase')=='ready',180)
    current = state()
    assert current['settings']['enabled'] and current['recognizer']['preparation']['phase'] in ('ready','standby')
    worker.config = {**current['settings'], 'voice': ''}
    worker.speaker.configure(True)
    wait_until(lambda:worker.speaker.status()['phase'] in ('ready','error'),180)
    assert worker.speaker.status()['phase']=='ready',worker.speaker.status()
    worker.ready = True
    worker.dialogue.configure(worker.config)
    wake, seconds = transcribe('嗨，大肥鱼。')
    event = worker.dialogue.accept(wake)
    assert event['kind'] == 'wake', (wake,event)
    # Reset so heard() exercises the same path as the real recognition thread.
    worker.dialogue.reset()
    worker.heard(wake)
    wait_until(lambda:not worker.speaker.playing and worker.speaker.queue.empty())
    assert not worker.speaker.last_error, worker.speaker.last_error
    report['wake'] = {'transcript':wake,'seconds':seconds,'acknowledged':True,'localPlayback':True}
    print('PASS official recognition and local wake playback',flush=True)
    command, seconds = transcribe('嗨，大肥鱼，向右边跑。')
    assert worker.dialogue.accept(command)['kind'] == 'command', command
    worker.dialogue.reset()
    before = runtime_state()
    worker.heard(command)
    seen = set()
    deadline=time.monotonic()+360
    while time.monotonic()<deadline:
        runtime=runtime_state()
        seen.add(runtime['action'])
        if worker.speaker.playing:
            report['spokenReply'] = worker.speaker.text
        if not worker.dialogue.busy:
            break
        time.sleep(.1)
    assert not worker.dialogue.busy, 'real-command-timeout'
    assert not worker.last_error, worker.last_error
    assert not worker.speaker.last_error, worker.speaker.last_error
    (ROOT/'qa/live-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert report['commandResult']['status']=='ready',report['commandResult']
    assert any('right' in action for action in seen), seen
    report['command']={'transcript':command,'seconds':seconds,'observedActions':sorted(seen),'samePetProcess':runtime['pid']==before['pid']}
    report['runtime']=state()['runtime']
    (ROOT/'qa/live-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2))
finally:
    worker.running=False
    worker.speaker.close()
