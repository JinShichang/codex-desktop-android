"""Run the phone image verifier on a full host JDK, outside Android's module stubs."""
import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    output.relative_to(ROOT)
    output.mkdir(parents=True, exist_ok=False)
    module_spec = importlib.util.spec_from_file_location("lifecycle_dependencies", ROOT / "tools/runtime/test-native-lifecycle-windows.py")
    dependencies = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(dependencies)
    jars = [dependencies.fetch_dependency(name) for name in dependencies.DEPENDENCIES]
    sources = [ROOT / ("android/app/src/" + tree + "/java/com/ai/codex/install/PhoneImageManifest" + suffix + ".java")
               for tree, suffix in (("main", ""), ("test", "Test"))]
    classes = output / "classes"
    classes.mkdir()
    cp = os.pathsep.join(map(str, jars))
    commands = [[shutil.which("javac"), "--release", "17", "-encoding", "UTF-8", "-cp", cp,
                 "-d", str(classes), *map(str, sources)],
                [shutil.which("java"), "-cp", str(classes) + os.pathsep + cp,
                 "org.junit.runner.JUnitCore", "com.ai.codex.install.PhoneImageManifestTest"]]
    for name, command in zip(("compile", "test"), commands):
        result = subprocess.run(command, cwd=ROOT, capture_output=True, timeout=90)
        (output / (name + ".log")).write_bytes(result.stdout + result.stderr)
        (output / (name + "-command.json")).write_text(json.dumps(command, indent=2) + "\n")
        result.check_returncode()
    report = {"success": True, "androidExecuted": False, "result": (output / "test.log").read_text(),
              "sources": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
              "dependencies": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in jars}}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
