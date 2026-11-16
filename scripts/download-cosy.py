"""Download official inference assets with size and SHA256 verification."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import quote
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
MODEL = 'FunAudioLLM/Fun-CosyVoice3-0.5B-2512'
TARGET = ROOT / 'models' / 'Fun-CosyVoice3-0.5B'


def download(item):
    path = TARGET / item['Path']
    path.parent.mkdir(parents=True, exist_ok=True)
    def valid(candidate):
        if not candidate.exists() or candidate.stat().st_size != item['Size']:
            return False
        with candidate.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest() == item['Sha256']
    if valid(path):
        print('Verified:', item['Path'], flush=True)
        return
    partial = path.with_name(path.name+'.partial')
    url = item.get('URL') or f'https://modelscope.cn/api/v1/models/{MODEL}/repo?Revision={item["Revision"]}&FilePath={quote(item["Path"])}'
    if item['Size'] > 100*1024*1024:
        chunk_size = item.get('ChunkSize',16*1024*1024)
        parts = path.with_name(path.name+f'.parts-{chunk_size}' if 'ChunkSize' in item else path.name+'.parts')
        parts.mkdir(exist_ok=True)
        def fetch_part(start):
            end = min(item['Size'], start+chunk_size)-1
            part = parts/str(start)
            if part.exists() and part.stat().st_size == end-start+1:
                return part
            for attempt in range(10):
                try:
                    # Distinct query keys prevent intermediary caches mixing ranges.
                    with urlopen(Request(url+('?' if '?' not in url else '&')+f'part={start}&length={end-start+1}', headers={'Range':f'bytes={start}-{end}'}),timeout=60) as response:
                        if response.status != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{item["Size"]}':
                            raise ValueError('invalid-range')
                        with part.open('wb') as output:
                            while chunk := response.read(1024*1024):
                                output.write(chunk)
                    if part.stat().st_size != end-start+1:
                        raise ValueError('incomplete-range')
                    return part
                except Exception:
                    if attempt == 9:
                        raise
                    time.sleep(2+attempt)
        with ThreadPoolExecutor(max_workers=item.get('Workers',4)) as pool:
            ordered = list(pool.map(fetch_part, range(0,item['Size'],chunk_size)))
        with partial.open('wb') as output:
            for part in ordered:
                with part.open('rb') as source:
                    while chunk := source.read(1024*1024):
                        output.write(chunk)
        if not valid(partial):
            raise ValueError('asset-checksum-mismatch')
        partial.replace(path)
        for part in ordered:
            part.unlink()
        parts.rmdir()
        print('Downloaded:',item['Path'],item['Size'],flush=True)
        return
    for attempt in range(5):
        try:
            offset = partial.stat().st_size if partial.exists() else 0
            with urlopen(Request(url, headers={'Range': f'bytes={offset}-'} if offset else {}), timeout=60) as response:
                append = offset > 0 and response.status == 206
                with partial.open('ab' if append else 'wb') as stream:
                    while chunk := response.read(1024*1024):
                        stream.write(chunk)
            if not valid(partial):
                partial.unlink(missing_ok=True)
                raise ValueError('asset-checksum-mismatch')
            partial.replace(path)
            print('Downloaded:', item['Path'], item['Size'], flush=True)
            return
        except Exception:
            if attempt == 4:
                raise
            time.sleep(2+attempt)


def main():
    with urlopen(f'https://modelscope.cn/api/v1/models/{MODEL}/repo/files?Revision=master&Recursive=true', timeout=30) as response:
        manifest = json.load(response)
    selected = [f for f in manifest['Data']['Files'] if f['Type']=='blob' and
                (f['Path'].startswith('CosyVoice-BlankEN/') or f['Path'] in
                 ('README.md','configuration.json','cosyvoice3.yaml','campplus.onnx','speech_tokenizer_v3.onnx','flow.pt','hift.pt','llm.pt'))]
    TARGET.mkdir(parents=True, exist_ok=True)
    (TARGET/'source-manifest.json').write_text(json.dumps(selected, indent=2), encoding='utf-8')
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(download, selected))
    print('Official inference assets verified.', flush=True)


if __name__=='__main__':
    main()
