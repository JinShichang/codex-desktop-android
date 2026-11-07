"""Authenticated MCP stdio relay for the vendored native phone driver."""
import json
import os
from pathlib import Path
import socket
import sys
import threading

CONFIG = Path('/usr/local/share/codex/phone/bridge.json')

def connect(config=CONFIG):
    cfg = json.loads(Path(config).read_text(encoding='utf-8'))
    if cfg.get('v') != 1 or not isinstance(cfg.get('token'), str):
        raise ValueError('Invalid phone bridge descriptor')
    endpoints = []
    if cfg.get('abstract'):
        endpoints.append((socket.AF_UNIX, '\0' + cfg['abstract']))
    if cfg.get('tcpPort'):
        endpoints.append((socket.AF_INET, ('127.0.0.1', cfg['tcpPort'])))
    last = None
    for family, address in endpoints:
        s = socket.socket(family, socket.SOCK_STREAM)
        try:
            s.settimeout(3)
            s.connect(address)
            s.sendall((json.dumps({'dshPhone': 1, 'token': cfg['token']}) + '\n').encode())
            s.settimeout(None)
            return s
        except OSError as e:
            last = e
            s.close()
    raise ConnectionError('Phone bridge unavailable') from last

def main():
    try:
        with connect(sys.argv[1] if len(sys.argv) > 1 else CONFIG) as s:
            def send():
                try:
                    while data := os.read(sys.stdin.fileno(), 65536):
                        s.sendall(data)
                finally:
                    try: s.shutdown(socket.SHUT_WR)
                    except OSError: pass
            threading.Thread(target=send, daemon=True).start()
            while data := s.recv(65536):
                sys.stdout.buffer.write(data)
                sys.stdout.buffer.flush()
    except (OSError, ValueError, KeyError):
        print('Phone MCP unavailable. Open ChatGPT > Android 工具 > 手机操控, enable it, then restart the desktop.', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
