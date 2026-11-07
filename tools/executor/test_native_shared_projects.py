"""Exercise the built ARM64 controller against a real nonroot native owner.

No phone, account, inference request or existing user project is used. Run on
Linux with CODEX_NATIVE_CONTROLLER and CODEX_NATIVE_TEST_HELPERS supplied.
The controller runner is optional (e.g. qemu-aarch64-static with a GNU sysroot).
"""
import asyncio
import base64
import importlib
import json
import os
from pathlib import Path
import shlex
import sys
import tempfile
import unittest

from tools.executor.exec_server import BackendCall
from tools.executor.native_executor_backend import NativeExecutorBackend
from tools.executor.native_runtime_acquisition import NativeRuntimeAcquisition, SessionExecServer
from tools.executor.native_runtime_startup import StartupManifest
from tools.executor.ordinary_uid_files import OrdinaryUidFilesBackend


@unittest.skipUnless(os.environ.get('CODEX_NATIVE_CONTROLLER') and os.environ.get('CODEX_NATIVE_TEST_HELPERS'),
                     'Requires the real built controller and native Linux helpers')
class NativeSharedProjectTests(unittest.IsolatedAsyncioTestCase):
    async def run_case(self, *, ordinary, selected):
        self.assertNotEqual(os.geteuid(), 0)
        with tempfile.TemporaryDirectory(prefix='codex-shared-project-', dir='/var/tmp') as temporary:
            parent = Path(temporary)
            workspace = parent/'private-projects'; workspace.mkdir(mode=0o700)
            shared = parent/'共享项目'; shared.mkdir(mode=0o700)
            alias = parent/'sdcard-project'; alias.symlink_to(shared, target_is_directory=True)
            home = parent/'home'; home.mkdir(mode=0o700)
            endpoint = parent/'endpoint'; endpoint.mkdir(mode=0o700)
            for path, model in ((workspace, 'private-project'), (shared, 'shared-project')):
                (path/'.codex').mkdir(mode=0o700)
                (path/'.codex/config.toml').write_text("model = '"+model+"'\n")
                (path/'.git').mkdir()
                (path/'.git/HEAD').write_text('ref: refs/heads/main\n')
            (home/'config.toml').write_text("model = 'user-model'\nsandbox_mode = 'danger-full-access'\n" +
                ''.join('[projects.'+json.dumps(str(p))+']\ntrust_level = "trusted"\n' for p in (workspace, shared, alias)))
            helpers = Path(os.environ['CODEX_NATIVE_TEST_HELPERS'])
            runtime = [('/usr', True), ('/lib', True), ('/lib64', True), ('/etc/ld.so.cache', False)]
            executables = {'bash': '/usr/bin/bash', '/usr/bin/bash': '/usr/bin/bash'}
            process_type = importlib.import_module('tools.executor.bionic-supervisor.processes').Processes
            def processes(runner, root, **options):
                return process_type(runner, root, runtime=runtime, executables=executables, **options)
            backend = NativeExecutorBackend(str(helpers/'native-files'), workspace,
                handle_helper=str(helpers/'native-file-handle'), process_runner=str(helpers/'runner'),
                process_factory=processes, guest_workspace=str(workspace), parent_environment={})
            if ordinary:
                direct_type = importlib.import_module('tools.executor.bionic-supervisor.direct_processes').DirectProcesses
                direct = direct_type(str(helpers/'direct-runner'), workspace, executables=executables,
                    files_backend=backend.files, parent_environment={'PATH':'/usr/bin:/bin'}, quarantine_owner=backend.processes)
                backend.install_ordinary_uid_profile(direct, OrdinaryUidFilesBackend(lock=backend.files.lock))
            server = SessionExecServer(backend, environment_info={
                'os':'linux', 'arch':'x86_64', 'cwd':workspace.as_uri(), 'userHomeDir':workspace.as_uri(),
                'shell':{'name':'bash','path':'/usr/bin/bash'}})
            owner = NativeRuntimeAcquisition(endpoint/'owner.sock', server, controller_uid=os.getuid())
            manifest = StartupManifest(endpoint/'startup.json', socket_path=endpoint/'owner.sock', workspace=workspace,
                shared_paths=[workspace, Path('/usr')], controller_roots=[home.as_uri(), Path('/usr').as_uri()],
                parent_environment={'PATH':'/usr/bin:/bin','HOME':str(workspace)}, directory_fd=owner.directory_fd)
            serving = asyncio.create_task(owner.run())
            proc = None
            error_path = parent/'stderr.log'
            try:
                env = dict(os.environ, HOME=str(home), CODEX_HOME=str(home),
                    CODEX_NATIVE_BOOTSTRAP=str(manifest.path), LANG='C.UTF-8')
                for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CHATGPT_ACCESS_TOKEN', 'OPENAI_BASE_URL'):
                    env.pop(key, None)
                env.pop('CODEX_NATIVE_PROJECT_ACCESS', None)
                if selected: env['CODEX_NATIVE_PROJECT_ACCESS'] = 'ordinary-uid'
                command = [*shlex.split(os.environ.get('CODEX_CONTROLLER_RUNNER','')),
                    os.environ['CODEX_NATIVE_CONTROLLER'], 'app-server']
                with error_path.open('wb') as errors:
                    proc = await asyncio.create_subprocess_exec(*command, cwd=home, env=env,
                        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=errors, limit=2*1024*1024)
                    if selected and not ordinary:
                        await asyncio.wait_for(proc.wait(), 45)
                        self.assertNotEqual(proc.returncode, 0)
                        self.assertIn('expected a JSON object', error_path.read_text())
                        return
                    sequence = 0
                    async def rpc(method, params):
                        nonlocal sequence
                        sequence += 1
                        proc.stdin.write((json.dumps({'id':sequence,'method':method,'params':params})+'\n').encode())
                        await proc.stdin.drain()
                        while True:
                            line = await asyncio.wait_for(proc.stdout.readline(), 45)
                            self.assertTrue(line, error_path.read_text()[-6000:])
                            result = json.loads(line)
                            if result.get('id') == sequence: return result
                    initialized = await rpc('initialize', {'clientInfo':{'name':'shared-project-regression','version':'1'},
                        'capabilities':{'experimentalApi':True}})
                    self.assertIn('result', initialized)
                    proc.stdin.write(b'{"method":"initialized","params":{}}\n'); await proc.stdin.drain()
                    result = await rpc('config/read', {'cwd':str(shared),'includeLayers':True})
                    if not selected:
                        self.assertIn('outside configuration discovery root', result['error']['message'])
                        return
                    self.assertNotIn('error', result, result)
                    self.assertEqual(result['result']['config']['model'], 'shared-project')
                    aliased = await rpc('config/read', {'cwd':str(alias),'includeLayers':True})
                    self.assertEqual(aliased['result']['config']['model'], 'shared-project')
                    private = await rpc('config/read', {'cwd':str(workspace),'includeLayers':True})
                    self.assertEqual(private['result']['config']['model'], 'private-project')
                    (shared/'.codex/config.toml').write_text("model = 'shared-refreshed'\n")
                    refreshed = await rpc('config/read', {'cwd':str(shared),'includeLayers':True})
                    self.assertEqual(refreshed['result']['config']['model'], 'shared-refreshed')
                    thread = await rpc('thread/start', {'cwd':str(shared), 'model':'gpt-6.1-sol', 'ephemeral':True})
                    self.assertNotIn('error', thread, thread)
                    self.assertEqual(thread['result']['cwd'], str(shared))
                    # Model execution uses the ordinary-UID profile's absent
                    # outer sandbox contract. Public command/exec is a separate
                    # human sandbox API; it must not be used as a substitute.
                    async def notice(*_): pass
                    number = 1000000
                    async def native(method, params):
                        nonlocal number
                        number += 1
                        return await backend.handle(BackendCall(server.session_id, number, method,
                            json.dumps(params).encode()), notice)
                    key = 'shared-project-regression'
                    started = await native('process/start', {'processId':key,
                        'argv':['bash','-c','pwd'], 'cwd':shared.as_uri(), 'env':{},
                        'envPolicy':{'inherit':'all','ignoreDefaultExcludes':False,
                            'exclude':[],'set':{},'includeOnly':[]}, 'tty':False,'pipeStdin':False})
                    self.assertEqual(started['sandboxType'], 'none')
                    cursor = 0
                    output = bytearray()
                    async def collect():
                        nonlocal cursor
                        while True:
                            result = await native('process/read', {'processId':key,'afterSeq':cursor,'waitMs':1000})
                            for chunk in result['chunks']:
                                if chunk['stream']=='stdout': output.extend(base64.b64decode(chunk['chunk'], validate=True))
                            self.assertLessEqual(len(output),65536)
                            cursor = result['nextSeq']-1
                            if result['closed']:
                                self.assertIsNone(result['failure'])
                                self.assertEqual(result['exitCode'],0)
                                return
                    await asyncio.wait_for(collect(),20)
                    self.assertEqual(output.decode().strip(),str(shared))
            except BaseException:
                print('Controller diagnostic:', error_path.read_text()[-6000:], file=sys.stderr)
                if serving.done() and not serving.cancelled():
                    print('Native owner diagnostic:', repr(serving.exception()), file=sys.stderr)
                raise
            finally:
                if proc is not None:
                    if proc.stdin is not None: proc.stdin.close()
                    try: await asyncio.wait_for(proc.wait(), 15)
                    except asyncio.TimeoutError:
                        proc.kill(); await proc.wait()
                if not serving.done(): serving.cancel()
                await asyncio.gather(serving, return_exceptions=True)
                await server.close()
                owner.close_endpoint()
                manifest.remove(); manifest.close()
                self.assertFalse(backend.processes.quarantined)

    async def test_ordinary_shared_project_config_refresh_thread_and_native_command(self):
        await self.run_case(ordinary=True, selected=True)

    async def test_default_keeps_private_discovery_boundary(self):
        await self.run_case(ordinary=True, selected=False)

    async def test_selection_cannot_enable_a_missing_native_profile(self):
        await self.run_case(ordinary=False, selected=True)


if __name__ == '__main__':
    unittest.main(verbosity=2)
