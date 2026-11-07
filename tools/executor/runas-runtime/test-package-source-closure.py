"""Offline source-admission checks; no native build or Android execution."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

PACKAGER = Path(__file__).with_name("stage-production-package.py")
spec = importlib.util.spec_from_file_location("source_closure_packager", PACKAGER)
packager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(packager)


class SourceClosureTests(unittest.TestCase):
    def setUp(self):
        work = packager.ROOT / "work"
        work.mkdir(exist_ok=True)
        self.temporary = tempfile.TemporaryDirectory(prefix="source-closure-", dir=work)
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.record = json.loads(packager.SOURCE_INPUTS.read_bytes())
        self.manifest = self.root / "sources.json"
        for row in self.record["files"]:
            if row["source"] is not None:
                destination = self.root / row["source"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes((packager.ROOT / row["source"]).read_bytes())

    def admit(self):
        self.manifest.write_text(json.dumps(self.record), encoding="utf-8")
        return packager.package_sources(self.root, self.manifest)

    def change_source(self, relative, suffix):
        row = next(row for row in self.record["files"] if row["path"] == relative)
        path = self.root / row["source"]
        data = path.read_bytes() + suffix
        path.write_bytes(data)
        # Keep the byte inventory consistent so the AST check is exercised.
        row.update(bytes=len(data), sha256=packager.digest(data))

    def test_current_checked_out_closure_needs_no_downloads(self):
        sources = self.admit()
        self.assertEqual(sources, packager.package_sources())
        self.assertIn("tools/executor/bionic-supervisor/direct_processes.py", sources)
        self.assertIn("tools/executor/bionic-supervisor/tty_processes.py", sources)
        self.assertEqual(sources["tools/__init__.py"], b"")
        self.assertFalse((self.root / "downloads").exists())

    def test_missing_physical_source_fails(self):
        row = next(row for row in self.record["files"] if row["source"] is not None)
        (self.root / row["source"]).unlink()
        with self.assertRaises(FileNotFoundError):
            self.admit()

    def test_missing_real_package_initializer_is_not_synthesized(self):
        (self.root / "tools/executor/bionic-supervisor/__init__.py").unlink()
        with self.assertRaises(FileNotFoundError):
            self.admit()

    def test_changed_source_with_old_hash_fails(self):
        row = self.record["files"][0]
        with (self.root / row["source"]).open("ab") as output:
            output.write(b"\n# changed\n")
        with self.assertRaisesRegex(ValueError, "hash or length differs"):
            self.admit()

    def test_wrong_hash_with_unchanged_length_fails(self):
        self.record["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "hash or length differs"):
            self.admit()

    def test_duplicate_case_insensitive_output_path_fails(self):
        row = copy.deepcopy(self.record["files"][0])
        row["path"] = row["path"].upper().replace(".PY", ".py")
        self.record["files"].append(row)
        with self.assertRaisesRegex(ValueError, "Duplicate production source path"):
            self.admit()

    def test_duplicate_json_key_fails(self):
        self.manifest.write_text('{"schema": "first", "schema": "second"}', encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "Duplicate source manifest JSON key"):
            packager.package_sources(self.root, self.manifest)

    def test_parent_path_escape_fails(self):
        self.record["files"][0]["source"] = "../outside.py"
        with self.assertRaisesRegex(ValueError, "Invalid production source path"):
            self.admit()

    def test_unresolved_absolute_import_with_valid_hash_fails(self):
        self.change_source("codex_app_bootstrap.py", b"\nimport tools.executor.missing_source\n")
        with self.assertRaisesRegex(ValueError, "Unresolved production source import: tools.executor.missing_source"):
            self.admit()

    def test_unresolved_relative_import_with_valid_hash_fails(self):
        self.change_source("tools/executor/bionic-supervisor/factory.py", b"\nfrom .missing_relative import Factory\n")
        with self.assertRaisesRegex(ValueError, "Unresolved production source import: tools.executor.bionic-supervisor.missing_relative"):
            self.admit()

    def test_omitted_transitive_source_fails(self):
        self.record["files"] = [row for row in self.record["files"]
                                if row["path"] != "tools/executor/bionic-supervisor/direct_wire.py"]
        with self.assertRaisesRegex(ValueError, "Unresolved production source import"):
            self.admit()

    def test_unreachable_extra_source_fails(self):
        name = "tools/executor/unreachable.py"
        (self.root / name).write_bytes(b"")
        self.record["files"].append({"path": name, "source": name, "bytes": 0,
                                      "sha256": packager.digest(b"")})
        with self.assertRaisesRegex(ValueError, "reachable import closure"):
            self.admit()

    def test_literal_dynamic_import_is_resolved(self):
        self.change_source("codex_native_bootstrap.py", b"\nimportlib.import_module('tools.executor.missing_dynamic')\n")
        with self.assertRaisesRegex(ValueError, "Unresolved production source import: tools.executor.missing_dynamic"):
            self.admit()

    def test_undeclared_computed_import_fails(self):
        self.record["dynamicImports"].pop()
        with self.assertRaisesRegex(ValueError, "Unreviewed computed import"):
            self.admit()

    def test_unused_computed_import_declaration_fails(self):
        self.record["dynamicImports"].append({"path": "codex_app_bootstrap.py", "expression": "unused",
                                              "modules": ["tools.executor.bionic-supervisor.factory"]})
        with self.assertRaisesRegex(ValueError, "reachable import closure"):
            self.admit()

    def test_dynamic_loader_alias_is_refused(self):
        self.change_source("codex_app_bootstrap.py", b"\nfrom importlib import import_module as load\n")
        with self.assertRaisesRegex(ValueError, "Unreviewed importlib member alias"):
            self.admit()

    def test_extra_external_allowance_fails(self):
        self.record["externalModules"].append("email")
        with self.assertRaisesRegex(ValueError, "reachable import closure"):
            self.admit()

    def test_non_stdlib_external_allowance_fails(self):
        self.record["externalModules"].append("unreviewed_dependency")
        with self.assertRaisesRegex(ValueError, "unique standard-library modules"):
            self.admit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
