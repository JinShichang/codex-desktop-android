"""Host regression tests; fake PRoot processes do not validate Android kernels."""
import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

if os.name == "posix":
    SPEC = importlib.util.spec_from_file_location("proot_compat", Path(__file__).with_name("proot_compat.py"))
    compat = importlib.util.module_from_spec(SPEC)
    SPEC.loader.exec_module(compat)


@unittest.skipUnless(os.name == "posix", "The PRoot process adapter requires a Linux/Android host")
class ProotCompatibilityTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.executable = self.base / "libproot.so"
        self.executable.write_text("fixture")
        self.root = self.base / "root"
        self.root.mkdir()
        self.args = [str(self.executable), "--kill-on-exit", "-r", str(self.root),
                     "-w", "/", "/usr/bin/env", "-i", "SECRET=do-not-copy", "/user-task", "do-not-execute"]
        self.environment = dict(os.environ, PROOT_NO_SECCOMP="1")
        self.calls = []

    def tearDown(self):
        self.temporary.cleanup()

    def runner(self, results):
        def run(args, env):
            self.calls.append((list(args), dict(env)))
            return results[len(self.calls) - 1]
        return run

    def select(self, results, platform="rom-one"):
        return compat.configure(self.args, self.environment, self.base, platform, self.runner(results))

    def test_supported_keeps_acceleration_and_does_not_probe_user_command(self):
        self.assertTrue(self.select([(True, True)]))
        self.assertNotIn(compat.NO_SECCOMP, self.environment)
        args, env = self.calls[0]
        self.assertNotIn(compat.NO_SECCOMP, env)
        self.assertNotIn("/user-task", args)
        self.assertNotIn("SECRET=do-not-copy", args)
        self.assertNotIn("do-not-execute", args)
        self.assertIn("--kill-on-exit", args)

    def test_failed_nested_exec_falls_back_only_after_baseline_passes(self):
        self.assertFalse(self.select([(False, True), (True, False)]))
        self.assertEqual("1", self.environment[compat.NO_SECCOMP])
        self.assertEqual("1", self.calls[1][1][compat.NO_SECCOMP])

    def test_exit_zero_without_acceleration_banner_is_not_reported_supported(self):
        self.assertFalse(self.select([(True, False), (True, False)]))
        self.assertEqual(2, len(self.calls))

    def test_both_modes_failing_do_not_cache_or_execute_task(self):
        original = dict(self.environment)
        with self.assertRaisesRegex(OSError, "both accelerated and compatible"):
            self.select([(False, False), (False, False)])
        self.assertEqual(original, self.environment)
        self.assertEqual([], list((self.base / ".proot-compat").glob("*.txt")))

    def test_persistent_result_is_reused_without_another_probe(self):
        self.select([(False, False), (True, False)])
        self.calls.clear()
        self.assertFalse(self.select([]))
        self.assertEqual([], self.calls)

    def test_new_rom_or_native_library_or_rootfs_is_probed_again(self):
        self.select([(True, True)])
        self.calls.clear()
        self.select([(True, True)], platform="rom-two")
        self.assertEqual(1, len(self.calls))
        self.calls.clear()
        self.executable.write_text("changed native fixture size")
        self.select([(True, True)])
        self.assertEqual(1, len(self.calls))
        self.calls.clear()
        other = self.base / "other-root"
        other.mkdir()
        self.args[self.args.index("-r") + 1] = str(other)
        self.select([(True, True)])
        self.assertEqual(1, len(self.calls))

    def test_corrupt_record_is_reprobed(self):
        self.select([(True, True)])
        next((self.base / ".proot-compat").glob("*.txt")).write_text("partial record")
        self.calls.clear()
        self.assertTrue(self.select([(True, True)]))
        self.assertEqual(1, len(self.calls))

    def test_shared_or_symlinked_cache_directory_is_rejected(self):
        destination = self.base / "other"
        destination.mkdir()
        (self.base / ".proot-compat").symlink_to(destination, target_is_directory=True)
        with self.assertRaisesRegex(OSError, "cache directory"):
            self.select([(True, True)])
        self.assertEqual([], self.calls)

    def test_probe_checks_exit_code_marker_and_acceleration_separately(self):
        def run(program):
            return compat.run_probe([sys.executable, "-c", program], os.environ, timeout=2)
        self.assertEqual((True, True), run("print('" + compat.ACCELERATION.decode() + "'); print('" + compat.MARKER.decode() + "')"))
        self.assertEqual((False, True), run("print('" + compat.ACCELERATION.decode() + "')"))
        self.assertEqual((False, False), run("print('" + compat.MARKER.decode() + "'); raise SystemExit(17)"))

    def test_hanging_or_flooding_probe_is_bounded(self):
        start = time.monotonic()
        self.assertEqual((False, False), compat.run_probe([sys.executable, "-c", "import time; time.sleep(30)"], os.environ, 0.1))
        self.assertLess(time.monotonic() - start, 3)
        self.assertEqual((False, False), compat.run_probe([sys.executable, "-c", "print('x'*20000)"], os.environ, 2))

    def test_real_nested_shell_command_outputs_marker(self):
        child = subprocess.run(["/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "/bin/sh", "-c", compat.SCRIPT],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=3)
        self.assertEqual(0, child.returncode, child.stderr)
        self.assertIn(compat.MARKER, child.stdout)

    def test_apk_isolated_python_entrypoint_loads_its_sibling_policy(self):
        # -I must remain enabled; normal sibling imports would fail here.
        self.executable.write_text("#!/bin/sh\nprintf 'ptrace acceleration (seccomp mode 2) enabled\\n'\n"
                                   "while [ \"$1\" != /usr/bin/env ]; do shift; done\nexec \"$@\"\n")
        self.executable.chmod(0o700)
        code = """import json,os,runpy,sys
from pathlib import Path
namespace=runpy.run_path(sys.argv[1]); scope=namespace['main'].__globals__
arguments=json.loads(sys.argv[2]); files=Path(sys.argv[3])
class Installation:
    def __init__(self, unused): self.files=files; self.proot_platform='host-test'
    def invocation(self, *unused): return arguments, dict(os.environ)
scope['Installation']=Installation; scope['read_json']=lambda *unused: {}
def execute(executable,args,env):
    print('EXEC_SELECTED_ACCELERATED' if 'PROOT_NO_SECCOMP' not in env else 'EXEC_SELECTED_COMPATIBLE')
    raise SystemExit(0)
scope['os'].execve=execute
sys.argv=['codex-tools','git','--version']; namespace['main']()
"""
        import json
        child = subprocess.run([sys.executable, "-I", "-B", "-c", code,
                                str(Path(__file__).with_name("codex_tools.py")), json.dumps(self.args), str(self.base)],
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
        self.assertEqual(0, child.returncode, child.stderr.decode())
        self.assertIn(b"EXEC_SELECTED_ACCELERATED", child.stdout)


if __name__ == "__main__":
    unittest.main()
