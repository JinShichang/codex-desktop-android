"""Configure the native phone's projectless folder using the official editor.

Only desktop.projectlessWorkspaceRoot is written. No executor policy, identity,
authentication or model catalog is synthesized or changed by this helper.
"""
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import signal
import stat
import subprocess
import time
import tomllib

OFFICIAL_CLI = '/usr/lib/chatgpt/resources/codex'
KEY = 'projectlessWorkspaceRoot'


def inside_workspace(value, workspace):
    return (isinstance(value, str) and value.startswith('/')
            and str(PurePosixPath(value)) == value and '..' not in PurePosixPath(value).parts
            and PurePosixPath(value).is_relative_to(workspace))


def selected_workspace(env):
    if env.get('CODEX_PHONE_CLIENT_COMPAT') != '1' or not env.get('CODEX_NATIVE_BOOTSTRAP'):
        return None
    workspace = env.get('CODEX_NATIVE_WORKSPACE', '')
    if not re.fullmatch(r'/data/(?:data|user/\d+)/com\.ai\.codex/files/projects', workspace):
        raise ValueError('Native phone workspace is not the declared application project root')
    if not stat.S_ISDIR(os.lstat(workspace).st_mode):
        raise ValueError('Native phone workspace must be a real directory')
    return workspace


def write_official_config(workspace, *, executable=OFFICIAL_CLI, env=None, timeout=30, edits=None):
    """Use upstream TOML editing, preserving comments and unrelated settings."""
    proc = subprocess.Popen([executable, 'app-server'], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                            env=env, start_new_session=True)
    deadline = time.monotonic() + timeout
    selector = selectors.DefaultSelector()
    selector.register(proc.stdout, selectors.EVENT_READ)
    pending = bytearray()

    def send(value):
        proc.stdin.write(json.dumps(value).encode() + b'\n')
        proc.stdin.flush()

    def response(identifier):
        while True:
            if b'\n' in pending:
                line, _, rest = pending.partition(b'\n')
                pending[:] = rest
                message = json.loads(line)
                if message.get('id') != identifier:
                    continue
                if 'error' in message:
                    raise RuntimeError('Official configuration editor refused the write: '
                                       + str(message['error'].get('message', 'RPC error'))[:512])
                return message['result']
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(remaining):
                raise TimeoutError('Official configuration editor timed out')
            block = os.read(proc.stdout.fileno(), 65536)
            if not block:
                raise RuntimeError('Official configuration editor exited before replying')
            pending.extend(block)
            if len(pending) > 4 * 1024 * 1024:
                raise ValueError('Official configuration editor response exceeds its bound')

    try:
        send({'id': 1, 'method': 'initialize', 'params': {
            'clientInfo': {'name': 'codex_phone_profile', 'version': '1'},
            'capabilities': {'experimentalApi': True}}})
        response(1)
        send({'method': 'initialized', 'params': {}})
        send({'id': 2, 'method': 'config/batchWrite', 'params': {'edits': edits if edits is not None else [{
            'keyPath': 'desktop.' + KEY, 'value': workspace, 'mergeStrategy': 'replace'}]}})
        response(2)
    finally:
        selector.close()
        proc.stdin.close()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        proc.stdout.close()


def prepare(env=None):
    env = dict(os.environ if env is None else env)
    workspace = selected_workspace(env)
    if workspace is None:
        return {'status': 'unselected'}
    home = Path(env.get('CODEX_HOME') or str(Path(env['HOME']) / '.codex'))
    config = home / 'config.toml'
    before = tomllib.loads(config.read_text()) if config.exists() else {}
    current = before.get('desktop', {}).get(KEY)
    if inside_workspace(current, workspace):
        return {'status': 'current'}
    write_official_config(workspace, env=env)
    after = tomllib.loads(config.read_text())
    expected = {**before, 'desktop': {**before.get('desktop', {}), KEY: workspace}}
    if after != expected:
        raise RuntimeError('Official phone profile edit did not preserve the expected configuration')
    return {'status': 'updated'}


if __name__ == '__main__':
    print(json.dumps(prepare()))
