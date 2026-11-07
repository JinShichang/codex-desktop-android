"""Codex Android MCP over authenticated same-UID Unix sockets, stdlib only."""
import json
import os
from pathlib import Path
import socket
import struct
import sys

LIMIT = 16 * 1024 * 1024
CONFIG = Path('/usr/local/share/codex/android-bridge.json')

def schema(properties=None, required=()):
    return dict(type='object', properties=properties or {}, required=list(required), additionalProperties=False)

STRING = {'type': 'string'}
NUMBER = {'type': 'number'}
INTEGER = {'type': 'integer'}

def tool(op, description, properties=None, required=(), readonly=False):
    return {'name': 'android_' + op, 'description': description, 'inputSchema': schema(properties, required),
            'annotations': {'readOnlyHint': readonly, 'openWorldHint': True}}

TOOLS = [
    tool('install_apk', 'Open one APK under /sdcard with the installer selected by Android while Codex is foreground. Use for ordinary install or update requests. The selected installer handles prompts and installation. installer_opened reports the handoff only. Use android_package_info to verify the installed version after the installer finishes.',
         {'path':STRING}, ['path']),
    tool('package_info', 'Read the installed versionCode and versionName for one exact Android package name in the current user. Use to verify installs and updates without Root. found=false means the package is absent or hidden by Android.',
         {'packageName':STRING}, ['packageName'], readonly=True),
    tool('device_command', 'Execute one allowlisted Android device command as argv. For explicitly requested silent installation or pm install, use authorized root with ["pm","install","-r","/sdcard/Download/app.apk"]. For ordinary installation use android_install_apk. App with the Files grant, or authorized root, may copy a regular file anywhere within /sdcard with ["cp","/sdcard/source","/sdcard/destination"]. A destination file can be replaced, and an existing directory receives the original filename. Verify an unknown outcome before retrying. ADB and Shizuku support other allowlisted commands. Native policy blocks shell syntax and unknown commands. Project builds use normal execution tools.',
         {'argv':{'type':'array','items':STRING,'minItems':1,'maxItems':32}, 'channel':{'type':'string','enum':['app','adb','root','shizuku']}}, ['argv']),
    tool('sensor_list', 'List physical sensors and per-sensor grants.', readonly=True),
    tool('sensor_read', 'Read one enabled sensor sample; name from sensor_list. Default off.', {'name':STRING}, ['name'], readonly=True),
    tool('location', 'Read one current foreground location after native and Android permission grants. Default off.', readonly=True),
    tool('flashlight', 'Set flashlight after explicit native capability grant.', {'enabled':{'type':'boolean'}}, ['enabled']),
    tool('clipboard_read', 'Read plain-text clipboard while ChatGPT is foreground, with clipboard grant.', readonly=True),
    tool('clipboard_write', 'Write plain-text clipboard while ChatGPT is foreground, with clipboard grant.', {'text':STRING}, ['text']),
    tool('file_list', 'List bounded directory entries under app projects or shared storage; credential directories refused.', {'path':STRING}, ['path'], readonly=True),
    tool('file_read', 'Read up to 1 MiB UTF-8 text from app projects/shared storage; no symlink traversal or credential directories.', {'path':STRING}, ['path'], readonly=True),
    tool('file_export', 'Export UTF-8 text or one existing project/shared-storage file (up to 128 MiB) into Download/codex. Provide exactly one of text/path. Credential paths refused.', {'name':STRING,'text':STRING,'path':STRING}, ['name']),
    tool('interaction_notify', 'Post a task notification after capability and Android notification grants.', {'title':STRING,'text':STRING}, ['title','text']),
    tool('interaction_toast', 'Show a brief native foreground message.', {'text':STRING}, ['text']),
    tool('interaction_vibrate', 'Vibrate for 1..3000 ms with interaction grant.', {'durationMs':INTEGER}),
    tool('interaction_ask', 'Ask the user a native question with 2 or 3 options; poll interaction_answer with questionId. No default answer.', {'text':STRING,'options':{'type':'array','items':STRING,'minItems':2,'maxItems':3}}, ['text','options']),
    tool('interaction_answer', 'Read a question outcome. Unknown or cancelled is not approval.', {'questionId':STRING}, ['questionId'], readonly=True),
    tool('interaction_share', 'Open Android share chooser for user-intended text.', {'text':STRING}, ['text']),
    tool('interaction_open', 'Open an http(s) link in Android.', {'url':STRING}, ['url']),
    tool('status', 'Read actual Codex Android bridge and permission status, without reading messages or screen.', readonly=True),
    tool('request_access', 'Present the normal Android permission request for the requested task, without granting it. Use only the needed scope and only after user intent to use that capability. Returns immediately; check android_status after the user responds. Never approve your own permission dialog.',
         {'scope':{'type':'string','enum':['sms_read','screen_control']}}, ['scope']),
    tool('sms_status', 'Read SMS permission, default messaging app and transport scope; no message bodies.', readonly=True),
    tool('sms_search', 'Search the public Android SMS provider by literal text, exact address, conversation and dates. Does not cover RCS or archive metadata; no result is not proof no message exists in Google Messages.',
         {'text':STRING,'address':STRING,'threadId':INTEGER,'dateAfter':INTEGER,'dateBefore':INTEGER,'beforeId':INTEGER,'limit':{'type':'integer','minimum':1,'maximum':50}}, readonly=True),
    tool('sms_read', 'Read a bounded page of one SMS conversation. This does not mark messages read.', {'threadId':INTEGER,'beforeId':INTEGER,'limit':{'type':'integer','minimum':1,'maximum':50}}, ['threadId'], readonly=True),
]

