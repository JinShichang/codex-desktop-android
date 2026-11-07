import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('phone_profile', Path(__file__).with_name('codex_phone_profile.py'))
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)


class PhoneProfileTest(unittest.TestCase):
    def test_only_selected_native_phone_changes_configuration(self):
        for env in ({}, {'CODEX_PHONE_CLIENT_COMPAT': '1'}, {'CODEX_NATIVE_BOOTSTRAP': '/session'}):
            with mock.patch.object(PROFILE, 'write_official_config') as writer:
                self.assertEqual({'status': 'unselected'}, PROFILE.prepare(env))
                writer.assert_not_called()

    def test_declared_workspace_cannot_expand_to_home_or_parent(self):
        for path in ('/', '/home/codex', '/data/data/com.ai.codex/files',
                     '/data/data/com.ai.codex/files/projects/../secrets'):
            with self.assertRaises(ValueError):
                PROFILE.selected_workspace({'CODEX_PHONE_CLIENT_COMPAT': '1',
                    'CODEX_NATIVE_BOOTSTRAP': '/session', 'CODEX_NATIVE_WORKSPACE': path})

    def test_existing_native_subfolder_is_preserved_but_sibling_and_traversal_are_not(self):
        root = '/data/data/com.ai.codex/files/projects'
        for path in (root, root + '/custom'):
            self.assertTrue(PROFILE.inside_workspace(path, root))
        for path in (root + '-other', root + '/../secrets', '/home/codex/Documents/Codex', None):
            self.assertFalse(PROFILE.inside_workspace(path, root))

    def test_valid_existing_profile_does_not_start_another_server(self):
        with tempfile.TemporaryDirectory() as directory:
            config = Path(directory) / 'config.toml'
            config.write_text('[desktop]\nprojectlessWorkspaceRoot = "/native/projects/custom"\n')
            with mock.patch.object(PROFILE, 'selected_workspace', return_value='/native/projects'), \
                    mock.patch.object(PROFILE, 'write_official_config') as writer:
                self.assertEqual({'status': 'current'}, PROFILE.prepare({'HOME': directory, 'CODEX_HOME': directory}))
                writer.assert_not_called()


if __name__ == '__main__':
    unittest.main()
