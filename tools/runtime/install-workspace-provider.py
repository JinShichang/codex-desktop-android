"""Apply one fingerprint-gated dependency-provider hook to a known client ASAR.

The original archive is preserved. Only reviewed modules receive added
Codex adapters; every existing byte in every other member is retained. This is
a Codex client integration, never represented as an unchanged official ASAR.
"""
import argparse
import contextlib
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import struct
import tempfile

KNOWN = {'d6511a6999ba4a6e3579001274fc79addae3b2604503af52600523b4ccf3c9d3': {'module': '.vite/build/early-bootstrap-824-71d2a741f6138352.js',
 'sha256': 'be1ce76c13ab45bd2df4575e566a3cd8e8ff2315431a1e55d1ca398058d3b147',
 'insertions': [{'at': 244835,
                 'code': '\n'
                         ';/* Codex workspace provider v1 */\n'
                         "({resolveManifest:et,validatePaths:ew,diagnose:X}=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({resolveManifest:et,validatePaths:ew,diagnose:X}));\n",
                 'role': 'workspaceProvider'},
                {'at': 163739,
                 'code': '\n'
                         ';/* Codex startup configuration probe */\n'
                         "G=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateStartupTransportResolver(G);\n",
                 'role': 'startupProbeResolver'},
                {'at': 227292,
                 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({instructions:",
                 'role': 'wrap-instructions-start'},
                {'at': 227894,
                 'code': '}).instructions',
                 'role': 'wrap-instructions-end'},
                {'at': 232768,
                 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({downloadFile:",
                 'role': 'wrap-downloadFile-start'},
                {'at': 233509,
                 'code': '}).downloadFile',
                 'role': 'wrap-downloadFile-end'}]},
 'ff2f15086473082610eb5756177a4a7f926a05d715437070b84c4fca9b94dd85': {'module': '.vite/build/early-bootstrap-824-8c6252e0131a7fe3.js',
                                                                      'sha256': '135ba428856dcfa52b53be2cc714bef8ed4fe8cefdad6011e61c89f27069b36b',
                                                                      'insertions': [{'at': 244092,
                                                                                      'code': '\n'
                                                                                              ';/* '
                                                                                              'Codex '
                                                                                              'workspace '
                                                                                              'provider '
                                                                                              'v1 */\n'
                                                                                              "({resolveManifest:et,validatePaths:ew,diagnose:X}=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({resolveManifest:et,validatePaths:ew,diagnose:X}));\n",
                                                                                      'role': 'workspaceProvider'},
                                                                                     {'at': 226576,
                                                                                      'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({instructions:",
                                                                                      'role': 'wrap-instructions-start'},
                                                                                     {'at': 227178,
                                                                                      'code': '}).instructions',
                                                                                      'role': 'wrap-instructions-end'},
                                                                                     {'at': 232039,
                                                                                      'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({downloadFile:",
                                                                                      'role': 'wrap-downloadFile-start'},
                                                                                     {'at': 232752,
                                                                                      'code': '}).downloadFile',
                                                                                      'role': 'wrap-downloadFile-end'},
                                                                                     {'at': 167697,
                                                                                      'code': '\n'
                                                                                              ';/* '
                                                                                              'Codex '
                                                                                              'startup '
                                                                                              'configuration '
                                                                                              'probe '
                                                                                              '*/\n'
                                                                                              "G=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateStartupTransportResolver(G);\n",
                                                                                      'role': 'startupProbeResolver'}]},
 '7dede49e4423c003f2133a89dd5de99e2ae03a4b0507f94c6a35c999f80e7c74': {'module': '.vite/build/application-network-startup-Bu9OoKJq.js',
                                                                      'sha256': 'cb1550aa4ea151512454654511f42844779cf53ef0300068034bec744cf91487',
                                                                      'names': ['Xr',
                                                                                'li',
                                                                                'Ei',
                                                                                'Hr',
                                                                                'zr'],
                                                                      'networkProbe': 'xl'},
 'a39fb89a6a676d2ad0b47ce5b50d513a8024993403f5d2f5f99355d9c1b07179': {'module': '.vite/build/application-network-startup-BG13czUt.js',
                                                                      'sha256': '90db83017c05bf247b53a09bb04a3312e0003259c56144535b09805085b16a6c',
                                                                      'names': ['ea',
                                                                                'pa',
                                                                                'Aa',
                                                                                'Ki',
                                                                                'Ui'],
                                                                      'networkProbe': 'Qc'},
 '1306be560e77fbfb68dd8b0bccac58d52396a3d445f12810a50438fb05f2e61d': {'module': '.vite/build/src-VqXTPopo.js',
                                                                      'sha256': '8d056524ea3f5714e5e0a254afd88f018d58465bc6ea026adee3c80ff7799e29',
                                                                      'names': ['xB',
                                                                                'PB',
                                                                                'QB',
                                                                                'hB',
                                                                                'fB']}}


KNOWN['f0752b2e81b94fdfdd986091c80466a05cb2f848289fd4c20887cd411a577670'] = {
    'module': '.vite/build/early-bootstrap-824-fc5a1a4b8b4c6ac3.js',
    'sha256': 'c8aefdffe99868691304d228a789fccc836699784987fc8bcf95bd96ea6fba20',
    'bootstrap': {
        'module': '.vite/build/early-bootstrap.js',
        'sha256': '6a19597cbc17c1c237e3c524e1a4585970f4395bd73c1383ae5bc99090f547dc',
    },
    'windowMode': {
        'module': '.vite/build/early-bootstrap-916-34c79998699157a6.js',
        'sha256': '943136e6b9f72336df43638a5b9ee6516c351ed1b9be734bd08bdc7452895a25',
        'at': 3213165,
    },
    'catalogSync': {
        'module': 'webview/assets/async/191628.72f208c924.js',
        'sha256': '775f0ef59fb0b9866f98ad6148c731548f9c5cd8c7ad2d6c60b40ef83d03639f',
        'at': 132147,
        'before': ',(0,u.useEffect)(()=>{r?.then(()=>f.reconcileHosts()).catch(()=>{})},[r,f])',
        'code': ',(0,u.useEffect)(()=>{f.updateStatus(n)},[f,n])',
    },
    'insertions': [
        {'at': 190165, 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateStartupTransportResolver(", 'role': 'startup-config-start'},
        {'at': 190173, 'code': ')', 'role': 'startup-config-end'},
        {'at': 190206, 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateStartupTransportResolver(", 'role': 'startup-signOut-start'},
        {'at': 190214, 'code': ')', 'role': 'startup-signOut-end'},
        {'at': 241217, 'code': "\n;/* Codex workspace provider v1 */\n({resolveManifest:et,validatePaths:ev,diagnose:X}=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({resolveManifest:et,validatePaths:ev,diagnose:X}));\n", 'role': 'workspaceProvider'},
        {'at': 222741, 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({instructions:", 'role': 'wrap-instructions-start'},
        {'at': 223343, 'code': '}).instructions', 'role': 'wrap-instructions-end'},
        {'at': 228232, 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({downloadFile:", 'role': 'wrap-downloadFile-start'},
        {'at': 228973, 'code': '}).downloadFile', 'role': 'wrap-downloadFile-end'},
    ],
}

# Official Linux ARM64 desktop 26.1120.41243; same reviewed hook roles as 26.1117.31558.
KNOWN['d30bfa984959784848c051d443eae8b986ea2b7f46ec50bfbcdf5b6267fc36de'] = {'module': '.vite/build/early-bootstrap-824-2ecd0bf923d56c72.js',
 'sha256': '6e21a71b8a2e0cff3fd7b45c0274e796b85432e30e9744525030162fa640b34e',
 'bootstrap': {'module': '.vite/build/early-bootstrap.js',
               'sha256': '07cfc0e1966e19e0344206402e0f4fa7a73e938e535d097c5148521d8f00228e'},
 'windowMode': {'module': '.vite/build/early-bootstrap-916-5cf181a62de3d3c8.js',
                'sha256': '5cc6e031c038e97aee2e8b84f0be3658664387ba26218d2a3eefba46217278d8',
                'at': 2564918},
 'catalogSync': {'module': 'webview/assets/async/886197.66245499ac.js',
                 'sha256': '720143e45fd97e9944d89bb8a5692b3f7a0425692add2dce819e80a28143f16f',
                 'at': 132347,
                 'before': ',(0,h.useEffect)(()=>{a?.then(()=>g.reconcileHosts()).catch(()=>{})},[a,g])',
                 'code': ',(0,h.useEffect)(()=>{g.updateStatus(n)},[g,n])'},
 'insertions': [{'at': 190165,
                 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateStartupTransportResolver(",
                 'role': 'startup-config-start'},
                {'at': 190173, 'code': ')', 'role': 'startup-config-end'},
                {'at': 190206,
                 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateStartupTransportResolver(",
                 'role': 'startup-signOut-start'},
                {'at': 190214, 'code': ')', 'role': 'startup-signOut-end'},
                {'at': 241507,
                 'code': '\n'
                         ';/* Codex workspace provider v1 */\n'
                         "({resolveManifest:et,validatePaths:ev,diagnose:X}=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({resolveManifest:et,validatePaths:ev,diagnose:X}));\n",
                 'role': 'workspaceProvider'},
                {'at': 223031,
                 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({instructions:",
                 'role': 'wrap-instructions-start'},
                {'at': 223633, 'code': '}).instructions', 'role': 'wrap-instructions-end'},
                {'at': 228522,
                 'code': "require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({downloadFile:",
                 'role': 'wrap-downloadFile-start'},
                {'at': 229263, 'code': '}).downloadFile', 'role': 'wrap-downloadFile-end'}]}



def digest(data):
    return hashlib.sha256(data).hexdigest()


def adapt(source):
    """Retain the in-memory API; installation uses the bounded stream plan."""
    stream = io.BytesIO(source)
    plan, descriptor = adaptation_plan(stream, digest(source))
    return b''.join(plan_chunks(stream, plan)), descriptor


def adaptation_plan(stream, source_sha256, *, bootstrap=True, catalog_sync=True):
    descriptor = KNOWN.get(source_sha256)
    if descriptor is None:
        raise ValueError('Client revision not reviewed for the Codex workspace provider')
    stream.seek(0)
    _, header_size, payload_size, json_size = struct.unpack('<IIII', stream.read(16))
    if payload_size + 4 != header_size or json_size > payload_size - 4:
        raise ValueError('Unexpected ASAR header')
    base = 8 + header_size
    header = json.loads(stream.read(json_size))
    blocks = []
    offset = 0
    changed = []
    bootstrap_module = descriptor.get('bootstrap') if bootstrap else None
    window_mode = descriptor.get('windowMode') if bootstrap else None
    catalog_module = descriptor.get('catalogSync') if catalog_sync else None

    def visit(directory, prefix=''):
        nonlocal offset
        for name, member in directory['files'].items():
            location = prefix + name
            if 'files' in member:
                visit(member, location + '/')
            elif 'offset' in member:
                start = base + int(member['offset'])
                size = member['size']
                segment = (start, size)
                if location == descriptor['module']:
                    stream.seek(start)
                    data = stream.read(size)
                    if digest(data) != descriptor['sha256']:
                        raise ValueError('The dependency module differs from the reviewed bytes')
                    if 'insertions' in descriptor:
                        previous = len(data) + 1
                        for insertion in sorted(descriptor['insertions'], key=lambda item: item['at'], reverse=True):
                            at = insertion['at']
                            if type(at) is not int or not 0 <= at < previous:
                                raise ValueError('Invalid reviewed module insertion')
                            data = data[:at] + insertion['code'].encode('utf-8') + data[at:]
                            previous = at
                    else:
                        names = descriptor['names']
                        properties = ['resolveManifest', 'downloadFile', 'validatePaths', 'diagnose', 'instructions']
                        entries = ','.join(key + ':' + value for key, value in zip(properties, names))
                        hook = ("\n;/* Codex workspace provider v1 */\n"
                                f"({{{entries}}}=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrate({{{entries}}}));\n")
                        if descriptor.get('networkProbe'):
                            probe = descriptor['networkProbe']
                            hook += ("/* Codex startup configuration probe */\n"
                                     f"{probe}=require('/usr/local/lib/codex/codex-workspace-provider.cjs').integrateNetworkProbe({probe});\n")
                        data += hook.encode()
                    segment = data
                    size = len(data)
                    changed.append(location)
                    if 'integrity' in member:
                        block_size = member['integrity']['blockSize']
                        member['integrity'].update(hash=digest(data),
                            blocks=[digest(data[i:i + block_size]) for i in range(0, len(data), block_size)])
                elif catalog_module and location == catalog_module['module']:
                    stream.seek(start)
                    data = stream.read(size)
                    if digest(data) != catalog_module['sha256']:
                        raise ValueError('The catalog module differs from the reviewed bytes')
                    at = catalog_module['at']
                    before = catalog_module['before'].encode('utf-8')
                    if data[at:at + len(before)] != before:
                        raise ValueError('The reviewed catalog status insertion differs')
                    # Keep the reader alive across status changes. Re-running
                    # its activation effect would dispose its paging caches.
                    data = data[:at] + catalog_module['code'].encode('utf-8') + data[at:]
                    segment = data
                    size = len(data)
                    changed.append(location)
                    if 'integrity' in member:
                        block_size = member['integrity']['blockSize']
                        member['integrity'].update(hash=digest(data),
                            blocks=[digest(data[i:i + block_size]) for i in range(0, len(data), block_size)])
                elif window_mode and location == window_mode['module']:
                    stream.seek(start)
                    data = stream.read(size)
                    if digest(data) != window_mode['sha256']:
                        raise ValueError('The window mode module differs from the reviewed bytes')
                    at = window_mode['at']
                    if data[at:at+len(b'let i="onboarding"!==t.mode?null:')] != b'let i="onboarding"!==t.mode?null:':
                        raise ValueError('The reviewed window mode insertion differs')
                    hook = b"t=require('/usr/local/lib/codex/codex-workspace-provider.cjs').phoneWindowMode(t);"
                    data = data[:at] + hook + data[at:]
                    segment = data
                    size = len(data)
                    changed.append(location)
                    if 'integrity' in member:
                        block_size = member['integrity']['blockSize']
                        member['integrity'].update(hash=digest(data),
                            blocks=[digest(data[i:i + block_size]) for i in range(0, len(data), block_size)])
                elif bootstrap_module and location == bootstrap_module['module']:
                    stream.seek(start)
                    data = stream.read(size)
                    if digest(data) != bootstrap_module['sha256']:
                        raise ValueError('The window bootstrap differs from the reviewed bytes')
                    # Register before the upstream bootstrap creates any windows,
                    # independently of lazy startup/configuration dependencies.
                    data = (b";/* Codex phone window bootstrap v1 */\n"
                            b"require('/usr/local/lib/codex/codex-workspace-provider.cjs')"
                            b".installPhoneFullscreen(require('electron'));\n") + data
                    segment = data
                    size = len(data)
                    changed.append(location)
                    if 'integrity' in member:
                        block_size = member['integrity']['blockSize']
                        member['integrity'].update(hash=digest(data),
                            blocks=[digest(data[i:i + block_size]) for i in range(0, len(data), block_size)])
                member['offset'] = str(offset)
                member['size'] = size
                blocks.append(segment)
                offset += size
    visit(header)
    expected_modules = [descriptor['module']]
    if bootstrap_module:
        expected_modules.append(bootstrap_module['module'])
    if window_mode:
        expected_modules.append(window_mode['module'])
    if catalog_module:
        expected_modules.append(catalog_module['module'])
    if sorted(changed) != sorted(expected_modules):
        raise ValueError('Expected exactly the reviewed adaptation modules')
    raw = json.dumps(header, ensure_ascii=False, separators=(',', ':')).encode()
    padded = raw + b'\0' * (-len(raw) % 4)
    header_bytes = struct.pack('<II', len(padded) + 4, len(raw)) + padded
    return [struct.pack('<II', 4, len(header_bytes)) + header_bytes, *blocks], descriptor


CHUNK = 1024 * 1024


def plan_chunks(stream, plan):
    for segment in plan:
        if isinstance(segment, bytes):
            yield segment
            continue
        offset, remaining = segment
        stream.seek(offset)
        while remaining:
            data = stream.read(min(CHUNK, remaining))
            if not data:
                raise ValueError('Truncated reviewed ASAR')
            remaining -= len(data)
            yield data


def stream_digest(stream):
    stream.seek(0)
    result = hashlib.sha256()
    while data := stream.read(CHUNK):
        result.update(data)
    return result.hexdigest()


def identity(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mode,
            info.st_mtime_ns, info.st_ctime_ns, info.st_nlink)


def exists(path):
    return os.path.lexists(path)


def directory_chain(path):
    """Validate existing ancestors without creating any path or following aliases."""
    for item in reversed((path, *path.parents)):
        if exists(item) and not stat.S_ISDIR(item.lstat().st_mode):
            raise ValueError('Workspace adapter state is not a real directory')


@contextlib.contextmanager
def snapshot(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise ValueError('Expected a regular, unaliased workspace adapter file')
        yield stream
        if identity(os.fstat(stream.fileno())) != identity(before) or identity(path.lstat()) != identity(before):
            raise ValueError('Workspace adapter input changed while being verified')


def verified_backup(path, expected):
    with snapshot(path) as stream:
        if stream_digest(stream) != expected:
            raise ValueError('The preserved official ASAR backup differs')


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate workspace adapter receipt field')
        result[key] = value
    return result


def adaptation_variants(descriptor):
    # Latest first, followed only by previously shipped adaptation plans.
    # Independently recompute every accepted archive and receipt from backup.
    yield {'bootstrap': True, 'catalog_sync': True}
    if descriptor.get('catalogSync'):
        yield {'bootstrap': True, 'catalog_sync': False}
    if descriptor.get('bootstrap'):
        yield {'bootstrap': False, 'catalog_sync': False}


def inspect_client(asar, state):
    """Read-only admission. Receipts never select or authenticate client bytes."""
    directory_chain(state)
    directory_chain(asar.parent)
    if asar.absolute().is_relative_to(state.absolute()):
        raise ValueError('Installed ASAR must be separate from its backup state')
    with snapshot(asar) as stream:
        current_identity = identity(os.fstat(stream.fileno()))
        current = stream_digest(stream)
    official = current if current in KNOWN else None
    original_path = asar if official else None
    if official is None:
        for candidate in KNOWN:
            backup = state / (candidate + '.official.asar')
            if not exists(backup):
                continue
            with snapshot(backup) as stream:
                if stream_digest(stream) != candidate:
                    raise ValueError('The preserved official ASAR backup differs')
                for variant in adaptation_variants(KNOWN[candidate]):
                    plan, _ = adaptation_plan(stream, candidate, **variant)
                    expected = hashlib.sha256()
                    for block in plan_chunks(stream, plan):
                        expected.update(block)
                    if expected.hexdigest() == current:
                        official, original_path = candidate, backup
                        break
            if official:
                break
    if official is None:
        raise ValueError('Client revision not reviewed for the Codex workspace provider')
    backup = state / (official + '.official.asar')
    if original_path == asar and exists(backup):
        verified_backup(backup, official)
    records = []
    with snapshot(original_path) as stream:
        if stream_digest(stream) != official:
            raise ValueError('Reviewed original ASAR changed')
        for variant in adaptation_variants(KNOWN[official]):
            plan, descriptor = adaptation_plan(stream, official, **variant)
            expected = hashlib.sha256()
            for block in plan_chunks(stream, plan):
                expected.update(block)
            record = {'provider': 'Codex', 'officialSha256': official, 'adaptedSha256': expected.hexdigest(),
                      'modifiedModule': descriptor['module'], 'backup': str(backup)}
            if variant['bootstrap'] and descriptor.get('bootstrap'):
                record['modifiedModules'] = [descriptor['module'], descriptor['bootstrap']['module']]
                if descriptor.get('windowMode'):
                    record['modifiedModules'].append(descriptor['windowMode']['module'])
            if variant['catalog_sync'] and descriptor.get('catalogSync'):
                record.setdefault('modifiedModules', [descriptor['module']]).append(descriptor['catalogSync']['module'])
            records.append(record)
    record = records[0]
    record_path = state / 'client-adapter.json'
    if exists(record_path):
        with snapshot(record_path) as stream:
            data = stream.read(65537)
        if len(data) > 65536 or json.loads(data, object_pairs_hook=unique_json) not in records:
            raise ValueError('Workspace adapter receipt differs from independently reviewed bytes')
    if identity(asar.lstat()) != current_identity:
        raise ValueError('Installed ASAR changed during compatibility validation')
    return record, current_identity, current == official, current != record['adaptedSha256']


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def create_state(path):
    directory_chain(path)
    missing = []
    current = path
    while not exists(current):
        missing.append(current)
        current = current.parent
    for item in reversed(missing):
        item.mkdir(mode=0o700)
        sync_directory(item.parent)


def checkpoint(name):
    """Test injection point; production has no environment-controlled failpoint."""


def atomic_write(path, chunks, mode, before_publish=lambda: None):
    fd, temporary = tempfile.mkstemp(prefix='.codex-adapter-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            for data in chunks:
                stream.write(data)
            stream.flush()
            os.fchmod(stream.fileno(), mode)
            os.fsync(stream.fileno())
        before_publish()
        checkpoint('before-rename:' + path.name)
        os.replace(temporary, path)
        checkpoint('after-rename:' + path.name)
        sync_directory(path.parent)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def original_chunks(path, expected):
    with snapshot(path) as stream:
        actual = hashlib.sha256()
        while data := stream.read(CHUNK):
            actual.update(data)
            yield data
        if actual.hexdigest() != expected:
            raise ValueError('Reviewed original ASAR changed before backup publication')


def adapted_chunks(backup, record):
    with snapshot(backup) as stream:
        if stream_digest(stream) != record['officialSha256']:
            raise ValueError('The preserved official ASAR backup differs')
        plan, _ = adaptation_plan(stream, record['officialSha256'])
        actual = hashlib.sha256()
        for block in plan_chunks(stream, plan):
            actual.update(block)
            yield block
        if actual.hexdigest() != record['adaptedSha256']:
            raise ValueError('Recomputed workspace adaptation differs')


def install(asar, state, check_only=False):
    record, observed, original, needs_update = inspect_client(asar, state)
    if check_only:
        return {'status': 'verified', 'clientState': 'original' if original else
                ('upgrade-required' if needs_update else 'adapted'), **record}
    # Admission precedes even state/lock creation. This lease serializes our
    # installers; it is not a boundary against hostile concurrent same-UID code.
    create_state(state)
    lock_path = state / 'install.lock'
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600)
    with os.fdopen(fd, 'r+b') as lock:
        info = os.fstat(lock.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError('Invalid workspace adapter installation lease')
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        os.fsync(lock.fileno())
        sync_directory(state)
        record, observed, original, needs_update = inspect_client(asar, state)
        backup = state / (record['officialSha256'] + '.official.asar')
        if needs_update:
            if not exists(backup):
                def absent_backup():
                    if exists(backup):
                        raise ValueError('Official ASAR backup appeared during publication')
                atomic_write(backup, original_chunks(asar, record['officialSha256']), 0o600, absent_backup)
            # An earlier process may have died immediately after the rename.
            with snapshot(backup) as stream:
                if stream_digest(stream) != record['officialSha256']:
                    raise ValueError('The preserved official ASAR backup differs')
                os.fsync(stream.fileno())
            sync_directory(state)
            checkpoint('after-backup')
            def unchanged_asar():
                if identity(asar.lstat()) != observed:
                    raise ValueError('Installed ASAR changed before activation')
            atomic_write(asar, adapted_chunks(backup, record), observed[3] & 0o777, unchanged_asar)
            checkpoint('after-asar')
        else:
            # Recovery also makes an earlier ASAR publication durable before
            # publishing its receipt; reconstructing that receipt needs no guess.
            with snapshot(asar) as stream:
                os.fsync(stream.fileno())
            sync_directory(asar.parent)
        record_path = state / 'client-adapter.json'
        if not exists(record_path) or json.loads(record_path.read_bytes(), object_pairs_hook=unique_json) != record:
            atomic_write(record_path, [json.dumps(record, indent=2).encode('utf-8')], 0o600)
            checkpoint('after-receipt')
        else:
            with snapshot(record_path) as stream:
                os.fsync(stream.fileno())
            sync_directory(state)
        return {'status': 'adapted' if original else ('upgraded' if needs_update else 'current'), **record}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--asar', type=Path, required=True)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--check', action='store_true', help='Verify compatibility without creating or changing any file')
    args = parser.parse_args()
    print(json.dumps(install(args.asar, args.state, args.check)))


if __name__ == '__main__':
    main()
