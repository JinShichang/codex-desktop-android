"""Every packaged PRoot launch must keep PRoot off its seccomp acceleration.

PRoot can translate syscalls by consuming ``SECCOMP_RET_TRACE`` events through
``PTRACE_EVENT_SECCOMP``. On current Android kernels that acceleration breaks the
second guest ``execve``: the tracee dies with ``SIGSEGV`` and callers only see
``proot info: vpid 1: terminated with signal 11``, with no Python or PRoot
diagnostic of its own.

A single direct ``execve`` still works, so the failure only appears once the guest
execs twice -- which is what keyring preparation, package installation, the runtime
smoke test and the desktop session all do. ``PROOT_NO_SECCOMP=1`` selects the plain
``PTRACE_SYSCALL`` path and is already pinned by the GNU executor. This check keeps
the Android launch sites from drifting away from it again.
"""
import re
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
SOURCES = ROOT / "android" / "app" / "src"
HELPER = "disableSeccompAcceleration"


def proot_launch_sites():
    """Return production Java files that start PRoot with a tracer environment.

    ``PROOT_LOADER`` is only set by code that builds the PRoot child's own
    environment, so it distinguishes a launch from a payload inventory or a
    helper that hands the guest tree to another program.
    """
    for path in sorted(SOURCES.rglob("*.java")):
        if "/src/test/" in path.as_posix() or "/src/androidTest/" in path.as_posix():
            continue
        text = path.read_text(encoding="utf-8")
        if "libproot.so" not in text or "PROOT_LOADER" not in text:
            continue
        yield path, text


class ProotLaunchEnvironmentTest(unittest.TestCase):
    def test_every_proot_launch_disables_seccomp_acceleration(self):
        sites = list(proot_launch_sites())
        self.assertGreaterEqual(len(sites), 6, "Expected the packaged PRoot launch sites")
        missing = [path.relative_to(ROOT).as_posix() for path, text in sites
                   if HELPER not in text and "PROOT_NO_SECCOMP" not in text]
        self.assertEqual([], missing,
                         "These PRoot launches would die on a nested guest exec: " + ", ".join(missing))

    def test_helper_sets_the_documented_value(self):
        helper = SOURCES / "main" / "java" / "com" / "ai" / "codex" / "install" / "ProotEnvironment.java"
        text = helper.read_text(encoding="utf-8")
        self.assertIn('NO_SECCOMP = "PROOT_NO_SECCOMP"', text)
        self.assertRegex(text, r'environment\.put\(NO_SECCOMP,\s*"1"\)')

    def test_helper_value_is_not_forwarded_into_the_guest(self):
        # The guest environment is always supplied explicitly by `env -i`, so the
        # tracer-only variable cannot leak into a session the desktop client sees.
        for path, text in proot_launch_sites():
            for match in re.finditer(r'"PROOT_NO_SECCOMP=?([^"]*)"', text):
                self.assertEqual("", match.group(1), path)


class ApplicationIdTest(unittest.TestCase):
    """Nothing may hard-code the original id where it means "this installation".

    A literal ``com.ai.codex`` in a shortcut, a component lookup or a process
    matcher makes a build installed under a different id address the *other*
    installation: shortcuts open the wrong app, and once that app is removed the
    target is missing entirely.
    """

    def test_shortcuts_follow_the_application_id(self):
        shortcuts = SOURCES / "main" / "res" / "xml" / "codex_shortcuts.xml"
        text = shortcuts.read_text(encoding="utf-8")
        self.assertIn('android:targetPackage="${applicationId}"', text)
        self.assertNotIn('android:targetPackage="com.ai.codex"', text)

    def test_self_lookups_use_the_build_id(self):
        privileged = (SOURCES / "main" / "java" / "com" / "ai" / "codex"
                      / "CodexPrivilegedContext.java").read_text(encoding="utf-8")
        self.assertIn("BuildConfig.APPLICATION_ID", privileged)
        # The historical default must not survive as a literal package lookup.
        self.assertNotIn('createPackageContext("com.ai.codex"', privileged)

    def test_process_reaping_does_not_use_a_package_prefix(self):
        service = (SOURCES / "main" / "java" / "com" / "termux" / "x11"
                   / "CodexRuntimeService.java").read_text(encoding="utf-8")
        self.assertNotIn('command.startsWith("com.ai.codex")', service)
        self.assertIn("getPackageName()", service)


if __name__ == "__main__":
    unittest.main()
