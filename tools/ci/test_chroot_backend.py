"""The chroot backend must stay a guarded, opt-in alternative to PRoot.

Chroot needs root, so it may only run when the user enabled the root channel in
this app. These checks keep that contract and the launcher's own guard rails
from drifting, without needing a device or an Android SDK.
"""
from pathlib import Path
import importlib.util
import json
import re
import tempfile
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
        self.assertIn("/data/user/0/*/files/debian", self.script)
        # A first install still has the tree in staging; that path is admitted too.
        self.assertIn(".codex-install/fresh/stages/*/root", self.script)
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


class BindTargetCleanupTest(unittest.TestCase):
    """Extra bind targets must not survive as foreign-owned directories.

    The keyring vault lives in no_backup/, bound at its own absolute path. That
    created root-owned directories inside the guest tree, and the installer's
    syncTree then refused to activate:
        Installer sync target is not an owned directory
    """

    def setUp(self):
        self.script = LAUNCHER.read_text(encoding="utf-8")

    def test_created_bind_targets_are_recorded(self):
        self.assertIn(".codex-chroot-created", self.script)

    def test_recorded_targets_are_pruned(self):
        self.assertIn('rmdir "$target"', self.script)
        # Parents created only to hold a bind target are pruned too.
        self.assertIn('rmdir "$parent"', self.script)


class GuestCleanupTest(unittest.TestCase):
    """The launcher must leave the guest tree as the app owns it.

    The installer walks the prepared root and refuses any entry owned by another
    uid; folders a root-privileged guest created would fail that check, and a
    still-attached bind mount would expose kernel-owned /proc entries to it.
    """

    def setUp(self):
        self.script = LAUNCHER.read_text(encoding="utf-8")

    def test_ownership_is_restored_before_exit(self):
        self.assertIn("restore_ownership", self.script)
        self.assertIn('chown -R "$uid:$uid"', self.script)
        # The call must come after the guest command, not just the definition.
        self.assertGreater(self.script.rindex("restore_ownership"),
                           self.script.index("timeout -k 5"))

    def test_namespace_mounts_are_detached(self):
        self.assertIn('umount "$root/$target"', self.script)


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


class SuResolutionTest(unittest.TestCase):
    """Chroot must resolve su exactly like the working root channel does.

    KernelSU serves su through a path an app process cannot stat, so a probe
    that returns null on failure silently disables chroot even though the app's
    own root channel works. The fallback must be the bare name, resolved by PATH
    inside the privileged call -- that is what CodexRootChannel already does.
    """

    def setUp(self):
        self.channel = CHANNEL.read_text(encoding="utf-8")
        self.root = (ROOT / "android/app/src/main/java/com/ai/codex/CodexRootChannel.java").read_text(encoding="utf-8")

    def test_available_falls_back_to_bare_su(self):
        self.assertIn('return "su";', self.channel)
        # A null return would disable the backend; it must not exist any more.
        self.assertNotIn("return null;\n    }\n\n    /**\n     * Materialise", self.channel)
        self.assertNotIn("no su available for chroot", self.channel)

    def test_candidates_match_the_root_channel(self):
        import re
        pattern = re.compile(r'"(/system/bin/su|/system/xbin/su|/sbin/su|/debug_ramdisk/su)"')
        self.assertEqual(set(pattern.findall(self.channel)), set(pattern.findall(self.root)))


class GuestEnvironmentValidationTest(unittest.TestCase):
    """The validator must not depend on regex escapes Java rejects.

    The previous pattern ended in a NUL escape, which java.util.regex refuses
    with "Unrecognized backslash escape sequence"; that exception escaped the
    launcher and aborted keyring preparation on every start.
    """

    def setUp(self):
        self.channel = CHANNEL.read_text(encoding="utf-8")

    def test_no_unsupported_regex_escapes(self):
        # A NUL character class inside a Java pattern string is the specific
        # mistake; assert the literal never appears in a matches() call.
        for line in self.channel.splitlines():
            if ".matches(" in line and "\\0" in line:
                self.fail("unsupported NUL escape in pattern: " + line.strip())

    def test_environment_entries_are_checked_without_regex(self):
        self.assertIn("isValidEnvironmentEntry", self.channel)
        self.assertIn("c == 0", self.channel)


