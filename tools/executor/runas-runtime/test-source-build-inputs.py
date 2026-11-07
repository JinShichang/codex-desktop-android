"""Exercise fresh input admission against real compiled artifacts and tampering."""
import argparse
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, HERE / filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


support = load("tested_runtime_support", "build-runtime-support.py")
fresh = load("tested_source_production", "source-production-inputs.py")


class SupportAdmissionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="support-admission-test-", dir=ROOT / "work")
        self.addCleanup(self.temporary.cleanup)
        self.build = Path(self.temporary.name) / "build"
        shutil.copytree(ARGS.support_build.resolve(strict=True), self.build)

    def test_actual_double_compilation_is_admitted(self):
        libraries, proof = support.admit(self.build)
        self.assertEqual(set(libraries), set(support.TARGETS))
        self.assertIs(proof["androidExecuted"], False)

    def test_modified_binary_is_rejected(self):
        path = self.build / "libcodex_native_files.so"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            support.admit(self.build)

    def test_different_recompilation_is_rejected(self):
        path = self.build / "repeat/libcodex_bionic_cwd.so"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            support.admit(self.build)

    def test_modified_frozen_source_is_rejected(self):
        path = self.build / "source/spawn.c"
        path.write_bytes(path.read_bytes() + b"\n/* changed */\n")
        with self.assertRaises(ValueError):
            support.admit(self.build)

    def test_duplicate_manifest_key_is_rejected(self):
        path = self.build / "build.json"
        path.write_bytes(path.read_bytes().replace(b'{', b'{"ndk":"29.0.14206865",', 1))
        with self.assertRaises(ValueError):
            support.admit(self.build)

    def test_missing_binary_record_is_rejected(self):
        path = self.build / "build.json"
        record = json.loads(path.read_bytes())
        record["binaries"].pop()
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            support.admit(self.build)

    def test_other_ndk_is_rejected(self):
        path = self.build / "build.json"
        record = json.loads(path.read_bytes())
        record["ndk"] = "27.0.12077973"
        path.write_text(json.dumps(record))
        with self.assertRaises(ValueError):
            support.admit(self.build)

    def test_frozen_source_symlink_is_rejected(self):
        path = self.build / "source/spawn.c"
        path.unlink()
        try:
            path.symlink_to(ROOT / support.INPUTS["spawn.c"])
        except OSError:
            self.skipTest("Host does not allow unprivileged symlinks")
        with self.assertRaises(ValueError):
            support.admit(self.build)


class RuntimeAdmissionTests(unittest.TestCase):
    def test_actual_official_runtime_and_source_inputs_are_readmitted(self):
        inventory = json.loads((ARGS.native_stage / "manifest.json").read_bytes())
        self.assertEqual(fresh.readmit(ARGS.native_stage, inventory), inventory["sourceBuildInputs"])

    def test_modified_stdlib_is_rejected_even_with_unchanged_manifest(self):
        inventory = json.loads((ARGS.native_stage / "manifest.json").read_bytes())
        proof = inventory["sourceBuildInputs"]
        with tempfile.TemporaryDirectory(prefix="runtime-admission-test-", dir=ROOT / "work") as temporary:
            runtime = Path(temporary) / "runtime"
            shutil.copytree(ROOT / proof["runtime"]["path"], runtime)
            target = next((runtime / "assets/bionic-python").rglob("json/__init__.py"))
            target.write_bytes(target.read_bytes() + b"\n# changed\n")
            with self.assertRaises(ValueError):
                fresh.admit(runtime, ROOT / proof["runtime"]["pythonArchive"],
                    ROOT / proof["supportBuild"]["path"], ROOT / proof["pythonCliBuild"]["path"],
                    ROOT / inventory["bashBuild"]["path"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--support-build", type=Path, required=True)
    parser.add_argument("--native-stage", type=Path, required=True)
    ARGS = parser.parse_args()
    unittest.main(argv=[__file__], verbosity=2)
