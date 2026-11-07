"""Offline rejection boundaries; fixtures are not qualified OpenSSL builds."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


BUILDER = Path(__file__).resolve().parents[1] / "tools/executor/build-gnu-engine.py"
SPEC = importlib.util.spec_from_file_location("gnu_engine_builder", BUILDER)
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


def elf_header(machine="AArch64", elf_class="ELF64", kind="REL (Relocatable file)"):
    return ("ELF Header:\n"
            f"  Class:                             {elf_class}\n"
            "  Data:                              2's complement, little endian\n"
            f"  Type:                              {kind}\n"
            f"  Machine:                           {machine}\n")


class DependencyInputsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.prefix = self.root / "deps"
        self.openssl = self.prefix / "openssl"
        (self.openssl / "lib").mkdir(parents=True)
        headers = self.openssl / "include/openssl"
        headers.mkdir(parents=True)
        (headers / "opensslv.h").write_text('#define OPENSSL_VERSION_STR "3.6.3"\n')
        for name in ("ssl.h", "crypto.h", "opensslconf.h", "configuration.h"):
            (headers / name).write_text("/* offline test fixture */\n")
        for name in builder.OPENSSL_ARCHIVES:
            (self.openssl / "lib" / name).write_bytes(b"!<arch>\nfixture-" + name.encode())
        self.source = self.root / "source.tar.gz"
        self.source.write_bytes(b"offline source fixture")
        # Only the source hash is replaced for these local fixtures; both
        # archive hashes are still checked against actual bytes by the builder.
        self.source_patch = patch.object(builder, "OPENSSL_SOURCE_SHA256", builder.sha(self.source))
        self.source_patch.start()
        self.addCleanup(self.source_patch.stop)
        self.manifest = self.root / "inputs.json"
        self.inputs = {
            "schema": "codex.gnu-engine-dependencies.v1", "target": builder.TARGET,
            "openssl": {
                "version": "3.6.3", "configureTarget": "linux-aarch64",
                "compilerTarget": "aarch64-linux-gnu",
                "source": {"url": builder.OPENSSL_SOURCE_URL, "archive": self.source.name,
                           "sha256": builder.sha(self.source)},
                "archives": {name: builder.sha(self.openssl / "lib" / name)
                             for name in builder.OPENSSL_ARCHIVES},
            },
        }

    def check(self, inputs=None):
        self.manifest.write_text(json.dumps(self.inputs if inputs is None else inputs))
        return builder.dependencies(self.prefix, self.manifest)

    def test_relative_source_and_both_real_library_hashes_are_retained(self):
        with patch.object(builder, "run", return_value=elf_header() + elf_header()):
            inputs, report = self.check()
        self.assertEqual(inputs, self.inputs)
        self.assertEqual(report["sourceArchiveSha256"], builder.sha(self.source))
        self.assertEqual([item["elfObjects"] for item in report["archives"]], [2, 2])
        self.assertEqual([item["sha256"] for item in report["archives"]],
                         list(self.inputs["openssl"]["archives"].values()))

    def test_changed_archive_fails_before_any_tool_invocation(self):
        for name in builder.OPENSSL_ARCHIVES:
            with self.subTest(name=name), patch.object(builder, "run") as run:
                path = self.openssl / "lib" / name
                original = path.read_bytes()
                path.write_bytes(original + b"changed")
                with self.assertRaisesRegex(RuntimeError, "Qualified OpenSSL archive changed"):
                    self.check()
                run.assert_not_called()
                path.write_bytes(original)

    def test_changed_source_archive_fails_before_any_tool_invocation(self):
        self.source.write_bytes(b"changed source")
        with patch.object(builder, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Official OpenSSL source archive changed"):
                self.check()
            run.assert_not_called()

    def test_source_version_target_and_compiler_identity_cannot_be_overridden(self):
        for field, wrong in (("version", "3.5.7"), ("configureTarget", "android-arm64"),
                             ("compilerTarget", "aarch64-linux-android")):
            inputs = copy.deepcopy(self.inputs)
            inputs["openssl"][field] = wrong
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                self.check(inputs)
        for field, wrong in (("url", "https://unreviewed.invalid/source.tar.gz"),
                             ("sha256", "0" * 64)):
            inputs = copy.deepcopy(self.inputs)
            inputs["openssl"]["source"][field] = wrong
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, "identity mismatch"):
                self.check(inputs)

    def test_manifest_requires_both_complete_library_hashes(self):
        for archives in ({"libssl.a": "0" * 64}, {"libssl.a": "REPLACE_ME", "libcrypto.a": "0" * 64},
                         {**self.inputs["openssl"]["archives"], "unexpected.a": "0" * 64}):
            inputs = copy.deepcopy(self.inputs)
            inputs["openssl"]["archives"] = archives
            with self.subTest(archives=archives), self.assertRaises(RuntimeError):
                self.check(inputs)

    def test_headers_must_match_source_version(self):
        (self.openssl / "include/openssl/opensslv.h").write_text('#define OPENSSL_VERSION_STR "3.5.7"\n')
        with self.assertRaisesRegex(RuntimeError, "headers do not match"):
            self.check()

    def test_thin_archive_is_refused_even_when_its_own_hash_is_pinned(self):
        path = self.openssl / "lib/libssl.a"
        path.write_bytes(b"!<thin>\nexternal.o")
        self.inputs["openssl"]["archives"]["libssl.a"] = builder.sha(path)
        with patch.object(builder, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "thin archives are refused"):
                self.check()
            run.assert_not_called()

    def test_every_archive_member_must_be_aarch64_relocatable_elf64(self):
        for bad in (elf_header(machine="Advanced Micro Devices X86-64"),
                    elf_header(elf_class="ELF32"), elf_header(kind="DYN (Shared object file)")):
            with self.subTest(header=bad), patch.object(builder, "run", return_value=elf_header() + bad):
                with self.assertRaisesRegex(RuntimeError, "archive member 2 has unexpected"):
                    self.check()

    def test_empty_archive_has_no_qualified_objects(self):
        with patch.object(builder, "run", return_value=""):
            with self.assertRaisesRegex(RuntimeError, "No ELF objects"):
                self.check()

    def test_preparation_checks_dependencies_before_source_export_or_v8_fetch(self):
        import argparse
        args = argparse.Namespace(dependencies=self.prefix, dependency_manifest=self.manifest)
        self.manifest.write_text(json.dumps(self.inputs))
        (self.openssl / "lib/libcrypto.a").write_bytes(b"changed")
        with patch.object(builder, "native_storage") as storage, patch.object(builder, "run") as run:
            with self.assertRaisesRegex(RuntimeError, "Qualified OpenSSL archive changed"):
                builder.prepare(args)
            storage.assert_not_called()
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
