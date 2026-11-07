import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).with_name("codex_agent_context.py")
SPEC = importlib.util.spec_from_file_location("context", SOURCE)
context = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(context)
MANIFEST = Path(__file__).resolve().parents[2] / "config/agent-context/codex.v1.json"


class ContextTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="codex-context-", dir=os.environ.get("CODEX_TEST_TMPDIR", "/var/tmp"))
        self.root = Path(self.temporary.name)
        (self.root / "etc").mkdir()
        (self.root / "etc/codex-user").write_text("codex\n")
        (self.root / "etc/passwd").write_text("root:x:0:0::/root:/bin/bash\ncodex:x:10410:10410::/home/codex:/bin/bash\n")
        (self.root / "etc/group").write_text("root:x:0:\ncodex:x:10410:\n")
        self.home = self.root / "home/codex"
        self.home.mkdir(parents=True)

    def tearDown(self):
        self.temporary.cleanup()

    def sync(self, **options):
        return context.synchronize(self.root, MANIFEST, **options)

    def test_metadata_does_not_create_or_inject_agents(self):
        result = self.sync()
        self.assertFalse(result['automaticInstructionInjection'])
        self.assertFalse((self.home / '.codex/AGENTS.md').exists())
        data = json.loads((self.root / result['manifestGuestFile'].lstrip('/')).read_bytes())
        self.assertEqual(data['guestBinding']['uid'], 10410)
        self.assertEqual(self.sync(check=True), result)

    def test_one_time_clear_includes_override_and_preserves_later_preferences(self):
        codex = self.home / '.codex'
        codex.mkdir()
        for name in ('AGENTS.md', 'AGENTS.override.md'):
            (codex / name).write_text('Old restrictions')
        self.sync(clear_global_instructions_once=True)
        for name in ('AGENTS.md', 'AGENTS.override.md'):
            self.assertEqual((codex / name).read_bytes(), b'')
        agents = codex / 'AGENTS.md'
        agents.write_text('My new preferences')
        inode = agents.stat().st_ino
        self.sync(clear_global_instructions_once=True)
        self.sync(check=True, clear_global_instructions_once=True)
        self.assertEqual(agents.read_text(), 'My new preferences')
        self.assertEqual(agents.stat().st_ino, inode)

    def test_plain_sync_preserves_existing_instructions(self):
        codex = self.home / '.codex'
        codex.mkdir()
        path = codex / 'AGENTS.md'
        path.write_text('User instructions')
        self.sync()
        self.assertEqual(path.read_text(), 'User instructions')

    def test_clear_validates_both_targets_before_modifying_either(self):
        codex = self.home / '.codex'
        codex.mkdir()
        external = self.root / 'outside'
        external.write_bytes(b'outside')
        agents = codex / 'AGENTS.md'
        agents.write_bytes(b'original')
        override = codex / 'AGENTS.override.md'
        override.symlink_to(external)
        with self.assertRaises((ValueError, OSError)):
            self.sync(clear_global_instructions_once=True)
        self.assertEqual(agents.read_bytes(), b'original')
        self.assertEqual(external.read_bytes(), b'outside')
        override.unlink()
        os.link(external, override)
        with self.assertRaises(ValueError):
            self.sync(clear_global_instructions_once=True)
        self.assertEqual(agents.read_bytes(), b'original')

    def test_explicit_codex_home_does_not_modify_default_home(self):
        custom = self.home / 'custom'
        custom.mkdir()
        (custom / 'config.toml').write_text('model = "unchanged"')
        result = self.sync(codex_home='/home/codex/custom', clear_global_instructions_once=True)
        self.assertEqual((custom / 'AGENTS.md').read_bytes(), b'')
        self.assertFalse((self.home / '.codex').exists())
        self.assertEqual((custom / 'config.toml').read_text(), 'model = "unchanged"')

    def test_bad_account_and_tampered_migration_marker_fail(self):
        self.sync(clear_global_instructions_once=True)
        marker = self.home / '.codex/codex/global-instructions-cleared-v2.json'
        marker.write_text('{}')
        with self.assertRaises(ValueError):
            self.sync(clear_global_instructions_once=True)
        (self.root / 'etc/codex-user').write_text('root\n')
        with self.assertRaises(ValueError):
            self.sync()

    def test_manifest_json_duplicates_and_capability_promotion_are_rejected(self):
        source = self.root / "bad.json"
        source.write_text('{"schema":1,"schema":2}')
        with self.assertRaises(ValueError):
            context.manifest(source)
        data = json.loads(MANIFEST.read_bytes())
        data["capabilities"][0]["status"] = "all-android-access"
        source.write_bytes(context.canonical(data))
        with self.assertRaises(ValueError):
            context.manifest(source)


if __name__ == "__main__":
    unittest.main(verbosity=2)
