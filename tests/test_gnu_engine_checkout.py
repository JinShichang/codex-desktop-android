"""A cached Cargo path cannot admit files outside the exported source snapshot."""
import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SPEC = importlib.util.spec_from_file_location(
    'gnu_engine_builder', Path(__file__).resolve().parents[1] / 'tools/executor/build-gnu-engine.py')
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class VerifiedCheckoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.snapshot = root / 'snapshot'
        self.checkout = root / 'checkout'
        for directory in (self.snapshot, self.checkout):
            directory.mkdir()
            (directory / 'input.rs').write_bytes(b'fn main() {}\n')
        (self.checkout / '.git').write_text('gitdir: /administrative/worktree\n')

    def verify(self, base=builder.BASE):
        with patch.object(builder, 'native_storage'), patch.object(builder, 'run', return_value=base):
            return builder.verified_checkout(self.checkout, self.snapshot)

    def test_identical_worktree_admitted_without_git_pointer_as_input(self):
        self.assertEqual(self.verify(), self.checkout.resolve())

    def test_changed_source_and_untracked_input_rejected(self):
        (self.checkout / 'input.rs').write_bytes(b'fn main() { panic!(); }\n')
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            self.verify()
        (self.checkout / 'input.rs').write_bytes((self.snapshot / 'input.rs').read_bytes())
        (self.checkout / 'ignored-build-hook').write_bytes(b'unrecorded')
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            self.verify()

    def test_wrong_upstream_and_missing_worktree_pointer_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'wrong upstream'):
            self.verify('0' * 40)
        (self.checkout / '.git').unlink()
        with self.assertRaisesRegex(RuntimeError, 'linked Git worktree'):
            self.verify()

    def test_executable_mode_changes_rejected(self):
        if __import__('os').name == 'nt':
            self.skipTest('POSIX executable mode requires Linux')
        (self.checkout / 'input.rs').chmod(0o755)
        with self.assertRaisesRegex(RuntimeError, 'differs'):
            self.verify()


if __name__ == '__main__':
    unittest.main()
