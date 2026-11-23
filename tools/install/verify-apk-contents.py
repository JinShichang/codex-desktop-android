"""Check development/production separation in an actual built APK, offline.

This checks packaged contents, not signing, provenance, device behavior or
release qualification. Never install the unsigned release-check artifact.
"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

RUNTIME = {"libXlorie.so", "libandroid-shmem.so", "libcodex-install.so",
           "libproot-loader.so", "libproot-loader32.so", "libproot.so", "libtalloc.so"}
DEBUG_CLASSES = (b"RootfsProbeService", b"ProotStorageProbeService", b"NativeRunnerProbeService", b"GuestAccountProbeService", b"InactivePreparationProbeService",
                 b"NativeFilesRpcProbeService",
                 b"NativePrivateExecProbeService",
                 b"NativeManagedProcessProbeService", b"NativeProbeFiles",
                 b"NativeHttpsAcquisitionProbeService",
                 b"NativeProcessRpcProbeService",
                 b"NativeExecutorProbeService",
                 b"NativeGnuProjectProbeService",
                 b"NativeGnuManagedProbeService",
                 b"NativeGnuExecutorService",
                 b"CombinedPreparationProbeService", b"CombinedPreparationFixture",
                 b"CodexProbeService", b"LandlockProbeReceiver")


def verify_native_update(apk, external_environment=False, embedded_engine=False):
    """Current app-origin executor update, separate from legacy fixture APKs.

    The candidate builder also runs verify-production-apk.py for every native
    digest, Python data file and source import closure. This function checks
    the surrounding runtime, paired GNU engine and compiled application classes.
    """
    with apk.open('rb') as source:
        digest = hashlib.file_digest(source, 'sha256').hexdigest()
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('Duplicate APK entries')
        required = {'lib/arm64-v8a/' + name for name in RUNTIME | {'libcodex-device-files.so', 'libcodex_tools_launcher.so'}}
        required |= {'assets/' + name for name in ('codex-executor-deployment.json', 'codex-executor-manifest.json',
            'codex-executor-evidence.json', 'codex-executor-qualification.json', 'codex-app-launch-build.json',
            'codex-python-runtime.json', 'bionic-python/lib/python3.14/os.py',
            'codex-tools/install-workspace-provider.py', 'gnu-engine/manifest.json')}
        required.add('res/xml-v33/phone_accessibility_service.xml')
        if not required.issubset(names):
            raise ValueError('Native update runtime assets are incomplete: ' + str(sorted(required - set(names))))
        deployment = json.loads(archive.read('assets/codex-executor-deployment.json'))
        if (deployment.get('schema') != 'codex.native.deployment.v2'
                or deployment.get('launchOrigin') != 'android-app' or deployment.get('packageName') != 'com.ai.codex'):
            raise ValueError('Native update requires the application-origin executor contract')
        manifest = json.loads(archive.read('assets/gnu-engine/manifest.json'))
        rows = manifest.get('files', [])
        if (manifest.get('schema') != 'codex.gnu-engine.payload.v1'
                or manifest.get('target') != 'aarch64-unknown-linux-gnu' or len(rows) != 2
                or {row.get('name') for row in rows} != {'codex-native', 'codex-code-mode-host'}):
            raise ValueError('Native update GNU engine pair is incomplete')
        expected_engine = {'assets/gnu-engine/manifest.json'}
        for row in rows:
            name = 'assets/gnu-engine/' + row['name']
            if external_environment and not embedded_engine:
                if name in names:
                    raise ValueError('Split APK embeds GNU engine bytes')
                if (not isinstance(row.get('bytes'), int) or row['bytes'] < 20
                        or not isinstance(row.get('sha256'), str) or len(row['sha256']) != 64
                        or any(c not in '0123456789abcdef' for c in row['sha256'])):
                    raise ValueError('Split GNU engine descriptor is invalid')
                continue
            expected_engine.add(name)
            if name not in names:
                raise ValueError('Embedded GNU engine pair is incomplete: ' + row['name'])
            hasher, size, header = hashlib.sha256(), 0, b''
            with archive.open(name) as stream:
                while block := stream.read(1024 * 1024):
                    if not header:
                        header = block[:20]
                    hasher.update(block)
                    size += len(block)
            if (len(header) != 20 or header[:7] != b'\x7fELF\x02\x01\x01'
                    or int.from_bytes(header[18:20], 'little') != 183):
                raise ValueError('Native update GNU engine is not ARM64 ELF: ' + row['name'])
            if size != row.get('bytes') or hasher.hexdigest() != row.get('sha256'):
                raise ValueError('Native update GNU engine differs from its manifest: ' + row['name'])
        if {n for n in names if n.startswith('assets/gnu-engine/') and not n.endswith('/')} != expected_engine:
            raise ValueError('Unexpected GNU engine asset')
        if external_environment:
            if any(name.endswith(('.tgz', '.tar.gz')) and name.startswith(('assets/desktop-client/', 'assets/phone-runtime/')) for name in names):
                raise ValueError('Split APK embeds a full environment archive')
            release = json.loads(archive.read('assets/phone-runtime/release.json'))
            inventory = archive.read('assets/phone-runtime/inventory.json')
            if (release.get('format') != 'codex.phone-image.v1' or release.get('archive') != 'codex-phone-rootfs.tar.gz'
                    or release.get('accountIncluded') is not False or release.get('keyringIncluded') is not False
                    or release.get('inventorySha256') != hashlib.sha256(inventory).hexdigest()
                    or release.get('inventoryBytes') != len(inventory)):
                raise ValueError('Split environment release descriptor differs')
            desktop = json.loads(archive.read('assets/desktop-client/manifest.json'))
            if (desktop.get('schema') != 'codex.desktop.payload.v1' or desktop.get('architecture') != 'arm64'
                    or desktop.get('version') != release.get('client', {}).get('version')):
                raise ValueError('Split environment desktop version differs')
        dex = b''.join(archive.read(name) for name in names if name.endswith('.dex'))
        for name in (b'Lcom/ai/codex/LiveNotifications;', b'Lcom/ai/codex/phone/PhoneControl;',
                     b'Lcom/termux/x11/CodexRuntimeService;'):
            if name not in dex:
                raise ValueError('Native update application class is missing: ' + name.decode())
    return {'apk_sha256': digest, 'variant': 'debug-split-environment' if external_environment else 'debug-native-update', 'native_update_contents': 'PASS',
            'gnuEngineVersion': manifest.get('version'), 'gnuEngineEmbedded': not external_environment or embedded_engine,
            'legacyDiagnosticFixturesQualified': False,
            'deviceQualified': False, 'limit': 'Current native update contents; legacy diagnostic fixtures and phone behavior are separate'}


def verify(apk, debug):
    with apk.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
        source.seek(0)
        with zipfile.ZipFile(source) as archive:
            names = archive.namelist()
            if len(names) != len(set(names)):
                raise ValueError("Duplicate APK entries")
            libraries = {name for name in names if name.startswith("lib/") and not name.endswith("/")}
            required = {"lib/arm64-v8a/" + name for name in RUNTIME}
            if not required.issubset(libraries) or (not debug and libraries != required):
                raise ValueError("APK native runtime differs: " + str(sorted(libraries ^ required)))
            dex = b"".join(archive.read(name) for name in names if name.endswith(".dex"))
            for descriptor in DEBUG_CLASSES:
                if (descriptor in dex) != debug:
                    raise ValueError("Wrong diagnostic class separation: " + descriptor.decode())
            file_rpc_assets = {name for name in names if name.startswith("assets/native-files-rpc/") and not name.endswith("/")}
            expected_assets = {"assets/native-files-rpc/" + name for name in (
                "tools/executor/exec_server.py", "tools/executor/native_files.py",
                "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
                "tools/executor/native_files_server.py", "tools/executor/native_files_rpc_fixture.py")}
            if file_rpc_assets != (expected_assets if debug else set()):
                raise ValueError("Wrong native file RPC source asset separation")
            private_assets = {name for name in names if name.startswith("assets/private-exec-probe/") and not name.endswith("/")}
            expected_private = {"assets/private-exec-probe/" + name for name in (
                "tools/executor/exec_server.py", "tools/executor/native_files.py",
                "tools/executor/policy_intent.py", "tools/policy/managed_policy.py",
                "tools/executor/native_files_rpc_fixture.py", "tools/executor/private_exec_broker.py",
                "tools/executor/native_file_streams.py",
                "tools/executor/native_runtime_startup.py", "tools/executor/native_path_uri.py",
                "tools/executor/native_session_recovery.py",
                "tools/executor/private_exec_fixture.py")}
            if private_assets != (expected_private if debug else set()):
                raise ValueError("Wrong private executor probe asset separation")
            if ("lib/arm64-v8a/libcodex-exec-bridge.so" in libraries) != debug:
                raise ValueError("Wrong GNU bridge diagnostic separation")
            if ("lib/arm64-v8a/libcodex_file_handle.so" in libraries) != debug:
                raise ValueError("Wrong native streaming helper diagnostic separation")
            managed_assets = {name for name in names if name.startswith('assets/managed-process-probe/') and not name.endswith('/')}
            expected_managed = {'assets/managed-process-probe/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
                'tools/executor/native-managed-test.py', 'tools/executor/native_managed_android_fixture.py')}
            if managed_assets != (expected_managed if debug else set()):
                raise ValueError('Wrong native managed process probe asset separation')
            for name in ('libcodex-native-managed-runner.so', 'libcodex-native-managed-fixture.so'):
                if ('lib/arm64-v8a/' + name in libraries) != debug:
                    raise ValueError('Wrong managed process diagnostic native separation')
            process_assets = {name for name in names if name.startswith('assets/process-rpc-probe/') and not name.endswith('/')}
            expected_process = {'assets/process-rpc-probe/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
                'tools/executor/native_processes.py', 'tools/executor/test_native_processes_live.py',
                'tools/executor/native_environment.py', 'tools/executor/native_environment_unicode.py',
                'tools/executor/native_processes_android_fixture.py')}
            if process_assets != (expected_process if debug else set()):
                raise ValueError('Wrong native process lifecycle probe asset separation')
            for name in ('libcodex-native-process-runner.so', 'libcodex-native-process-fixture.so'):
                if ('lib/arm64-v8a/' + name in libraries) != debug:
                    raise ValueError('Wrong native process lifecycle diagnostic separation')
            composite_assets = {name for name in names if name.startswith('assets/native-executor-probe/') and not name.endswith('/')}
            expected_composite = {'assets/native-executor-probe/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
                'tools/executor/native_processes.py', 'tools/executor/native_file_streams.py',
                'tools/executor/native_environment.py', 'tools/executor/native_environment_unicode.py',
                'tools/executor/native_executor_backend.py', 'tools/executor/private_exec_broker.py',
                'tools/executor/native_runtime_startup.py', 'tools/executor/native_path_uri.py',
                'tools/executor/native_session_recovery.py',
                'tools/executor/test_native_processes_live.py', 'tools/executor/test_native_executor_transport.py',
                'tools/executor/native_executor_android_fixture.py')}
            if composite_assets != (expected_composite if debug else set()):
                raise ValueError('Wrong native composite executor asset separation')
            android_python = {name for name in names if name.startswith("assets/native-python/") and not name.endswith("/")}
            gnu_managed_assets = {name for name in names if name.startswith('assets/gnu-managed-probe/') and not name.endswith('/')}
            expected_gnu_managed = {'assets/gnu-managed-probe/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_files_rpc_fixture.py', 'tools/executor/native_process_policy.py',
                'tools/executor/native_processes.py', 'tools/executor/native_environment.py',
                'tools/executor/native_environment_unicode.py',
                'tools/executor/gnu-runtime/gnu_process_adapter.py',
                'tools/executor/gnu-runtime/gnu_runtime_capacity.py',
                'tools/executor/gnu-runtime/gnu_runtime_address.py',
                'tools/executor/gnu-runtime/test_gnu_process_adapter.py',
                'tools/executor/gnu-runtime/managed_android_fixture.py')}
            if gnu_managed_assets != (expected_gnu_managed if debug else set()):
                raise ValueError('Wrong GNU managed process source separation')
            gnu_executor_assets = {name for name in names if name.startswith('assets/gnu-executor/') and not name.endswith('/')}
            expected_gnu_executor = {'assets/gnu-executor/' + name for name in (
                'tools/executor/exec_server.py', 'tools/executor/native_files.py',
                'tools/executor/policy_intent.py', 'tools/policy/managed_policy.py',
                'tools/executor/native_process_policy.py', 'tools/executor/native_processes.py',
                'tools/executor/native_file_streams.py', 'tools/executor/native_environment.py',
                'tools/executor/native_environment_unicode.py', 'tools/executor/native_executor_backend.py',
                'tools/executor/private_exec_broker.py', 'tools/executor/gnu-runtime/gnu_process_adapter.py',
                'tools/executor/native_runtime_startup.py', 'tools/executor/native_path_uri.py',
                'tools/executor/native_session_recovery.py',
                'tools/executor/gnu-runtime/gnu_runtime_capacity.py',
                'tools/executor/gnu-runtime/gnu_runtime_address.py',
                'tools/executor/gnu-runtime/gnu_executor_broker.py')}
            if gnu_executor_assets != (expected_gnu_executor if debug else set()):
                raise ValueError('Wrong GNU executor integration source separation')
            for name in ('libcodex-gnu-managed.so', 'libcodex-strict-proot.so', 'libcodex-gnu-project.so'):
                if ('lib/arm64-v8a/' + name in libraries) != debug:
                    raise ValueError('Wrong native GNU diagnostic separation: ' + name)
            python_notices = {name for name in names if name.startswith("assets/native-python-notices/") and not name.endswith("/")}
            python_libs = {"lib/arm64-v8a/" + name for name in (
                "libcodex_python.so", "libpython3.14.so", "libcrypto_python.so", "libssl_python.so", "libsqlite3_python.so")}
            if debug:
                if (not python_libs.issubset(libraries)
                        or "assets/native-python-notices/sources.json" not in python_notices
                        or "assets/native-python/lib/python3.14/os.py" not in android_python
                        or "assets/native-python/lib/python3.14/lib-dynload/_asyncio.cpython-314-aarch64-linux-android.so" not in android_python):
                    raise ValueError("Native Android Python diagnostic inputs are incomplete")
            elif android_python or python_notices or libraries & python_libs:
                raise ValueError("Native Android Python diagnostic leaked into release")
    return {"apk_sha256": digest, "variant": "debug" if debug else "release",
            "native_libraries": len(libraries), "diagnostic_separation": "PASS",
            "limit": "Package contents only, not a binary release qualification"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("apk", type=Path)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--native-update", action="store_true", help="Current application-origin update contract; does not claim legacy native diagnostic fixtures")
    parser.add_argument('--external-environment', action='store_true', help='Verify metadata-only payloads and the separate full environment contract')
    parser.add_argument('--embedded-engine', action='store_true', help='With the separate environment, verify an embedded matched GNU engine update pair')
    args = parser.parse_args()
    if args.native_update and not args.debug:
        parser.error('--native-update currently selects the debug update variant')
    if args.external_environment and not args.native_update:
        parser.error('--external-environment requires --native-update')
    if args.embedded_engine and not args.external_environment:
        parser.error('--embedded-engine requires --external-environment')
    print(json.dumps(verify_native_update(args.apk, args.external_environment, args.embedded_engine) if args.native_update else verify(args.apk, args.debug), indent=2))
