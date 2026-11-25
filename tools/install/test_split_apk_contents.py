"""Offline split-package contract fixtures, separate from native/device validation."""
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location('apk_contents', Path(__file__).with_name('verify-apk-contents.py'))
CHECK = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECK)


class SplitApkContentsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.apk = Path(self.temporary.name) / 'fixture.apk'
        self.files = {'lib/arm64-v8a/' + name: b'fixture' for name in
                      CHECK.RUNTIME | {'libcodex-device-files.so', 'libcodex_tools_launcher.so'}}
        for name in ('codex-executor-deployment.json', 'codex-executor-manifest.json',
                     'codex-executor-evidence.json', 'codex-executor-qualification.json',
                     'codex-app-launch-build.json', 'codex-python-runtime.json',
                     'bionic-python/lib/python3.14/os.py', 'codex-tools/install-workspace-provider.py'):
            self.files['assets/' + name] = b'fixture'
        self.files['res/xml-v33/phone_accessibility_service.xml'] = b'fixture'
        self.files['classes.dex'] = b''.join((b'Lcom/ai/codex/LiveNotifications;',
                b'Lcom/ai/codex/phone/PhoneControl;', b'Lcom/termux/x11/CodexRuntimeService;'))
        self.put('codex-executor-deployment.json', {'schema': 'codex.native.deployment.v2',
                'launchOrigin': 'android-app', 'packageName': 'com.ai.codex'})
        self.put('gnu-engine/manifest.json', {'schema': 'codex.gnu-engine.payload.v1',
            'target': 'aarch64-unknown-linux-gnu', 'version': '0.171.0',
            'files': [{'name': name, 'bytes': 20, 'sha256': '0' * 64}
                      for name in ('codex-native', 'codex-code-mode-host')]})
        inventory = b'{"format":"codex.phone-image.v1","files":[]}'
        self.files['assets/phone-runtime/inventory.json'] = inventory
        self.put('phone-runtime/release.json', {'format': 'codex.phone-image.v1',
            'archive': 'codex-phone-rootfs.tar.gz', 'accountIncluded': False, 'keyringIncluded': False,
            'inventorySha256': hashlib.sha256(inventory).hexdigest(), 'inventoryBytes': len(inventory),
            'client': {'version': '26.1117.31558'}})
        self.put('desktop-client/manifest.json', {'schema': 'codex.desktop.payload.v1',
            'architecture': 'arm64', 'version': '26.1117.31558'})

    def put(self, name, value):
        self.files['assets/' + name] = json.dumps(value).encode()

    def verify(self, embedded_engine=False):
        with zipfile.ZipFile(self.apk, 'w') as archive:
            for name, data in self.files.items():
                archive.writestr(name, data)
        return CHECK.verify_native_update(self.apk, external_environment=True, embedded_engine=embedded_engine)

    def embed_engine(self):
        header = b'\x7fELF\x02\x01\x01' + bytes(11) + (183).to_bytes(2, 'little')
        files = []
        for name in ('codex-native', 'codex-code-mode-host'):
            data = header + name.encode()
            self.files['assets/gnu-engine/' + name] = data
            files.append({'name': name, 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()})
        self.put('gnu-engine/manifest.json', {'schema': 'codex.gnu-engine.payload.v1',
            'target': 'aarch64-unknown-linux-gnu', 'version': '0.171.0', 'files': files})

    def test_explicit_engine_update_reuses_external_environment(self):
        self.embed_engine()
        self.assertTrue(self.verify(embedded_engine=True)['gnuEngineEmbedded'])

    def test_explicit_engine_update_still_requires_matching_complete_pair(self):
        self.embed_engine()
        self.files['assets/gnu-engine/codex-native'] += b'tampered'
        with self.assertRaisesRegex(ValueError, 'differs from its manifest'):
            self.verify(embedded_engine=True)
        self.embed_engine()
        del self.files['assets/gnu-engine/codex-code-mode-host']
        with self.assertRaisesRegex(ValueError, 'pair is incomplete'):
            self.verify(embedded_engine=True)

    def test_accepts_metadata_only_split_contract(self):
        self.assertEqual('debug-split-environment', self.verify()['variant'])

    def test_rejects_embedded_engine(self):
        self.files['assets/gnu-engine/codex-native'] = b'unexpected'
        with self.assertRaisesRegex(ValueError, 'embeds GNU'):
            self.verify()

    def test_rejects_tampered_inventory(self):
        self.files['assets/phone-runtime/inventory.json'] += b' '
        with self.assertRaisesRegex(ValueError, 'release descriptor'):
            self.verify()

    def test_rejects_desktop_environment_version_mismatch(self):
        self.put('desktop-client/manifest.json', {'schema': 'codex.desktop.payload.v1',
            'architecture': 'arm64', 'version': 'wrong'})
        with self.assertRaisesRegex(ValueError, 'desktop version'):
            self.verify()

    def test_rejects_full_archive_inside_split_apk(self):
        self.files['assets/phone-runtime/codex-phone-rootfs.tgz'] = b'unexpected'
        with self.assertRaisesRegex(ValueError, 'full environment archive'):
            self.verify()

    def image_payloads(self):
        release = json.loads(self.files['assets/phone-runtime/release.json'])
        image = b'ZIP contract fixture, not a runnable phone image'
        release.update(spec={'compressedBytes': len(image)},
                clientPayload=json.loads(self.files['assets/desktop-client/manifest.json']),
                enginePayload=json.loads(self.files['assets/gnu-engine/manifest.json']))
        self.put('phone-runtime/release.json', release)
        self.files['assets/phone-runtime/codex-phone-rootfs.tgz'] = image
        self.files['classes.dex'] += b'Lcom/ai/codex/install/EmbeddedRuntimePayloadInstaller;'

    def verify_image(self):
        with zipfile.ZipFile(self.apk, 'w') as archive:
            for name, data in self.files.items():
                archive.writestr(name, data)
        return CHECK.verify_native_update(self.apk, image_payloads=True)

    def test_full_image_reuses_payloads_without_duplicate_assets(self):
        self.image_payloads()
        result = self.verify_image()
        self.assertEqual('debug-full-image-payloads', result['variant'])
        self.assertTrue(result['payloadsFromPhoneImage'])
        self.assertFalse(result['gnuEngineEmbedded'])

    def test_full_image_rejects_duplicate_payloads(self):
        self.image_payloads()
        for name in ('assets/desktop-client/client.tgz', 'assets/gnu-engine/codex-native'):
            self.files[name] = b'duplicate'
            with self.assertRaises(ValueError):
                self.verify_image()
            del self.files[name]

    def test_full_image_requires_matching_descriptors_and_update_installer(self):
        self.image_payloads()
        release = json.loads(self.files['assets/phone-runtime/release.json'])
        release['enginePayload']['version'] = 'wrong'
        self.put('phone-runtime/release.json', release)
        with self.assertRaisesRegex(ValueError, 'matching image'):
            self.verify_image()
        self.image_payloads()
        self.files['classes.dex'] = self.files['classes.dex'].replace(
                b'Lcom/ai/codex/install/EmbeddedRuntimePayloadInstaller;', b'')
        with self.assertRaisesRegex(ValueError, 'update installer'):
            self.verify_image()

    def test_full_image_rejects_the_release_asset_size_limit(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        self.image_payloads()
        with patch.object(Path, 'stat', return_value=SimpleNamespace(st_size=2**31)):
            with self.assertRaisesRegex(ValueError, '2 GiB'):
                self.verify_image()


if __name__ == '__main__':
    unittest.main()
