"""Register APK-owned phone MCP with the official config editor; preserve other settings."""
import json
import os
from pathlib import Path
import tomllib
from codex_phone_profile import write_official_config

RELAY='/usr/local/share/codex/plugins/codex-android/scripts/phone_relay.py'
SKILL='/usr/local/share/codex/plugins/codex-android/skills/phone/SKILL.md'
SERVER={'command':'/usr/bin/python3','args':['-I','-B',RELAY],
        'startup_timeout_sec':15,'tool_timeout_sec':660,'enabled':True}

def server_for(env):
    tools=env.get('CODEX_TOOLS_DIR')
    if not tools: return SERVER
    root=Path(tools)
    if env.get('CODEX_PHONE_CLIENT_COMPAT') == '1':
        return {**SERVER, 'args':['-I','-B',RELAY,str(root/'phone-bridge.json')],
                'cwd':str(root), 'env':{'LD_LIBRARY_PATH':'','LD_PRELOAD':'','PYTHONDONTWRITEBYTECODE':'1'}}
    installation=json.loads((root/'installation.json').read_text(encoding='utf-8'))
    if installation.get('schema')!='codex.local-tools.v1' or Path(installation['filesDir'])/'codex-tools' != root:
        raise ValueError('Unexpected native MCP installation')
    native=Path(installation['nativeLibraryDir'])
    if not str(native).startswith('/data/app/') or not (native/'libcodex_python_cli.so').is_file():
        raise ValueError('Native phone MCP interpreter is missing')
    return {**SERVER,'command':str(native/'libcodex_python_cli.so'),
            'args':['-I','-B',str(root/'phone_relay.py'),str(root/'phone-bridge.json')],
            'cwd':str(root),'env':{'LD_LIBRARY_PATH':str(native),'LD_PRELOAD':'','PYTHONDONTWRITEBYTECODE':'1'}}

def prepare(env=None):
    env=dict(os.environ if env is None else env)
    home=Path(env.get('CODEX_HOME') or str(Path(env['HOME'])/'.codex'))
    home.mkdir(parents=True,exist_ok=True)
    path=home/'config.toml'
    before=tomllib.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    server=server_for(env)
    servers=before.get('mcp_servers',{})
    if servers.get('phone') != server:
        write_official_config(None,env=env,edits=[{'keyPath':'mcp_servers.phone','value':server,'mergeStrategy':'replace'}])
        after=tomllib.loads(path.read_text(encoding='utf-8'))
        expected={**before,'mcp_servers':{**servers,'phone':server}}
        if after != expected: raise RuntimeError('Phone MCP config write changed unrelated settings')
    target=home/'skills/codex-phone/SKILL.md'
    contents=Path(SKILL).read_bytes()
    target.parent.mkdir(parents=True,exist_ok=True)
    if not target.exists() or target.read_bytes()!=contents:
        temp=target.with_suffix('.next');temp.write_bytes(contents);temp.replace(target)
    return {'phoneMcp':'registered','skill':'installed'}

if __name__=='__main__': print(json.dumps(prepare()))