class ChrootWiringTest(unittest.TestCase):
    def test_preparation_prefers_chroot_and_keeps_proot(self):
        text = PREPARATION.read_text(encoding="utf-8")
        self.assertIn("CodexChrootChannel.isAvailable(context)", text)
        # PRoot must remain the fallback so unrooted devices keep working.
        self.assertIn("SecretPipeProcess.run(process,credential,", text)
        # The activation timeout stays the widened bound.
        self.assertIn("KEYRING_PREPARATION_TIMEOUT_MS", text)


class SmokeTestBackendTest(unittest.TestCase):
    """The activation smoke test must use the same backend choice as keyring.

    It previously always ran through PRoot, so once chroot fixed keyring
    preparation the install still failed at "本机运行环境验证超时".
    """

    def test_smoke_prefers_chroot_and_keeps_proot(self):
        text = PREPARATION.parent.joinpath("PhoneRuntimeInstaller.java").read_text(encoding="utf-8")
        self.assertIn("CodexChrootChannel.isAvailable(context)", text)
        self.assertIn("smokeWithProot", text)
        self.assertIn("CODEX_RUNTIME_SMOKE", text)
        # The old assertion demanded a binary this payload does not ship.
        self.assertNotIn('text.contains("codex-cli")', text)


class RewriteQualificationTest(unittest.TestCase):
    """Rewriting the executor payload must refresh its pinned digests.

    codex-executor-qualification.json records the SHA-256 of the deployment and
    launch assets. Rewriting the application id changed those bytes but left the
    recorded digests stale, so the app refused to start the executor with
    "Native qualification digest mismatch".
    """

    def setUp(self):
        self.text = (ROOT / "tools/workstation/rewrite-application-id.py").read_text(encoding="utf-8")

    def test_qualification_asset_is_rewritten(self):
        self.assertIn("codex-executor-qualification.json", self.text)

    def test_pinned_digests_are_refreshed(self):
        for field in ("deploymentSha256", "sourceManifestSha256",
                      "evidenceSha256", "appLaunchBuildSha256"):
            self.assertIn(field, self.text)

    def test_manifest_entry_digests_are_refreshed(self):
        # The manifest lists every codex-executor/ source file with its digest;
        # the admission loop verifies each one, so a rewritten script must have
        # its entry refreshed before the manifest digest is recorded.
        self.assertIn("codex-executor-manifest.json", self.text)
        self.assertIn('entry["sha256"] = actual', self.text)

    def test_rewrite_is_idempotent(self):
        """Running the rewrite twice must not grow the id to ``...dev.dev``.

        The co-installed build rewrites once during ``recover`` and again after
        compiling the transport library (its digest lands in the deployment
        inventory). A plain substring replace turned the second pass into
        ``com.ai.codex.dev.dev`` and the build died with "Deployment packageName
        was not rewritten", so the rewrite must only match a whole id.
        """
        with tempfile.TemporaryDirectory() as directory:
            assets = Path(directory)
            script = ROOT / "tools" / "workstation" / "rewrite-application-id.py"
            module = importlib.util.spec_from_file_location("rewrite_app_id", script)
            loaded = importlib.util.module_from_spec(module)
            module.loader.exec_module(loaded)

            def write(relative, text):
                path = assets / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(text, encoding="utf-8")

            for relative in loaded.TEXT_ASSETS:
                write(relative, "package com.ai.codex\n# com.ai.codex/private\n")
            write("codex-executor-evidence.json", "{}")
            write("codex-executor-deployment.json", json.dumps({
                "packageName": "com.ai.codex",
                "pythonRuntime": {"path": "/data/user/0/com.ai.codex/files/python",
                                  "manifestAsset": "codex-python-runtime.json",
                                  "manifestSha256": ""},
                "nativeLibraries": {},
            }))
            write("codex-python-runtime.json", json.dumps({"runtimeHome": "/data/user/0/com.ai.codex/files"}))
            write("codex-executor-manifest.json", json.dumps([]))
            write("codex-executor-qualification.json", json.dumps({}))

            loaded.rewrite(assets, "com.ai.codex", "com.ai.codex.dev")
            deployment = json.loads((assets / "codex-executor-deployment.json").read_text())
            self.assertEqual(deployment["packageName"], "com.ai.codex.dev")

            # Second pass over already-rewritten assets: nothing left to change.
            self.assertEqual(loaded.rewrite(assets, "com.ai.codex", "com.ai.codex.dev"), [])
            deployment = json.loads((assets / "codex-executor-deployment.json").read_text())
            self.assertEqual(deployment["packageName"], "com.ai.codex.dev")
            for relative in loaded.TEXT_ASSETS:
                self.assertNotIn("com.ai.codex.dev.dev", (assets / relative).read_text())


