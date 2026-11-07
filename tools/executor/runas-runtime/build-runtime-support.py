"""Build fresh runtime helpers and legacy JNI from current, frozen sources.

Two real NDK r29 compilations must match. This supplies build evidence only;
neither Linux nor Android sandbox qualification follows from a successful build.
"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "tools/executor"))
from android_ndk_host import select_toolchain, write_host_evidence

INPUTS = {
    "native-files.c": "tools/executor/native-files.c",
    "native-file-handle.c": "tools/executor/native-file-handle.c",
    "native-runner-seccomp.h": "tools/executor/native-runner-seccomp.h",
    "spawn.c": "tools/executor/shizuku-service/transport/src/main/cpp/spawn.c",
    "cwd.c": "tools/executor/bionic-cwd/cwd.c",
    "exports.map": "tools/executor/bionic-cwd/exports.map",
    "build-runtime-support.py": "tools/executor/runas-runtime/build-runtime-support.py",
    "android_ndk_host.py": "tools/executor/android_ndk_host.py",
    "check-elf.py": "tools/executor/bionic-runtime/shizuku-check-elf.py",
    "inspect-elf.py": "tools/executor/stage-android-python.py",
}
TARGETS = {
    "libcodex_native_files.so": ("native-files.c", False),
    "libcodex_native_file_handle.so": ("native-file-handle.c", False),
    "libcodex_shizuku_transport.so": ("spawn.c", True),
    "libcodex_bionic_cwd.so": ("cwd.c", True),
}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError("Duplicate evidence key: " + name)
            result[name] = value
        return result
    return json.loads(path.read_bytes(), object_pairs_hook=unique)


def regular(root, relative):
    if (not isinstance(relative, str) or not relative or "\\" in relative
            or ":" in relative or any(p in {"", ".", ".."} for p in relative.split("/"))):
        raise ValueError("Noncanonical evidence path")
    target = root
    for part in relative.split("/"):
        target /= part
        if target.is_symlink() or target.is_junction():
            raise ValueError("Evidence path alias")
    target.resolve(strict=True).relative_to(root.resolve(strict=True))
    if not target.is_file():
        raise ValueError("Evidence must be a regular file")
    return target


def elf(path, shared):
    data = path.read_bytes()
    spec = importlib.util.spec_from_file_location("codex_support_elf",
        ROOT / INPUTS["inspect-elf.py" if shared else "check-elf.py"])
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    if not shared:
        if sys.flags.optimize:
            raise ValueError("ELF checks require normal Python assertions")
        return checker.check(path)
    result = checker.elf_info(data)
    header = struct.unpack_from("<HHIQQQIHHHHHH", data, 16)
    segments = [struct.unpack_from("<IIQQQQQQ", data, header[4] + i * 56)
                for i in range(header[9])]
    dynamic = next(s for s in segments if s[0] == 2)
    tags = dict(struct.unpack_from("<QQ", data, p)
                for p in range(dynamic[2], dynamic[2] + dynamic[5], 16))
    stacks = [s for s in segments if s[0] == 0x6474E551]
    if (header[3] != 0 or result["interpreter"] is not None or result["runpath"]
            or not tags.get(30, 0) & 8 or 15 in tags
            or not any(s[0] == 0x6474E552 for s in segments)
            or len(stacks) != 1 or stacks[0][1] & 1
            or any(row["alignment"] != 16384 for row in result["loads"])
            or set(result["needed"]) - {"libc.so", "libdl.so"}):
        raise ValueError("Unsupported runtime support shared ELF")
    return dict(result, sha256=digest(data), bytes=len(data), relro_now=True, nx_stack=True)


def admit(build):
    build = Path(build).resolve(strict=True)
    build.relative_to(ROOT)
    record = read_json(regular(build, "build.json"))
    if (record.get("schema") != "codex.native-support-build.v1"
            or record.get("androidExecuted") is not False or record.get("reproducible") is not True
            or record.get("ndk") != "29.0.14206865" or record.get("apiLevel") != 35):
        raise ValueError("Unsupported runtime support build")
    source_bytes = regular(build, "sources.json").read_bytes()
    sources = read_json(build / "sources.json")
    if (digest(source_bytes) != record.get("sourceManifestSha256")
            or len(sources) != len(INPUTS) or {row["path"] for row in sources} != set(INPUTS)):
        raise ValueError("Runtime support source inventory differs")
    if {p.name for p in (build / "source").iterdir()} != set(INPUTS):
        raise ValueError("Unexpected frozen support source")
    for row in sources:
        data = regular(build, "source/" + row["path"]).read_bytes()
        if (digest(data) != row["sha256"] or len(data) != row["bytes"]
                or data != (ROOT / INPUTS[row["path"]]).read_bytes()):
            raise ValueError("Runtime support source differs: " + row["path"])
    if "Pkg.Revision = 29.0.14206865" not in regular(build, "ndk-source.properties").read_text().splitlines():
        raise ValueError("Runtime support NDK differs")
    rows = record["binaries"]
    if len(rows) != len(TARGETS) or {row["name"] for row in rows} != set(TARGETS):
        raise ValueError("Runtime support binary inventory differs")
    libraries = {}
    for row in rows:
        name = row["name"]
        binary = regular(build, name)
        data = binary.read_bytes()
        if (digest(data) != row["sha256"] or len(data) != row["bytes"]
                or regular(build, "repeat/" + name).read_bytes() != data
                or row.get("realRecompilationIdentical") is not True
                or elf(binary, TARGETS[name][1]) != row["elf"]):
            raise ValueError("Runtime support binary/evidence differs: " + name)
        libraries[name] = data
    return libraries, {"path": build.relative_to(ROOT).as_posix(),
        "buildManifestSha256": digest((build / "build.json").read_bytes()),
        "sourceManifestSha256": record["sourceManifestSha256"], "androidExecuted": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ndk", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    ndk, output = args.ndk.resolve(strict=True), args.output.resolve()
    output.relative_to(ROOT)
    if "Pkg.Revision = 29.0.14206865" not in (ndk / "source.properties").read_text().splitlines():
        raise ValueError("Exact NDK r29 required")
    host = select_toolchain(ndk)
    output.mkdir(parents=True, exist_ok=False)
    write_host_evidence(output, host, Path(__file__))
    source = output / "source"
    source.mkdir()
    manifest = []
    for name, relative in sorted(INPUTS.items()):
        data = (ROOT / relative).read_bytes()
        (source / name).write_bytes(data)
        manifest.append({"path": name, "sha256": digest(data), "bytes": len(data)})
    (output / "sources.json").write_text(json.dumps(manifest, indent=2) + "\n")
    shutil.copyfile(ndk / "source.properties", output / "ndk-source.properties")
    (output / "repeat").mkdir()
    records = []
    for name, (filename, shared) in TARGETS.items():
        command = [str(host.tool("clang")), "--target=aarch64-linux-android35", "-std=c11", "-O2",
            "-Wall", "-Wextra", "-Werror", "-fstack-protector-strong", "-I" + str(source),
            "-fPIC" if shared else "-fPIE", "-shared" if shared else "-pie",
            "-ffile-prefix-map=" + str(output) + "=/codex/native-support",
            str(source / filename), "-Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack",
            "-Wl,-z,max-page-size=16384,-z,common-page-size=16384"]
        if shared:
            command.append("-Wl,-soname," + name)
        if filename == "cwd.c":
            command += ["-fvisibility=hidden", "-Wl,--version-script=" + str(source / "exports.map")]
        for repeat in (False, True):
            target = output / ("repeat/" if repeat else "") / name
            actual = command + ["-o", str(target)]
            suffix = ".repeat" if repeat else ""
            (output / (name + suffix + ".command.json")).write_text(json.dumps(actual, indent=2) + "\n")
            compiled = subprocess.run(actual, capture_output=True, timeout=120)
            (output / (name + suffix + ".stdout")).write_bytes(compiled.stdout)
            (output / (name + suffix + ".stderr")).write_bytes(compiled.stderr)
            compiled.check_returncode()
        data = (output / name).read_bytes()
        if (output / "repeat" / name).read_bytes() != data:
            raise ValueError("Runtime support recompilation differs: " + name)
        records.append({"name": name, "sha256": digest(data), "bytes": len(data),
            "realRecompilationIdentical": True, "elf": elf(output / name, shared)})
    record = {"schema": "codex.native-support-build.v1", "ndk": "29.0.14206865", "apiLevel": 35,
        "androidExecuted": False, "reproducible": True,
        "sourceManifestSha256": digest((output / "sources.json").read_bytes()), "binaries": records}
    (output / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    admit(output)
    print(json.dumps({"output": str(output), "binaries": len(records), "androidExecuted": False}))


if __name__ == "__main__":
    main()
