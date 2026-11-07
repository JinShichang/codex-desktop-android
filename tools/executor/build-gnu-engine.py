"""Freeze and build the separate GNU ARM64 controller; never access a phone.

Run in WSL as codex-build. `prepare` does not compile Rust. The source comes
from the recovery export, not mutable working-tree files or a test harness.
"""
from __future__ import annotations

import argparse
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile


PROJECT = Path(__file__).resolve().parents[2]
BASE = "086ccc833bc9cf01024ad2dd6af7dbd421b6bf9a"
TARGET = "aarch64-unknown-linux-gnu"
BINARIES = ("codex", "codex-code-mode-host")
OPENSSL_VERSION = "3.6.3"
OPENSSL_SOURCE_URL = (
    "https://github.com/openssl/openssl/releases/download/openssl-3.6.3/openssl-3.6.3.tar.gz"
)
# Same reviewed source identity as tools/ci/native_validation.py, not the hash
# of a locally built library (which depends on the compiler and build recipe).
OPENSSL_SOURCE_SHA256 = "243a86649cf6f23eeb6a2ff2456e09e5d77dd9018a54d3d96b0c6bdd6ba6c7f1"
OPENSSL_ARCHIVES = ("libssl.a", "libcrypto.a")


def sha(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def run(argv, **kwargs) -> str:
    return subprocess.check_output(list(map(str, argv)), text=True, **kwargs).strip()


def openssl_archive(path: Path) -> dict:
    """Verify every member, not just the first object reported by readelf."""
    with path.open("rb") as stream:
        if stream.read(8) != b"!<arch>\n":
            raise RuntimeError(f"Not a self-contained static archive (thin archives are refused): {path}")
    # A failed readelf (including a non-ELF member) is fatal. Its C locale makes
    # the checks independent of the build host's UI language.
    output = run(["aarch64-linux-gnu-readelf", "--file-header", "--wide", path],
                 env=dict(os.environ, LC_ALL="C"))
    headers = re.split(r"(?m)^ELF Header:\s*$", output)[1:]
    if not headers:
        raise RuntimeError(f"No ELF objects in OpenSSL archive: {path}")
    for index, header in enumerate(headers, 1):
        for field, value in (("Class", "ELF64"),
                             ("Data", "2's complement, little endian"),
                             ("Type", "REL (Relocatable file)"), ("Machine", "AArch64")):
            actual = re.search(rf"(?m)^\s*{field}:\s*(.*?)\s*$", header)
            if actual is None or actual.group(1) != value:
                raise RuntimeError(f"OpenSSL archive member {index} has unexpected {field}: {path}")
    return {"path": str(path), "sha256": sha(path), "elfObjects": len(headers),
            "machine": "AArch64", "class": "ELF64", "type": "REL"}


def dependencies(prefix: Path, manifest_path: Path) -> tuple[dict, dict]:
    """Validate explicit local inputs before fetching V8 or freezing a build.

    The input manifest is an approval boundary: library hashes must already
    describe the reviewed dependency build. Never regenerate it during prepare.
    Source provenance is checked separately from the two output archive hashes.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if (manifest.get("schema") != "codex.gnu-engine-dependencies.v1"
            or manifest.get("target") != TARGET):
        raise RuntimeError("Unsupported GNU engine dependency manifest identity")
    openssl = manifest.get("openssl", {})
    source = openssl.get("source", {})
    if (openssl.get("version") != OPENSSL_VERSION
            or source.get("url") != OPENSSL_SOURCE_URL
            or source.get("sha256") != OPENSSL_SOURCE_SHA256
            or openssl.get("configureTarget") != "linux-aarch64"
            or openssl.get("compilerTarget") != "aarch64-linux-gnu"):
        raise RuntimeError("OpenSSL source or GNU ARM64 build identity mismatch")
    source_name = source.get("archive")
    if not isinstance(source_name, str) or not source_name.strip():
        raise RuntimeError("OpenSSL source.archive is required (relative to the dependency manifest)")
    source_archive = (manifest_path.parent / source_name).resolve()
    if sha(source_archive) != OPENSSL_SOURCE_SHA256:
        raise RuntimeError(f"Official OpenSSL source archive changed: {source_archive}")
    expected = openssl.get("archives", {})
    if set(expected) != set(OPENSSL_ARCHIVES):
        raise RuntimeError("OpenSSL archives must pin exactly libssl.a and libcrypto.a")
    for name in OPENSSL_ARCHIVES:
        if not isinstance(expected[name], str) or not re.fullmatch(r"[0-9a-f]{64}", expected[name]):
            raise RuntimeError(f"Expected a real lowercase SHA256 for {name}")
        path = prefix / "openssl/lib" / name
        if sha(path) != expected[name]:
            raise RuntimeError(f"Qualified OpenSSL archive changed: {path}")
    # Do not let unrecorded symlink targets supply headers or archive bytes.
    openssl_root = (prefix / "openssl").resolve()
    for path in openssl_root.rglob("*"):
        if path.is_symlink():
            try:
                path.resolve(strict=True).relative_to(openssl_root)
            except (ValueError, OSError) as error:
                raise RuntimeError(f"OpenSSL input symlink escapes its frozen prefix: {path}") from error
    version_header = openssl_root / "include/openssl/opensslv.h"
    if not re.search(rf'^\s*#\s*define\s+OPENSSL_VERSION_STR\s+"{re.escape(OPENSSL_VERSION)}"\s*$',
                     version_header.read_text(encoding="utf-8"), re.MULTILINE):
        raise RuntimeError("OpenSSL headers do not match the pinned source version")
    for name in ("ssl.h", "crypto.h", "opensslconf.h", "configuration.h"):
        if not (openssl_root / "include/openssl" / name).is_file():
            raise RuntimeError(f"OpenSSL development header is missing: {name}")
    report = {"sourceArchive": str(source_archive), "sourceArchiveSha256": sha(source_archive),
              "archives": [openssl_archive(prefix / "openssl/lib" / name) for name in OPENSSL_ARCHIVES]}
    return manifest, report


def native_storage(path: Path, label: str, *, writable: bool = False) -> dict:
    """Check the actual mount, including symlinks and not-yet-created paths."""
    path = path.expanduser().resolve()
    existing = path
    while not existing.exists():
        existing = existing.parent
    if not existing.is_dir():
        raise RuntimeError(f"{label} is not a directory: {existing}")
    mounts = json.loads(run(["findmnt", "--json", "--target", existing,
                            "--output", "FSTYPE,SOURCE,TARGET"]))["filesystems"]
    mount = mounts[0]
    if mount["fstype"].lower() in {"9p", "drvfs", "virtiofs", "ntfs", "ntfs3",
                                   "fuseblk", "fuse.ntfs-3g", "cifs", "smb3"}:
        raise RuntimeError(
            f"{label} uses Windows/shared storage ({mount['fstype']}): {path}. "
            "Use the native Linux build directory /opt/codex/engine-gnu-arm64/builds "
            "and keep the Cargo target on Linux.")
    if writable and not os.access(existing, os.W_OK | os.X_OK):
        raise RuntimeError(f"{label} is not writable by the build user: {existing}")
    return {"path": str(path), "filesystem": mount["fstype"],
            "device": mount["source"], "mountpoint": mount["target"]}


def files(root: Path, *, checkout: bool = False) -> list[dict]:
    entries = []
    for path in sorted(root.rglob("*")):
        # A linked Git worktree has one administrative pointer, not build input.
        # Nothing else (including ignored or untracked files) is excluded.
        if checkout and path == root / ".git":
            continue
        if path.is_symlink():
            entries.append({"path": path.relative_to(root).as_posix(), "link": os.readlink(path)})
        elif path.is_file():
            entries.append({"path": path.relative_to(root).as_posix(), "sha256": sha(path),
                            "mode": path.stat().st_mode & 0o777, "bytes": path.stat().st_size})
    return entries


def verified_checkout(checkout: Path, snapshot: Path) -> Path:
    """Reuse Cargo paths only when they exactly reproduce the recovery export."""
    checkout = checkout.expanduser().resolve(strict=True)
    if not (checkout / ".git").is_file():
        raise RuntimeError("--verified-checkout requires a linked Git worktree")
    native_storage(checkout, "Verified source checkout")
    if run(["git", "-C", checkout, "rev-parse", "HEAD"]) != BASE:
        raise RuntimeError("Verified checkout has the wrong upstream base")
    if files(checkout, checkout=True) != files(snapshot):
        raise RuntimeError("Verified checkout differs from the reconstructed recovery export")
    return checkout


def environment(state: dict) -> dict:
    deps = Path(state["dependencies"])
    cargo_home = Path(state["cargoHome"])
    env = dict(os.environ)
    env.update({
        "CARGO_HOME": str(cargo_home), "RUSTUP_HOME": state["rustupHome"],
        "PATH": str(cargo_home / "bin") + os.pathsep + os.environ["PATH"],
        "CARGO_TARGET_DIR": state["targetDirectory"],
        "CARGO_TARGET_AARCH64_UNKNOWN_LINUX_GNU_LINKER": "aarch64-linux-gnu-gcc",
        "CC_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-gcc",
        "CXX_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-g++",
        "AR_aarch64_unknown_linux_gnu": "aarch64-linux-gnu-ar",
        "AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_DIR": str(deps / "openssl"),
        "AARCH64_UNKNOWN_LINUX_GNU_OPENSSL_STATIC": "1",
        "RUSTY_V8_ARCHIVE": state["v8Archive"],
        "RUSTY_V8_SRC_BINDING_PATH": state["v8Binding"],
        "CARGO_NET_GIT_FETCH_WITH_CLI": "true",
    })
    # Do not inherit a different build's V8 mode or cross-target flags.
    for key in ("V8_FROM_SOURCE", "DOCS_RS", "RUSTFLAGS", "CARGO_ENCODED_RUSTFLAGS"):
        if env.get(key):
            raise RuntimeError(f"Ambiguous inherited build override: {key}")
    return env


def prepare(args) -> None:
    sys.dont_write_bytecode = True
    args.dependencies = args.dependencies.expanduser().resolve()
    args.dependency_manifest = args.dependency_manifest.expanduser().resolve()
    dependency_inputs, dependency_checks = dependencies(args.dependencies, args.dependency_manifest)
    args.cargo_home = args.cargo_home.expanduser().resolve(strict=True)
    args.rustup_home = args.rustup_home.expanduser().resolve(strict=True)
    storage = {
        "buildRoot": native_storage(args.build_root, "--build-root", writable=True),
        "targetDirectory": native_storage(args.target_dir, "--target-dir", writable=True),
    }
    args.build_root = Path(storage["buildRoot"]["path"])
    args.target_dir = Path(storage["targetDirectory"]["path"])
    export = PROJECT / "recovery/engine"
    manifest = json.loads((export / "manifest.json").read_text())
    patch = export / manifest["patch"]
    if manifest["base"] != BASE or sha(patch) != manifest["sha256"]:
        raise RuntimeError("Recovery source identity mismatch")
    if run(["git", "-C", args.engine, "rev-parse", "HEAD"]) != BASE:
        raise RuntimeError("Engine repository does not have the pinned base")
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    build = args.build_root / f"{stamp}-{manifest['sha256'][:12]}"
    build.mkdir(parents=True, exist_ok=False)
    evidence = PROJECT / "downloads/engine-gnu-arm64" / build.name
    evidence.mkdir(parents=True, exist_ok=False)
    source = build / "source"
    source.mkdir()
    archive = build / "upstream.tar"
    with archive.open("wb") as stream:
        subprocess.run(["git", "-C", str(args.engine), "-c", "core.autocrlf=false",
                        "-c", "core.eol=lf", "archive", BASE], stdout=stream, check=True)
    with tarfile.open(archive) as stream:
        stream.extractall(source, filter="data")
    # A source snapshot deliberately has no Git index and never modifies the
    # live worktree's index. Apply exactly the full-index binary recovery patch.
    shutil.copyfile(patch, evidence / "engine.patch")
    # A snapshot under this project's work/ directory has no Git repository of
    # its own. Stop parent discovery so git apply uses the snapshot, rather
    # than interpreting paths relative to Codex's enclosing checkout.
    patch_environment = dict(os.environ, GIT_CEILING_DIRECTORIES=str(source.parent))
    for options in (["--check"], []):
        subprocess.run(["git", "apply", *options, str(evidence / "engine.patch")],
                       cwd=source, env=patch_environment, check=True)
    save(evidence / "recovery-manifest.json", manifest)
    save(evidence / "SOURCES.json", files(source))
    canonical_source = source
    if args.verified_checkout:
        source = verified_checkout(args.engine, canonical_source)

    # Reuse the official source-package verifier, retaining archive and binding
    # together. Cached downloads are rechecked against upstream's SHA manifest.
    os.environ["CODEX_REPO_ROOT"] = str(source)
    sys.path.insert(0, str(source / "scripts"))
    from codex_package.targets import TARGET_SPECS
    from codex_package.v8 import fetch_codex_v8_artifacts
    v8 = fetch_codex_v8_artifacts(TARGET_SPECS[TARGET], cache_root=PROJECT / "downloads/engine-v8")
    # Fetching V8 may take time. Do not freeze a changed dependency prefix as
    # though it still matched the reviewed archive hashes checked above.
    current_inputs, current_checks = dependencies(args.dependencies, args.dependency_manifest)
    if current_inputs != dependency_inputs or current_checks != dependency_checks:
        raise RuntimeError("Reviewed OpenSSL inputs changed during preparation")
    save(evidence / "DEPENDENCY-INPUTS.json", dependency_inputs)
    save(evidence / "DEPENDENCY-CHECKS.json", dependency_checks)
    save(evidence / "DEPENDENCIES.json", files(args.dependencies / "openssl"))
    state = {
        "schema": "codex.gnu-engine-build.v1", "sourceBase": BASE,
        "patchSha256": manifest["sha256"], "target": TARGET, "profile": "release",
        "source": str(source), "evidence": str(evidence), "build": str(build),
        "sourceMode": "verified-checkout" if args.verified_checkout else "frozen-snapshot",
        "canonicalSource": str(canonical_source),
        "dependencies": str(args.dependencies), "targetDirectory": str(args.target_dir),
        "cargoHome": str(args.cargo_home), "rustupHome": str(args.rustup_home),
        "v8Archive": str(v8.archive), "v8ArchiveSha256": sha(v8.archive),
        "v8Binding": str(v8.binding), "v8BindingSha256": sha(v8.binding),
        "sourceManifestSha256": sha(evidence / "SOURCES.json"),
        "dependencyManifestSha256": sha(evidence / "DEPENDENCIES.json"),
        "dependencyInputsSha256": sha(evidence / "DEPENDENCY-INPUTS.json"),
        "dependencyChecksSha256": sha(evidence / "DEPENDENCY-CHECKS.json"),
        "upstreamArchiveSha256": sha(archive),
        "builderSha256": sha(Path(__file__)), "androidExecution": False,
        "buildCompleted": False, "packageCompleted": False,
        "storage": storage,
    }
    env = environment(state)
    cwd = source / "codex-rs"
    probes = {}
    for name, command in {
        "rustc": ["rustc", "-vV"], "cargo": ["cargo", "-vV"],
        "targets": ["rustup", "target", "list", "--installed"],
        "gcc": ["aarch64-linux-gnu-gcc", "--version"],
        "gxx": ["aarch64-linux-gnu-g++", "--version"],
        "readelf": ["aarch64-linux-gnu-readelf", "--version"],
    }.items():
        probes[name] = run(command, cwd=cwd, env=env)
    if TARGET not in probes["targets"].splitlines():
        raise RuntimeError(f"Install the pinned Rust toolchain target {TARGET} before building")
    save(evidence / "toolchain.json", probes)
    shutil.copyfile(__file__, evidence / "build-gnu-engine.py")
    save(evidence / "build-state.json", state)
    print(evidence / "build-state.json")


def validate(state: dict) -> Path:
    evidence = Path(state["evidence"])
    if state["schema"] != "codex.gnu-engine-build.v1" or state["sourceBase"] != BASE:
        raise RuntimeError("Unsupported build identity")
    if sha(Path(__file__)) != state["builderSha256"]:
        raise RuntimeError("Builder changed since preparation; use the preserved builder or prepare again")
    for name, key in (("SOURCES.json", "sourceManifestSha256"),
                      ("DEPENDENCIES.json", "dependencyManifestSha256"),
                      ("DEPENDENCY-INPUTS.json", "dependencyInputsSha256"),
                      ("DEPENDENCY-CHECKS.json", "dependencyChecksSha256")):
        if sha(evidence / name) != state[key]:
            raise RuntimeError(f"Manifest changed: {name}")
    source = Path(state["source"])
    is_checkout = state.get("sourceMode") == "verified-checkout"
    if is_checkout and run(["git", "-C", source, "rev-parse", "HEAD"]) != BASE:
        raise RuntimeError("Verified checkout base changed")
    if files(source, checkout=is_checkout) != json.loads((evidence / "SOURCES.json").read_text()):
        raise RuntimeError("Frozen source changed")
    if is_checkout and files(Path(state["canonicalSource"])) != json.loads((evidence / "SOURCES.json").read_text()):
        raise RuntimeError("Canonical recovery snapshot changed")
    if files(Path(state["dependencies"]) / "openssl") != json.loads((evidence / "DEPENDENCIES.json").read_text()):
        raise RuntimeError("OpenSSL inputs changed")
    for key in ("v8Archive", "v8Binding"):
        if sha(Path(state[key])) != state[key + "Sha256"]:
            raise RuntimeError(f"V8 input changed: {key}")
    return evidence


def build(args, state: dict) -> None:
    # Check again: a mount or symlink can change after source preparation.
    native_storage(Path(state["source"]), "Build source")
    native_storage(Path(state["build"]), "Build directory", writable=True)
    native_storage(Path(state["targetDirectory"]), "Cargo target", writable=True)
    evidence = validate(state)
    # A unique log retains each attempt, including interrupted or failed builds.
    with tempfile.NamedTemporaryFile(prefix="build-", suffix=".log", dir=evidence, delete=False) as log:
        command = ["cargo", "build", "--locked", "--target", TARGET, "--release", "--timings",
                   "-p", "codex-cli", "--bin", "codex", "-p", "codex-code-mode-host", "--bin", "codex-code-mode-host"]
        if args.jobs is not None:
            command += ["--jobs", str(args.jobs)]
        print(f"Building; log: {log.name}", flush=True)
        result = subprocess.run(command, cwd=Path(state["source"]) / "codex-rs",
                                env=environment(state), stdout=log, stderr=subprocess.STDOUT)
    state.update(buildCompleted=result.returncode == 0, buildExitCode=result.returncode,
                 buildLog=log.name, buildCommand=command)
    if result.returncode == 0:
        validate(state)
        # Snapshot outputs while this build still owns their provenance. A
        # later build can reuse the shared Cargo target without changing them.
        artifacts = Path(state["build"]) / "unstripped"
        artifacts.mkdir(exist_ok=False)
        for name in BINARIES:
            shutil.copy2(Path(state["targetDirectory"]) / TARGET / "release" / name, artifacts / name)
        state["builtBinaries"] = files(artifacts)
    save(args.state, state)
    if result.returncode:
        raise SystemExit(result.returncode)


def archive_directory(root: Path, destination: Path) -> None:
    """Archive fixed inputs in stable order with normalized metadata."""
    with destination.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w") as output:
            for path in sorted(root.rglob("*")):
                entry = output.gettarinfo(str(path), arcname=path.relative_to(root).as_posix())
                entry.uid = entry.gid = entry.mtime = 0
                entry.uname = entry.gname = ""
                if path.is_file():
                    with path.open("rb") as stream:
                        output.addfile(entry, stream)
                else:
                    output.addfile(entry)


def package(args, state: dict) -> None:
    evidence = validate(state)
    built = Path(state["build"]) / "unstripped"
    if not state["buildCompleted"] or files(built) != state["builtBinaries"]:
        raise RuntimeError("No matching successful build to package")
    stage = Path(state["build"]) / "package"
    stage.mkdir(exist_ok=False)
    symbols = Path(state["build"]) / "symbols"
    symbols.mkdir()
    for name in BINARIES:
        output, debug = stage / name, symbols / f"{name}.debug"
        shutil.copy2(built / name, output)
        subprocess.run(["aarch64-linux-gnu-objcopy", "--only-keep-debug", str(output), str(debug)], check=True)
        subprocess.run(["aarch64-linux-gnu-strip", "--strip-unneeded", str(output)], check=True)
        subprocess.run(["aarch64-linux-gnu-objcopy", f"--add-gnu-debuglink={debug}", str(output)], check=True)
    subprocess.run([sys.executable, str(PROJECT / "tools/executor/check-gnu-engine-elf.py"),
                    "--binaries", str(stage), "--libraries", str(args.libraries),
                    "--output", str(evidence / "static-compatibility.json")], check=True)
    for name in ("SOURCES.json", "recovery-manifest.json", "engine.patch", "static-compatibility.json",
                 "DEPENDENCY-INPUTS.json", "DEPENDENCY-CHECKS.json", "DEPENDENCIES.json"):
        shutil.copyfile(evidence / name, stage / name)
    package_files = files(stage)
    save(stage / "manifest.json", {"kind": "separate-gnu-engine-payload", "target": TARGET,
        "sourceBase": BASE, "patchSha256": state["patchSha256"], "files": package_files,
        "androidExecution": False, "liveUiQualified": False,
        "cliContract": "codex app-server [arguments]; native runtime requires production launcher injection"})
    # Symbols are preserved separately, outside the phone payload.
    save(evidence / "SYMBOLS.json", {"directory": str(symbols), "files": files(symbols)})
    archive = evidence / "codex-gnu-engine-aarch64.tar.gz"
    symbol_archive = evidence / "codex-gnu-engine-aarch64-symbols.tar.gz"
    archive_directory(stage, archive)
    archive_directory(symbols, symbol_archive)
    (evidence / "SHA256SUMS").write_text(
        f"{sha(archive)}  {archive.name}\n{sha(symbol_archive)}  {symbol_archive.name}\n")
    state.update(packageCompleted=True, package=str(archive), packageSha256=sha(archive))
    save(args.state, state)
    print(archive)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("prepare", "build", "package"))
    parser.add_argument("--engine", type=Path, default=PROJECT / "work/worktrees/CodexEngine")
    parser.add_argument("--verified-checkout", action="store_true",
                        help="Build in --engine only after an exact comparison with the reconstructed recovery export")
    parser.add_argument("--build-root", type=Path, default=Path("/opt/codex/engine-gnu-arm64/builds"))
    parser.add_argument("--dependencies", type=Path, default=Path("/opt/codex/engine-gnu-arm64/deps"))
    parser.add_argument("--dependency-manifest", type=Path,
                        help="Reviewed OpenSSL source/archive hashes and GNU ARM64 build identity; required for prepare")
    parser.add_argument("--target-dir", type=Path, default=Path("/opt/codex/engine-gnu-arm64/target"))
    parser.add_argument("--cargo-home", type=Path,
                        default=Path(os.environ.get("CARGO_HOME", Path.home() / ".cargo")),
                        help="Explicit Cargo installation/cache; frozen into the build state")
    parser.add_argument("--rustup-home", type=Path,
                        default=Path(os.environ.get("RUSTUP_HOME", Path.home() / ".rustup")),
                        help="Explicit Rustup toolchain installation; frozen into the build state")
    parser.add_argument("--libraries", type=Path, default=PROJECT / "downloads/engine-arm64-device-libs-20260907")
    parser.add_argument("--state", type=Path)
    parser.add_argument("--jobs", type=int)
    args = parser.parse_args()
    if args.action == "prepare" and args.dependency_manifest is None:
        parser.error("--dependency-manifest is required for prepare; see tools/executor/gnu-engine-build.md")
    if sys.platform != "linux" or os.getuid() == 0:
        parser.error("Run on the Linux build host as an unprivileged user")
    if args.jobs is not None and args.jobs < 1:
        parser.error("--jobs must be positive")
    if args.action == "prepare":
        prepare(args)
    else:
        if args.state is None:
            parser.error("--state is required for build/package")
        globals()[args.action](args, json.loads(args.state.read_text()))


if __name__ == "__main__":
    main()
