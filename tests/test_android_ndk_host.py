"""Host selection regressions; fixtures are text files and never executed."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/executor"))
import android_ndk_host as ndk_host


class NdkHostTests(unittest.TestCase):
    def setUp(self):
        parent = ROOT / "work/ndk-host-tests"
        parent.mkdir(parents=True, exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(dir=parent)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def tools(self, tag, suffix):
        directory = self.root / "toolchains/llvm/prebuilt" / tag
        (directory / "bin").mkdir(parents=True)
        for name in ("clang", "llvm-readelf"):
            (directory / "bin" / (name + suffix)).write_text("not an executable\n")
        return directory

    def select(self, system, machine, release="test"):
        with patch.object(ndk_host.platform, "system", return_value=system), \
                patch.object(ndk_host.platform, "machine", return_value=machine), \
                patch.object(ndk_host.platform, "release", return_value=release), \
                patch.object(ndk_host.os, "access", return_value=True):
            return ndk_host.select_toolchain(self.root)

    def test_windows_amd64_uses_exe(self):
        expected = self.tools("windows-x86_64", ".exe")
        host = self.select("Windows", "AMD64")
        self.assertEqual(host.root, expected)
        self.assertEqual(host.tool("clang"), expected / "bin/clang.exe")
        self.assertFalse(host.wsl)

    def test_linux_and_wsl_use_native_tools(self):
        expected = self.tools("linux-x86_64", "")
        host = self.select("Linux", "x86_64", "6.6.87.2-microsoft-standard-WSL2")
        with patch.object(ndk_host.os, "access", return_value=True):
            self.assertEqual(host.tool("llvm-readelf"), expected / "bin/llvm-readelf")
        self.assertTrue(host.wsl)
        self.assertFalse(self.select("Linux", "x86_64", "6.6.0").wsl)

    def test_other_host_toolchain_is_never_selected(self):
        self.tools("windows-x86_64", ".exe")
        with self.assertRaisesRegex(FileNotFoundError, "selected native host"):
            self.select("Linux", "x86_64")

    def test_unsupported_hosts_fail_before_toolchain_lookup(self):
        for system, machine in (("Darwin", "arm64"), ("Linux", "aarch64"),
                                ("Windows", "ARM64"), ("Plan9", "x86_64")):
            with self.subTest(system=system, machine=machine), \
                    self.assertRaisesRegex(ValueError, "Unsupported NDK build host"):
                self.select(system, machine)

    def test_missing_or_nonexecutable_tool_fails(self):
        directory = self.tools("linux-x86_64", "")
        with patch.object(ndk_host.os, "access", return_value=False), \
                self.assertRaises(FileNotFoundError):
            ndk_host.NdkHost(directory, "linux-x86_64", "", "Linux", "x86_64", False).tool("clang")
        (directory / "bin/llvm-readelf").unlink()
        with self.assertRaises(FileNotFoundError):
            self.select("Linux", "x86_64")

    def test_evidence_preserves_helper_and_tool_hashes(self):
        self.tools("windows-x86_64", ".exe")
        host = self.select("Windows", "AMD64")
        output = self.root / "output"
        output.mkdir()
        ndk_host.write_host_evidence(output, host, Path(__file__))
        self.assertEqual((output / "android_ndk_host.py").read_bytes(), Path(ndk_host.__file__).read_bytes())
        record = json.loads((output / "host-toolchain.json").read_text())
        self.assertEqual(record["hostTag"], "windows-x86_64")
        self.assertEqual(record["tools"]["clang"]["sha256"],
                         hashlib.sha256(host.tool("clang").read_bytes()).hexdigest())
        with self.assertRaises(FileExistsError):
            ndk_host.write_host_evidence(output, host, Path(__file__))

    def test_builders_reject_other_host_before_creating_outputs(self):
        # Only an incompatible host directory exists, so no compiler can run.
        if ndk_host.platform.system() == "Windows":
            self.tools("linux-x86_64", "")
        else:
            self.tools("windows-x86_64", ".exe")
        (self.root / "source.properties").write_text("Pkg.Revision = 29.0.14206865\n")
        builders = {
            "bionic-supervisor/build-direct-windows.py": [],
            "bionic-supervisor/build-model-windows.py": [],
            "bionic-supervisor/build-pty-windows.py": [],
            "runas-runtime/build-python-windows.py": ["--prefix", str(self.root / "prefix")],
            "runas-runtime/build-bootstrap-windows.py": ["--prefix", str(self.root / "prefix"),
                "--inventory", str(self.root / "inventory.h"), "--libraries", str(self.root / "libraries")],
            "shizuku-service/build-app-transport-windows.py": [],
        }
        for index, (relative, options) in enumerate(builders.items()):
            with self.subTest(builder=relative):
                output = self.root / ("builder-output-" + str(index))
                result = subprocess.run([sys.executable, "-B", str(ROOT / "tools/executor" / relative),
                    "--ndk", str(self.root), "--output", str(output), *options],
                    capture_output=True, text=True, timeout=30)
                self.assertNotEqual(result.returncode, 0)
                self.assertRegex(result.stderr, "selected native host toolchain|Unsupported NDK build host")
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
