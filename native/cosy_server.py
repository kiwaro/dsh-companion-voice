"""Private synthesis server: no network listener and no persisted user text."""
import base64
import contextlib
import json
import os
from pathlib import Path
import queue
import sys
import threading

ROOT = Path(__file__).resolve().parents[1]
VOICE = 'CosyVoice · 官方参考女声'
protocol, output_lock = sys.stdout, threading.Lock()


def emit(packet):
    with output_lock:
        protocol.write(json.dumps(packet, ensure_ascii=False)+'\n')
        protocol.flush()


def main():
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    sys.path[:0] = [str(ROOT/'runtime'/'CosyVoice'), str(ROOT/'runtime'/'CosyVoice'/'third_party'/'Matcha-TTS')]
    # Upstream prints synthesized text. Discard it rather than writing a log.
    with open(os.devnull, 'w', encoding='utf-8') as quiet, contextlib.redirect_stdout(quiet), contextlib.redirect_stderr(quiet):
        try:
            import logging
            logging.disable(logging.CRITICAL)
            import torch
            from cosyvoice.cli.cosyvoice import AutoModel
            torch.set_num_threads(4)
            model = AutoModel(model_dir=str(ROOT/'models'/'Fun-CosyVoice3-0.5B'), fp16=torch.cuda.is_available())
            model.add_zero_shot_spk('You are a helpful assistant.<|endofprompt|>希望你以后能够做的比我还好呦。',
                str(ROOT/'runtime'/'CosyVoice'/'asset'/'zero_shot_prompt.wav'), VOICE)
            # Warm up once and keep only the fixed wake acknowledgement in RAM.
            # A fresh wake must not wait for neural generation on every turn.
            with torch.inference_mode():
                wake_audio = [chunk['tts_speech'].float().cpu() for chunk in model.inference_zero_shot(
                    '我在。', '', '', zero_shot_spk_id=VOICE, stream=False, text_frontend=False)]
        except Exception:
            emit(dict(kind='fatal', error='cosy-load-failed'))
            return
        tasks, active, guard = queue.Queue(), {}, threading.Lock()

        def synthesize():
            while True:
                request, cancelled = tasks.get()
                request_id = request['id']
                try:
                    if cancelled.is_set():
                        continue
                    if request.get('voice', VOICE) != VOICE:
                        raise ValueError('unknown-voice')
                    speed = 2 ** (max(-10, min(10, request.get('rate', 0)))/20)
                    volume = max(0, min(100, request.get('volume', 80)))/100
                    with torch.inference_mode():
                        chunks = ({'tts_speech':audio} for audio in wake_audio) if request['text']=='我在。' and speed==1.0 else model.inference_zero_shot(
                            request['text'], '', '', zero_shot_spk_id=VOICE, stream=(speed==1.0), speed=speed, text_frontend=False)
                        for chunk in chunks:
                            if cancelled.is_set():
                                # Drain upstream to finish its generation thread before reuse.
                                continue
                            pcm = (chunk['tts_speech'].float().clamp(-1, 1)*volume*32767).to(torch.int16).cpu().numpy().tobytes()
                            emit(dict(kind='audio', id=request_id, sampleRate=model.sample_rate,
                                pcmBase64=base64.b64encode(pcm).decode('ascii')))
                except Exception:
                    emit(dict(kind='error', id=request_id, error='cosy-synthesis-failed'))
                finally:
                    emit(dict(kind='done', id=request_id))
                    with guard:
                        active.pop(request_id, None)

        threading.Thread(target=synthesize, daemon=True).start()
        emit(dict(kind='ready', device=torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'CPU', sampleRate=model.sample_rate))
        for line in sys.stdin:
            try:
                request = json.loads(line)
                request_id = request.get('id')
                if request.get('operation') == 'speak':
                    flag = threading.Event()
                    with guard:
                        active[request_id] = flag
                    tasks.put((request, flag))
                elif request.get('operation') == 'cancel':
                    with guard:
                        flag = active.get(request_id)
                        if flag:
                            flag.set()
            except (ValueError, TypeError):
                continue
        with guard:
            for flag in active.values():
                flag.set()


if __name__=='__main__':
    main()
