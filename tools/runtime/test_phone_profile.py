import importlib.util
import json
from pathlib import Path
import tempfile
import tomllib
import unittest
from unittest import mock

SPEC = importlib.util.spec_from_file_location('phone_profile', Path(__file__).with_name('codex_phone_profile.py'))
PROFILE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROFILE)

MCP_SPEC = importlib.util.spec_from_file_location('install_phone_mcp', Path(__file__).with_name('install_phone_mcp.py'))
MCP = importlib.util.module_from_spec(MCP_SPEC)
with mock.patch.dict('sys.modules', {'codex_phone_profile': PROFILE}):
    MCP_SPEC.loader.exec_module(MCP)


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


class AndroidMcpRegistrationTest(unittest.TestCase):
    def test_device_and_phone_registered_together_without_touching_other_servers(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            config = home / 'config.toml'
            config.write_text('model = "example"\n[mcp_servers.node_repl]\ncommand = "node"\n')
            skill = home / 'asset.md'
            skill.write_text('# Phone skill\n')

            def write_servers(_, *, env, edits):
                with config.open('a', encoding='utf-8') as output:
                    for edit in edits:
                        output.write(f"\n[{edit['keyPath']}]\n")
                        for key, value in edit['value'].items():
                            output.write(f'{key} = {json.dumps(value)}\n')

            env = {'HOME': directory, 'CODEX_HOME': directory}
            with mock.patch.object(MCP, 'SKILL', str(skill)), \
                    mock.patch.object(MCP, 'write_official_config', side_effect=write_servers) as writer:
                MCP.prepare(env)
                MCP.prepare(env)
                writer.assert_called_once()
            installed = tomllib.loads(config.read_text())
            self.assertEqual('example', installed['model'])
            self.assertEqual({'command': 'node'}, installed['mcp_servers']['node_repl'])
            self.assertEqual(MCP.SERVER, installed['mcp_servers']['phone'])
            device = installed['mcp_servers']['codex_android']
            self.assertEqual('/usr/bin/python3', device['command'])
            self.assertEqual(str(MCP.SHARE / MCP.DEVICE_SCRIPT), device['args'][2])
            self.assertEqual(str(MCP.SHARE / 'android-bridge.json'), device['args'][3])
            self.assertGreater(device['tool_timeout_sec'], 150)


if __name__ == '__main__':
    unittest.main()