class BuildTypeTest(unittest.TestCase):
    """The packaged native executor cannot run inside a debuggable app.

    Android starts debuggable apps without the zygote seccomp filter, and
    admission requires PR_GET_SECCOMP == 2. A debug APK therefore failed with
    "Application transport requires the exact non-root app identity and inherited
    seccomp 2". Verified on device: com.android.settings reported Seccomp 2 while
    the debug build reported 0.
    """

    def setUp(self):
        self.build = (ROOT / "android/app/build.gradle").read_text(encoding="utf-8")
        self.builder = (ROOT / "tools/ci/coinstalled-build.py").read_text(encoding="utf-8")

    def test_release_variant_exists_and_is_not_debuggable(self):
        self.assertIn("release {", self.build)
        self.assertIn("debuggable false", self.build)
        # It still has to be signed, or the APK cannot be installed.
        self.assertIn("signingConfig signingConfigs.debug", self.build)

    def test_target_sdk_is_a_build_input(self):
        # A targetSdk above the platform's API starts the process outside the
        # usual sandbox (Seccomp 0 instead of 2), which the executor refuses.
        self.assertIn("codexTargetSdk", self.build)
        self.assertIn("TARGET_SDK", self.builder)
        self.assertIn("codexTargetSdk=", self.builder)

    def test_coinstalled_build_assembles_release(self):
        self.assertIn("assembleRelease", self.builder)
        # assembleDebug may appear only for the :shizukuTransport module, which has
        # no release variant of its own; the application APK must be a release build.
        for line in self.builder.splitlines():
            if "assembleDebug" in line:
                self.assertIn(":shizukuTransport:", line, line.strip())


class SeccompToleranceTest(unittest.TestCase):
    """Admission accepts a KernelSU-unfiltered sandbox, and only that.

    KernelSU strips the zygote seccomp filter from authorised applications so that
    privilege escalation can work, and admission required PR_GET_SECCOMP == 2.
    Measured on the target device: com.tencent.mm (not authorised) reported 2, while
    com.ai.codex.dev, app.operit and com.droidspaces.app (all authorised) reported 0.
    The guest runtime needs the same authorisation, so the two requirements are
    mutually exclusive.

    This build accepts 0 as well, and nothing else: every identity, gid, NNP and
    capability condition is still enforced.
    """

    def setUp(self):
        self.c = (ROOT / "tools/executor/shizuku-service/transport/src/main/cpp"
                  / "app-spawn.c").read_text(encoding="utf-8")

    def test_seccomp_accepts_filtered_and_unfiltered(self):
        self.assertIn("tolerated_seccomp", self.c)
        self.assertIn("mode == 2 || mode == 0", self.c)
        # Anything other than 0 or 2 must still be rejected.
        self.assertNotIn("prctl(PR_GET_SECCOMP, 0, 0, 0, 0) == 0", self.c)

    def test_other_admission_conditions_are_unchanged(self):
        for condition in ("real != application_uid", "effective != real", "saved != real",
                          "greal != application_uid", "PR_GET_NO_NEW_PRIVS"):
            self.assertIn(condition, self.c)
        self.assertIn("capabilities[i].effective", self.c)

    def test_weakening_is_documented(self):
        self.assertIn("COM_AI_CODEX_ALLOW_UNFILTERED_SECCOMP", self.c)
        # The comment must state that this is a deliberate deviation.
        self.assertIn("must not be presented as equivalent", self.c)


class AppTransportSourceBuildTest(unittest.TestCase):
    """The app transport must be compiled here, not reused from a published APK."""

    def setUp(self):
        self.cmake = (ROOT / "tools/executor/shizuku-service/transport/src/main/cpp"
                      / "CMakeLists.txt").read_text(encoding="utf-8")
        self.gradle = (ROOT / "tools/executor/shizuku-service/transport/build.gradle").read_text(encoding="utf-8")
        self.builder = (ROOT / "tools/ci/coinstalled-build.py").read_text(encoding="utf-8")

    def test_option_is_enabled(self):
        self.assertIn("CODEX_BUILD_APP_TRANSPORT", self.cmake)
        self.assertIn("CODEX_BUILD_APP_TRANSPORT=ON", self.gradle)

    def test_published_copy_is_not_reused(self):
        self.assertIn('if name == "libcodex_app_transport.so"', self.builder)


if __name__ == "__main__":
    unittest.main()
