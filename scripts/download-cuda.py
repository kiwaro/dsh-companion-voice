"""Official CUDA wheel, ranged and hash verified for slow full downloads."""
import html
import importlib.util
import re
from urllib.parse import unquote
from urllib.request import Request, urlopen
from pathlib import Path

spec=importlib.util.spec_from_file_location('cosy_download',Path(__file__).with_name('download-cosy.py'))
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
module.TARGET=module.ROOT/'runtime'/'wheels'
with urlopen('https://download.pytorch.org/whl/cu128/torch/',timeout=30) as response:
    listing=response.read().decode()
url=next(html.unescape(x) for x in re.findall(r'href="([^"]+)"',listing) if 'torch-2.8.0%2Bcu128-cp310-cp310-win_amd64.whl' in x)
url,digest=url.split('#sha256=')
# The official r2 endpoint may stall on high ranges on some proxy routes.
# Both official hosts serve the same wheel; retain the published SHA256.
url=url.replace('://download-r2.pytorch.org/','://download.pytorch.org/')
with urlopen(Request(url,headers={'Range':'bytes=0-1023'}),timeout=30) as response:
    size=int(response.headers['Content-Range'].split('/')[-1])
module.download(dict(Path=unquote(url.rsplit('/',1)[-1]),URL=url,Size=size,Sha256=digest,Workers=96,ChunkSize=1024*1024))