def request(op, args, *, config_path=None):
    config = json.loads((CONFIG if config_path is None else config_path).read_text(encoding='utf-8'))
    uid = config['androidUid']
    if config.get('schema') != 'codex.android.bridge.v1' or type(uid) is not int or uid <= 0:
        raise ValueError('invalid_bridge_configuration')
    raw = json.dumps(dict(version=1, op=op, args=args), ensure_ascii=False).encode('utf-8') + b'\n'
    if len(raw) > 32768: raise ValueError('request_too_large')
    argv = args.get('argv') if op == 'device_command' else None
    executable = argv[0].removeprefix('/system/bin/') if isinstance(argv, list) and argv and isinstance(argv[0], str) else None
    file_command = executable == 'cp' or executable == 'pm' and argv[1:2] == ['install']
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as connection:
        connection.settimeout(20)
        connection.connect('\0codex-android-' + str(uid))
        peer = struct.unpack('3i', connection.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12))
        if peer[1] != uid: raise PermissionError('unexpected_android_peer')
        connection.sendall(raw)
        if file_command: connection.settimeout(150)
        data = bytearray()
        while not data.endswith(b'\n'):
            try:
                chunk = connection.recv(min(65536, LIMIT + 1 - len(data)))
            except TimeoutError:
                if file_command: return {'ok':False, 'error':'device_file_command_result_unknown', 'retrySafe':False}
                raise
            if not chunk: raise ConnectionError('incomplete_android_response')
            data.extend(chunk)
            if len(data) > LIMIT: raise ValueError('android_response_too_large')
        result = json.loads(data)
        if result.get('ok') is not True:
            if isinstance(result.get('result'), dict): return result['result']
            return {'ok':False, 'error':result.get('error','android_operation_failed')}
        return result['result']

def content(result):
    result = dict(result)
    encoded = result.pop('imageBase64', None)
    mime = result.pop('mimeType', 'image/png')
    answer = [{'type':'text', 'text':json.dumps(result, ensure_ascii=False)}]
    if encoded:
        if mime not in ('image/png','image/jpeg'): raise ValueError('unsupported_image_type')
        answer.append({'type':'image', 'mimeType':mime, 'data':encoded})
    return answer

def dispatch(message):
    method, params = message.get('method'), message.get('params', {})
    if method == 'initialize':
        return {'protocolVersion':params.get('protocolVersion','2024-11-05'), 'capabilities':{'tools':{}},
                'serverInfo':{'name':'codex-android','version':'0.2.0'},
                'instructions':'Android device tools. Use android_status to check device grants. For ordinary APK installation, use android_install_apk and follow the selected installer prompts. Verify the installed version by exact package name with android_package_info. Use the root install route only when the user requests silent install or pm install. Copy APKs built in private project storage to shared storage first. Device commands are allowlisted natively. Use explicit user intent. SMS queries are read-only and require the installation-local grant.'}
    if method == 'ping': return {}
    if method == 'tools/list': return {'tools':TOOLS}
    if method == 'tools/call':
        name = params.get('name')
        specification = next((t for t in TOOLS if t['name'] == name), None)
        if specification is None: raise ValueError('unknown_tool')
        args = params.get('arguments', {})
        if not isinstance(args,dict): raise ValueError('invalid_arguments')
        defined = specification['inputSchema']
        if set(args) - set(defined['properties']) or not set(defined['required']).issubset(args): raise ValueError('invalid_arguments')
        try:
            result = request(name.removeprefix('android_'),args)
            return {'content':content(result), 'isError':result.get('ok') is False}
        except Exception as error:
            code = str(error)
            if not code or any(c not in 'abcdefghijklmnopqrstuvwxyz_0123456789' for c in code): code = 'android_bridge_unavailable'
            return {'content':[{'type':'text','text':code}], 'isError':True}
    if method.startswith('notifications/'): return None
    raise ValueError('unknown_method')

def main():
    for raw in sys.stdin.buffer:
        if len(raw) > 65536: continue
        message = None
        try:
            message = json.loads(raw)
            result = dispatch(message)
            if 'id' not in message: continue
            reply = {'jsonrpc':'2.0','id':message['id'],'result':result}
        except Exception:
            reply = {'jsonrpc':'2.0','id':message.get('id') if isinstance(message,dict) else None,
                     'error':{'code':-32602,'message':'Invalid MCP request'}}
        sys.stdout.write(json.dumps(reply, ensure_ascii=False)+'\n'); sys.stdout.flush()

if __name__ == '__main__':
    if len(sys.argv) == 2: CONFIG = Path(sys.argv[1])
    main()
