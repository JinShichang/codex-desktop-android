"""Admit explicitly selected fresh runtime inputs alongside the historical pins."""
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]


def digest(data):
    return hashlib.sha256(data).hexdigest()


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def tree(root):
    result = {}
    for path in root.rglob("*"):
        if path.is_symlink() or path.is_junction():
            raise ValueError("Source runtime cannot contain path aliases")
        if path.is_dir():
            continue
        if not path.is_file():
            raise ValueError("Source runtime contains a special file")
        result[path.relative_to(root).as_posix()] = path
    return result


def normalized_manifest(manifest):
    # Origin is descriptive and can be an absolute or relative CLI input path.
    # Every other field and every payload byte must match the pinned producer.
    result = json.loads(json.dumps(manifest))
    for row in result["nativeFiles"]:
        row.pop("origin", None)
    return result


def admit(runtime, archive, support, cli, bash):
    runtime, archive, support, cli, bash = (
        Path(p).resolve(strict=True) for p in (runtime, archive, support, cli, bash))
    for path in (runtime, support, cli, bash):
        path.relative_to(ROOT)
    helper = load("codex_fresh_runtime_support", Path(__file__).with_name("build-runtime-support.py"))
    libraries, support_provenance = helper.admit(support)
    package = load("codex_fresh_official_python", ROOT / "tools/executor/bionic-runtime/python-package.py")
    # package() authenticates the complete official tarball before extraction.
    package.package(archive)
    cli_record = helper.read_json(helper.regular(cli, "build.json"))
    cli_source = helper.regular(cli, "python-cli.c").read_bytes()
    if (cli_record.get("schema") != "codex.runas-python-windows-build.v1"
            or cli_record.get("androidExecuted") is not False
            or cli_record.get("ndk") != "29.0.14206865"
            or cli_record.get("archiveSha256") != package.PIN["sha256"]
            or cli_source != (ROOT / "tools/executor/bionic-runtime/python-cli.c").read_bytes()
            or digest(cli_source) != cli_record.get("sourceSha256")
            or digest(helper.regular(cli, "libcodex_python_cli.so").read_bytes()) != cli_record.get("executableSha256")):
        raise ValueError("Fresh Python CLI differs from its current source or pinned build inputs")
    producer = ROOT / "tools/executor/bionic-runtime/stage-runtime.py"
    expected_parent = ROOT / "work"
    expected_parent.mkdir(exist_ok=True)
    actual = tree(runtime)
    manifest_bytes = helper.regular(runtime, "manifest.json").read_bytes()
    manifest = helper.read_json(runtime / "manifest.json")
    with tempfile.TemporaryDirectory(prefix="source-runtime-admission-", dir=expected_parent) as temporary:
        expected = Path(temporary) / "runtime"
        subprocess.run([sys.executable, "-B", str(producer), "--python-archive", str(archive),
            "--python-cli", str(cli / "libcodex_python_cli.so"),
            "--bash", str(bash / "libcodex_bash.so"), "--output", str(expected)],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
        generated = tree(expected)
        if set(actual) != set(generated):
            raise ValueError("Fresh runtime has missing or additional files")
        expected_manifest = helper.read_json(expected / "manifest.json")
        if normalized_manifest(manifest) != normalized_manifest(expected_manifest):
            raise ValueError("Fresh runtime manifest differs from the pinned producer")
        for name in actual.keys() - {"manifest.json"}:
            if actual[name].read_bytes() != generated[name].read_bytes():
                raise ValueError("Fresh runtime differs from the official package or selected executable: " + name)
    provenance = {"schema": "codex.native-source-inputs.v1", "androidExecuted": False,
        "runtime": {"path": runtime.relative_to(ROOT).as_posix(),
            "pythonArchive": archive.relative_to(ROOT).as_posix(),
            "manifestSha256": digest(manifest_bytes), "pythonArchiveSha256": digest(archive.read_bytes()),
            "producerSha256": digest(producer.read_bytes())},
        "pythonCliBuild": {"path": cli.relative_to(ROOT).as_posix(),
            "buildManifestSha256": digest((cli / "build.json").read_bytes())},
        "supportBuild": support_provenance}
    return manifest, libraries, provenance


def readmit(stage, inventory):
    proof = inventory["sourceBuildInputs"]
    runtime = proof["runtime"]
    manifest, libraries, actual = admit(ROOT / runtime["path"], ROOT / runtime["pythonArchive"],
        ROOT / proof["supportBuild"]["path"], ROOT / proof["pythonCliBuild"]["path"],
        ROOT / inventory["bashBuild"]["path"])
    if actual != proof:
        raise ValueError("Fresh source input provenance differs from its actual builds")
    for name, data in libraries.items():
        if (stage / "jniLibs/arm64-v8a" / name).read_bytes() != data:
            raise ValueError("Fresh staged support library differs from its admitted build: " + name)
    return actual
