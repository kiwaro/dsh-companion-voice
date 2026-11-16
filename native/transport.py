"""Token-authenticated loopback transport without proxies or redirects."""
import ctypes
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, ProxyHandler, HTTPRedirectHandler, Request


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def alive(pid):
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel.OpenProcess.restype = ctypes.c_void_p
    handle = kernel.OpenProcess(0x1000, False, pid)
    if not handle:
        return ctypes.get_last_error() == 5
    try:
        code = ctypes.c_ulong()
        return bool(kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))) and code.value == 259
    finally:
        kernel.CloseHandle(ctypes.c_void_p(handle))


class Transport:
    def __init__(self, path):
        self.path = Path(path)
        data = json.loads(self.path.read_text(encoding='utf-8'))
        url = urlsplit(data['origin'])
        if data.get('version') != 1 or url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.path or url.query or url.fragment or url.username or url.password:
            raise ValueError('connection-origin')
        if not isinstance(data.get('token'), str) or len(data['token']) != 64 or not isinstance(data.get('pid'), int):
            raise ValueError('connection-format')
        self.data = data

    def valid(self):
        try:
            return alive(self.data['pid']) and json.loads(self.path.read_text(encoding='utf-8'))['token'] == self.data['token']
        except (OSError, ValueError, KeyError):
            return False

    def post(self, route, data, timeout=15):
        request = Request(self.data['origin']+route, data=json.dumps(data, ensure_ascii=False).encode('utf-8'),
                          headers={'Content-Type': 'application/json', 'Authorization': 'Bearer '+self.data['token']})
        with build_opener(ProxyHandler({}), NoRedirect()).open(request, timeout=timeout) as response:
            return json.load(response)
