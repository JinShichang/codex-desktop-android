"""The chroot backend must stay a guarded, opt-in alternative to PRoot.

Chroot needs root, so it may only run when the user enabled the root channel in
this app. These checks keep that contract and the launcher's own guard rails
from drifting, without needing a device or an Android SDK.
"""
from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "android/app/src/main/assets/chroot/codex-chroot.sh"
CHANNEL = ROOT / "android/app/src/main/java/com/ai/codex/CodexChrootChannel.java"
PREPARATION = ROOT / "android/app/src/main/java/com/ai/codex/install/AndroidInactivePreparation.java"


class ChrootLauncherTest(unittest.TestCase):
    def setUp(self):
        self.script = LAUNCHER.read_text(encoding="utf-8")

    def test_launcher_refuses_non_root_and_foreign_roots(self):
        # Root is mandatory and the guest root must live under the app's
        # private debian directory; anything else is refused, never degraded.
        self.assertIn('[ "$(id -u)" = "0" ]', self.script)
        self.assertIn("/data/user/0/*/files/debian|/data/data/*/files/debian", self.script)
        self.assertIn('fail "refusing root outside', self.script)

    def test_mounts_are_private_to_the_namespace(self):
        # A plain mount would modify the host mount table; the launcher must
        # enter a private mount namespace first.
        self.assertIn("exec unshare -m", self.script)
        self.assertIn("mount --make-rprivate /", self.script)
        # Essential trees are verified instead of silently missing.
        self.assertIn('$root/proc/self', self.script)
        self.assertIn('$root/dev/null', self.script)

    def test_identity_is_real_and_applied_inside_the_guest(self):
        # Android's chroot is toybox (no --userspec); the guest's own setpriv
        # performs the switch, so the guest passwd database is authoritative.
        self.assertIn("setpriv --reuid", self.script)
        # --userspec may only be mentioned as the reason it is not used.
        executable = "\n".join(line for line in self.script.splitlines()
                                if not line.lstrip().startswith("#"))
        self.assertNotIn("--userspec", executable)

    def test_script_parses_as_shell(self):
        # Let a real shell parser judge the script instead of counting braces,
        # which ${...} expansions would skew.
        import subprocess
        result = subprocess.run(["sh", "-n", str(LAUNCHER)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.assertEqual(0, result.returncode, result.stdout)


class ChrootChannelTest(unittest.TestCase):
    def setUp(self):
        self.java = CHANNEL.read_text(encoding="utf-8")

    def test_root_channel_switch_is_honoured(self):
        # Chroot must not become a side door to root: it needs the same explicit
        # capability the rest of the app requires.
        self.assertIn('CodexDeviceFeatures.enabled(context, "root")', self.java)

    def test_credential_travels_over_a_pipe_not_argv(self):
        # The keyring password is written to stdin and zeroed afterwards; it must
        # never be interpolated into the command line or the environment.
        self.assertIn("stdin.write(credential)", self.java)
        self.assertIn("java.util.Arrays.fill(credential", self.java)
        self.assertNotIn('"credential="', self.java)

    def test_guest_environment_and_binds_are_validated(self):
        self.assertIn("Invalid guest environment entry", self.java)
        self.assertIn("Invalid bind path", self.java)
        # A bind path must be absolute and free of separators that would let it
        # escape the list encoding.
        self.assertIn("path.contains(\";\")", self.java)


class ChrootWiringTest(unittest.TestCase):
    def test_preparation_prefers_chroot_and_keeps_proot(self):
        text = PREPARATION.read_text(encoding="utf-8")
        self.assertIn("CodexChrootChannel.isAvailable(context)", text)
        # PRoot must remain the fallback so unrooted devices keep working.
        self.assertIn("SecretPipeProcess.run(process,credential,", text)
        # The activation timeout stays the widened bound.
        self.assertIn("KEYRING_PREPARATION_TIMEOUT_MS", text)


if __name__ == "__main__":
    unittest.main()
