#!/usr/bin/env python3
"""Build a co-installed Codex debug APK that verifies the PRoot launch fix.

Unlike ``manual-full-apk.yml`` this never reads a maintainer signing secret and
never replays the retired ``ci-native-baseline-v60`` release. It recovers the
*unchanged* native and asset payload from a pinned public release, rewrites only
the owning application id, and assembles a debug APK signed with a throwaway
key. The result installs beside the existing app; it cannot update it.

Stages
    recover    verify the base APK, extract the payload, rewrite the app id
    toolchain  install Android SDK platform/build-tools/NDK/CMake and Gradle
    build      run the Gradle assembleRelease with explicit payload inputs
    verify     read the produced APK back: app id, signature, payload wiring

Every stage writes its own log under ``work/coinstall/logs`` and refuses to
continue when a pinned digest differs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "coinstall"
PAYLOAD = WORK / "payload"
OUT = WORK / "out"
BASE_VERSION = "v85"
# Pinned from the published asset digest; a different APK is refused.
BASE_APK_SHA256 = "d07eec662cfac91486468610b7eea6f16cc96f1ea1c9ba841652c44cf695cf74"
# The admission binary compiles against OpenSSL's headers. Both values are the
# pins stage-android-python.py already uses for the official Python runtime.
OPENSSL_SHA256 = "a8c0d28a529ca480f9f36cf5792e2cd21984552a3c8e4aa11a24aa31aeac98e8"
OPENSSL_URL = "https://github.com/openssl/openssl/releases/download/openssl-3.5.7/openssl-3.5.7.tar.gz"
# The interpreter entry bakes its deployment prefix in at build time. These are
# the same official inputs stage-android-python.py pins.
PYTHON_VERSION = "3.14.7"
PYTHON_PACKAGE = "python-" + PYTHON_VERSION + "-aarch64-linux-android.tar.gz"
PYTHON_SHA256 = "6d50cc3aa66e414a439594089bcdfb5f1264358155c70c1f00471c24cfb477fb"
PYTHON_URL = "https://www.python.org/ftp/python/" + PYTHON_VERSION + "/" + PYTHON_PACKAGE
GRADLE_VERSION = "9.7.1"
NDK_VERSION = "29.0.14206865"
CMAKE_VERSION = "3.22.1"
BUILD_TOOLS = "36.0.0"
SDK_PLATFORM = "android-37.0"
# The installed platform's own API level decides whether the system applies the
# zygote seccomp filter; targeting above it disables the filter, and the packaged
# native executor requires it.
TARGET_SDK = "35"
RUNTIME_LIBS = (
    "libproot.so", "libproot-loader.so", "libproot-loader32.so",
    "libtalloc.so", "libandroid-shmem.so",
)
# Named in the app's loader but owned by the shizukuTransport module, so the
# executor inventory must exclude them exactly as build.gradle does.
TRANSPORT_LIBS = {"libcodex_shizuku_transport.so", "libcodex_bionic_cwd.so"}


def log(stage, message):
    directory = WORK / "logs"
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / (stage + ".log")).open("a", encoding="utf-8") as stream:
        stream.write(message.rstrip() + "\n")
    print(message, flush=True)


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def fetch(url: str, destination: Path, *, expected: str | None = None, limit=2 * 1024**3) -> Path:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or (expected and digest(destination) != expected):
        request = urllib.request.Request(url, headers={"User-Agent": "codex-coinstall"})
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as stream:
            size = 0
            while True:
                chunk = response.read(1 << 20)
                if not chunk:
                    break
                size += len(chunk)
                if size > limit:
                    raise SystemExit("Download exceeds its bound: " + url)
                stream.write(chunk)
    if expected and digest(destination) != expected:
        raise SystemExit("Downloaded digest differs from the pinned value: " + url)
    return destination


def run(stage, argv, *, cwd=ROOT, env=None):
    log(stage, "$ " + " ".join(map(str, argv)))
    process = subprocess.run(list(map(str, argv)), cwd=cwd, env=env,
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if process.stdout:
        log(stage, process.stdout)
    if process.returncode:
        raise SystemExit(f"{stage} failed with exit {process.returncode}; see work/coinstall/logs/{stage}.log")
    return process.stdout


# --------------------------------------------------------------------------- recover

def extract_payload(apk: Path):
    for directory in (PAYLOAD / "runtime-five" / "arm64-v8a",
                      PAYLOAD / "executor-jni" / "arm64-v8a",
                      PAYLOAD / "executor-assets"):
        directory.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(apk) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise SystemExit("Base APK has duplicate entries")
        libraries = {}
        for name in names:
            if name.startswith("lib/arm64-v8a/") and name.endswith(".so"):
                libraries[Path(name).name] = archive.read(name)
        assets = 0
        # The complete first-install image lives under phone-runtime/ and is
        # handed to Gradle as its own input directory, not as an app asset.
        image = PAYLOAD / "phone-image" / "phone-runtime"
        image.mkdir(parents=True, exist_ok=True)
        image_members = 0
        skip = ("assets/phone-runtime/", "assets/desktop-client/", "assets/gnu-engine/")
        for name in names:
            if not name.startswith("assets/") or name.endswith("/"):
                continue
            if name.startswith("assets/phone-runtime/"):
                # Gradle renames the archive to .tgz itself (AGP would otherwise
                # expand a .gz asset); the staged input must keep its true name.
                relative = name[len("assets/"):].replace(
                    "phone-runtime/codex-phone-rootfs.tgz",
                    "phone-runtime/codex-phone-rootfs.tar.gz")
                target = PAYLOAD / "phone-image" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
                image_members += 1
                continue
            if name.startswith(skip):
                continue
            relative = name[len("assets/"):]
            target = PAYLOAD / "executor-assets" / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(archive.read(name))
            assets += 1
    deployment = json.loads((PAYLOAD / "executor-assets" / "codex-executor-deployment.json").read_text())
    needed = set(deployment["nativeLibraries"]) - TRANSPORT_LIBS
    missing = [n for n in RUNTIME_LIBS + tuple(sorted(needed)) if n not in libraries]
    if missing:
        raise SystemExit("Base APK lacks expected libraries: " + ", ".join(map(str, missing)))
    for name in RUNTIME_LIBS:
        (PAYLOAD / "runtime-five" / "arm64-v8a" / name).write_bytes(libraries[name])
    # The transport libraries are rebuilt by the :shizukuTransport module, but
    # the deployment inventory pins the *published* bytes. Stage the published
    # copies so the packaged APK matches its own inventory instead of failing
    # admission with "Packaged native library digest mismatch".
    transport_dir = PAYLOAD / "transport-jni" / "arm64-v8a"
    transport_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted(TRANSPORT_LIBS):
        if name not in libraries:
            raise SystemExit("Base APK lacks " + name)
        (transport_dir / name).write_bytes(libraries[name])
    for name in needed:
        if name in ("libcodex_app_transport.so", "libcodex_app_bootstrap.so"):
            # Both are compiled from source here. The transport embeds this build's
            # admission policy; the bootstrap embeds the installed application id
            # (its private data root), so reusing the published copy would keep
            # pointing at the original package's directory.
            continue
        (PAYLOAD / "executor-jni" / "arm64-v8a" / name).write_bytes(libraries[name])
    # libXlorie.so is produced by the :lorie CMake project, which the co-installed
    # build does not rebuild. Reuse the published bytes so the app can load it.
    if "libXlorie.so" not in libraries:
        raise SystemExit("Base APK lacks libXlorie.so")
    (PAYLOAD / "runtime-five" / "arm64-v8a" / "libXlorie.so").write_bytes(libraries["libXlorie.so"])
    log("recover", json.dumps({"assets": assets, "libraries": len(libraries),
                               "executorJni": len(needed), "imageFiles": image_members},
                              indent=2))
    if image_members == 0:
        raise SystemExit("Base APK carries no first-install image")
    return deployment


def recover():
    package_id = os.environ.get("PACKAGE_ID") or "com.ai.codex.dev"
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", package_id):
        raise SystemExit("Invalid application id: " + package_id)
    if package_id == "com.ai.codex":
        raise SystemExit("The co-installed build must use a new application id")
    version = os.environ.get("BASE_VERSION") or BASE_VERSION
    url = ("https://github.com/JinShichang/codex-desktop-android/releases/download/"
           + version + "/Codex-Android-" + version + "-full.apk")
    apk = fetch(url, WORK / "base" / f"{version}.apk", expected=BASE_APK_SHA256)
    log("recover", "Base APK verified: " + BASE_APK_SHA256)
    extract_payload(apk)
    # Reviewed sources replace the recovered ones before the id rewrite, so the
    # rewrite refreshes the manifest digests over the code that will ship.
    sync_source_assets()
    run("recover", [sys.executable, "-B", ROOT / "tools" / "workstation" / "rewrite-application-id.py",
                    "--assets", PAYLOAD / "executor-assets",
                    "--from", "com.ai.codex", "--to", package_id])
    # The Python runtime inventory pins its own digest inside the deployment
    # asset, so re-verify the pair after the rewrite.
    deployment = json.loads((PAYLOAD / "executor-assets" / "codex-executor-deployment.json").read_text())
    manifest = PAYLOAD / "executor-assets" / deployment["pythonRuntime"]["manifestAsset"]
    if digest(manifest) != deployment["pythonRuntime"]["manifestSha256"]:
        raise SystemExit("Rewritten Python runtime manifest does not match its declared digest")
    if deployment["packageName"] != package_id:
        raise SystemExit("Deployment asset still names the original package")
    (WORK / "state.json").write_text(json.dumps({
        "packageId": package_id, "baseVersion": version, "baseApkSha256": BASE_APK_SHA256,
    }, indent=2) + "\n", encoding="utf-8")


# ------------------------------------------------------------------------- toolchain

def toolchain():
    sdk = WORK / "android-sdk"
    sdk.mkdir(parents=True, exist_ok=True)
    tools = sdk / "cmdline-tools"
    manager = tools / "latest" / "bin" / "sdkmanager"
    if not manager.is_file():
        metadata = fetch("https://dl.google.com/android/repository/repository2-1.xml",
                         WORK / "downloads" / "repository.xml", limit=16 * 1024**2)
        # Resolve the archive from Google's own manifest instead of guessing a
        # filename: select the linux archive of cmdline-tools;latest only, then
        # verify both its published checksum and size.
        import xml.etree.ElementTree as ElementTree
        tree = ElementTree.fromstring(metadata.read_bytes())
        package = next((p for p in tree.findall("remotePackage")
                        if p.attrib.get("path") == "cmdline-tools;latest"), None)
        if package is None:
            raise SystemExit("Repository manifest has no cmdline-tools;latest package")
        archive_node = next((a for a in package.findall("archives/archive")
                             if a.findtext("host-os") == "linux"), None)
        if archive_node is None:
            raise SystemExit("cmdline-tools;latest has no linux archive")
        complete = archive_node.find("complete")
        name = complete.findtext("url")
        checksum = complete.find("checksum")
        size = int(complete.findtext("size"))
        if not name or checksum is None:
            raise SystemExit("cmdline-tools;latest archive is incomplete")
        algorithm = checksum.attrib.get("type", "sha1").replace("-", "").lower()
        archive = fetch("https://dl.google.com/android/repository/" + name,
                        WORK / "downloads" / name)
        if archive.stat().st_size != size:
            raise SystemExit("Command-line tools size differs from repository metadata")
        actual = hashlib.new(algorithm, archive.read_bytes()).hexdigest()
        if actual != checksum.text.strip():
            raise SystemExit("Command-line tools checksum differs from repository metadata")
        # Extract away from the SDK root: the archive may itself be named
        # cmdline-tools, so unpacking in place would try to move a directory
        # into its own child.
        staging = WORK / "downloads" / "cmdline-tools-unpacked"
        if staging.exists():
            shutil.rmtree(staging)
        staging.mkdir(parents=True)
        with zipfile.ZipFile(archive) as zipped:
            for entry in zipped.namelist():
                path = Path(entry)
                if path.is_absolute() or ".." in path.parts:
                    raise SystemExit("Unexpected archive member: " + entry)
            zipped.extractall(staging)
        roots = [d for d in staging.iterdir() if d.is_dir() and (d / "bin" / "sdkmanager").is_file()]
        if len(roots) != 1:
            raise SystemExit("Command-line tools archive has an unexpected layout")
        tools.mkdir(parents=True, exist_ok=True)
        shutil.move(str(roots[0]), str(tools / "latest"))
        shutil.rmtree(staging)
        for executable in (tools / "latest" / "bin").iterdir():
            executable.chmod(0o755)
        manager = tools / "latest" / "bin" / "sdkmanager"
    environment = dict(os.environ, ANDROID_HOME=str(sdk), ANDROID_SDK_ROOT=str(sdk),
                       JAVA_HOME=os.environ["JAVA_HOME"])
    for executable in (tools / "latest" / "bin").iterdir():
        executable.chmod(0o755)
    accept = subprocess.run([str(manager), f"--sdk_root={sdk}", "--licenses"],
                            input="y\n" * 200, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, env=environment)
    log("toolchain", accept.stdout or "licenses accepted")
    run("toolchain", [manager, f"--sdk_root={sdk}",
                      f"platforms;{SDK_PLATFORM}", f"build-tools;{BUILD_TOOLS}",
                      f"ndk;{NDK_VERSION}", f"cmake;{CMAKE_VERSION}"], env=environment)

    gradle = WORK / "gradle" / f"gradle-{GRADLE_VERSION}"
    if not (gradle / "bin" / "gradle").is_file():
        base = f"https://services.gradle.org/distributions/gradle-{GRADLE_VERSION}-bin.zip"
        checksum = fetch(base + ".sha256", WORK / "downloads" / "gradle.sha256", limit=1024)
        expected = checksum.read_text().strip().split()[0]
        archive = fetch(base, WORK / "downloads" / f"gradle-{GRADLE_VERSION}-bin.zip",
                        expected=expected)
        with zipfile.ZipFile(archive) as zipped:
            zipped.extractall(WORK / "gradle")
        (gradle / "bin" / "gradle").chmod(0o755)
    (WORK / "env.json").write_text(json.dumps({
        "sdk": str(sdk), "gradle": str(gradle / "bin" / "gradle"),
    }, indent=2) + "\n", encoding="utf-8")
    log("toolchain", "Android SDK, NDK, CMake and Gradle are ready")


# --------------------------------------------------------------------------- build

def record_transport_digest_from_apk(apk: Path) -> bool:
    """Make the deployment inventory describe what the APK actually ships.

    libcodex_app_transport.so is compiled from source, and a Gradle library's
    debug and release variants do not produce identical bytes, so a digest read
    from ``:shizukuTransport:assembleDebug`` never matched the library that the
    application's ``assembleRelease`` packaged. Admission then rejected every
    launch with "Packaged native library digest mismatch" -- which is exactly what
    the first device run after the dumpable fix reported.

    Reading the library back out of the produced APK removes the guesswork: the
    inventory is written from the packaged bytes themselves. Returns True when the
    inventory had to change, so the caller repackages once; the native output is
    already up to date by then, so the library bytes stay identical.
    """
    name = "libcodex_app_transport.so"
    with zipfile.ZipFile(apk) as archive:
        member = "lib/arm64-v8a/" + name
        if member not in archive.namelist():
            raise SystemExit("Produced APK lacks " + member)
        actual = hashlib.sha256(archive.read(member)).hexdigest()
    deployment_path = PAYLOAD / "executor-assets" / "codex-executor-deployment.json"
    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    if deployment["nativeLibraries"].get(name) == actual:
        log("build", "packaged " + name + " digest matches the inventory")
        return False
    deployment["nativeLibraries"][name] = actual
    deployment_path.write_text(json.dumps(deployment, indent=2, sort_keys=True) + "\n",
                               encoding="utf-8")
    log("build", "recorded packaged digest for " + name + ": " + actual)
    # The qualification record pins the deployment digest, so refresh the chain.
    package_id = json.loads((WORK / "state.json").read_text())["packageId"]
    run("build", [sys.executable, "-B", ROOT / "tools" / "workstation"
                  / "rewrite-application-id.py", "--assets", PAYLOAD / "executor-assets",
                  "--from", "com.ai.codex", "--to", package_id])
    return True


# Executor Python modules this build modifies. They ship inside the APK assets, so
# a payload recovered from the published APK carries the published copies; the
# local sources must replace them or the fix never reaches the device.
# (payload-relative asset path, reviewed source path). The entry modules live in
# the transport module's assets; shared executor modules live under tools/executor.
SOURCE_SYNCED_ASSETS = (
    ("codex-executor/codex_app_bootstrap.py",
     ROOT / "tools" / "executor" / "shizuku-service" / "transport" / "src" / "main"
     / "assets" / "codex-executor" / "codex_app_bootstrap.py"),
    ("codex-executor/codex_native_bootstrap.py",
     ROOT / "tools" / "executor" / "shizuku-service" / "transport" / "src" / "main"
     / "assets" / "codex-executor" / "codex_native_bootstrap.py"),
    ("codex-executor/tools/executor/native_session_recovery.py",
     ROOT / "tools" / "executor" / "native_session_recovery.py"),
)


def sync_source_assets() -> None:
    """Replace recovered executor modules with this checkout's reviewed sources.

    recover() extracts the published APK verbatim, so editing a module here would
    otherwise have no effect: the packaged asset would still be the upstream copy.
    """
    synced = []
    for relative, source in SOURCE_SYNCED_ASSETS:
        if not source.is_file():
            raise SystemExit("Missing reviewed executor source: " + str(source))
        target = PAYLOAD / "executor-assets" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.is_file() or target.read_bytes() != source.read_bytes():
            shutil.copy2(source, target)
            synced.append(relative)
    if synced:
        log("recover", "synced reviewed executor sources: " + ", ".join(synced))


def python_prefix() -> Path:
    """Provide the official CPython Android prefix for rebuilding the CLI.

    libcodex_python_cli.so bakes its deployment prefix in at build time:
    PYTHONHOME is ignored under -I, so CODEX_PYTHON_HOME is the only source. The
    published library names /data/user/0/com.ai.codex, which a co-installed build
    cannot reach, and the packaged assets carry only lib/ (no include/ and no
    libpython3.14.so). So the CLI is rebuilt against the official release archive,
    whose SHA-256 is already pinned by stage-android-python.py.
    """
    prefix = WORK / "python-prefix"
    stamp = prefix / ".complete"
    if stamp.is_file():
        return prefix
    archive = fetch(PYTHON_URL, WORK / "downloads" / PYTHON_PACKAGE, expected=PYTHON_SHA256)
    if prefix.exists():
        shutil.rmtree(prefix)
    prefix.mkdir(parents=True)
    with tarfile.open(archive) as tar:
        for member in tar.getmembers():
            # Members are "./prefix/<path>"; keep only the prefix subtree.
            name = member.name[2:] if member.name.startswith("./") else member.name
            if not name.startswith("prefix/"):
                continue
            member.name = name[len("prefix/"):]
            if not member.name:
                continue
            tar.extract(member, prefix, filter="data")
    for required in (prefix / "include" / "python3.14" / "Python.h",
                     prefix / "lib" / "libpython3.14.so"):
        if not required.is_file():
            raise SystemExit("Official CPython prefix lacks " + str(required.name))
    stamp.write_text("ok\n", encoding="utf-8")
    log("bootstrap", "prepared official CPython prefix")
    return prefix


def build_python_cli(package_id: str) -> None:
    """Rebuild the interpreter entry so its baked-in prefix matches this build."""
    env_json = json.loads((WORK / "env.json").read_text())
    sdk = Path(env_json["sdk"])
    runtime_home = "/data/user/0/" + package_id + "/files/native-runtime-v1/python"
    environment = dict(os.environ, ANDROID_NDK_HOME=str(sdk / "ndk" / NDK_VERSION))
    # Third argument: the verified official archive. Without it the script looks in
    # downloads/native-python/inputs, which this CI does not populate.
    archive = fetch(PYTHON_URL, WORK / "downloads" / PYTHON_PACKAGE, expected=PYTHON_SHA256)
    run("bootstrap", ["bash", str(ROOT / "tools" / "executor" / "bionic-runtime"
                      / "build-python-cli.sh"), str(python_prefix()), runtime_home,
                      str(archive)],
        env=environment)
    # build-python-cli.sh writes into a mktemp tree under repo/work and prints it.
    produced = sorted(ROOT.glob("work/codex-bionic-python-*/libcodex_python_cli.so"),
                      key=lambda p: p.stat().st_mtime)
    if not produced:
        raise SystemExit("Python CLI rebuild produced no library")
    target = PAYLOAD / "executor-jni" / "arm64-v8a" / "libcodex_python_cli.so"
    shutil.copy2(produced[-1], target)
    record_name = "libcodex_python_cli.so"
    deployment_path = PAYLOAD / "executor-assets" / "codex-executor-deployment.json"
    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    actual = digest(target)
    if deployment["nativeLibraries"].get(record_name) != actual:
        deployment["nativeLibraries"][record_name] = actual
        if deployment.get("pythonLibrary") == record_name:
            deployment["pythonSha256"] = actual
        deployment_path.write_text(json.dumps(deployment, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
        run("build", [sys.executable, "-B", ROOT / "tools" / "workstation"
                      / "rewrite-application-id.py", "--assets", PAYLOAD / "executor-assets",
                      "--from", "com.ai.codex", "--to", package_id])
    log("build", "rebuilt " + record_name + " for " + runtime_home)


def openssl_prefix() -> Path:
    """Provide the OpenSSL headers native-bootstrap.c compiles against.

    build-bootstrap-windows.py expects an official OpenSSL prefix (-I<prefix>/include);
    upstream produces it on a Windows workstation, so it never existed in this Linux
    CI. Taking it from the published APK is impossible: assets/bionic-python ships
    lib/ but no include/. So the headers come from OpenSSL's own pinned release,
    which stage-android-python.py already pins by SHA-256.

    Only headers are needed: the admission binary links the already-packaged
    libcrypto_python.so and uses nothing beyond EVP_* SHA-256. Generated headers
    (opensslv.h, safestack.h, configuration.h, ...) are produced with the same
    Perl rules the OpenSSL Makefile uses, so no compiler or make is required.
    """
    prefix = WORK / "openssl-prefix"
    stamp = prefix / ".complete"
    if stamp.is_file():
        return prefix
    source = WORK / "openssl-source"
    if not (source / "Configure").is_file():
        archive = fetch(OPENSSL_URL, WORK / "downloads" / "openssl.tar.gz", expected=OPENSSL_SHA256)
        if source.exists():
            shutil.rmtree(source)
        source.mkdir(parents=True)
        with tarfile.open(archive) as tar:
            # The release tarball is rooted at openssl-<version>/; strip it so
            # Configure sees its own source tree.
            for member in tar.getmembers():
                parts = member.name.split("/", 1)
                if len(parts) != 2 or not parts[1]:
                    continue
                member.name = parts[1]
                tar.extract(member, source, filter="data")
    # Configure writes configuration.h and configdata.pm; a generic target is
    # enough because only declarations are consumed, never compiled OpenSSL code.
    subprocess.run(["perl", "./Configure", "linux-aarch64", "no-tests", "no-apps", "no-docs"],
                   cwd=source, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, check=True)
    # Every *.h.in is rendered by the same dofile generator the Makefile calls.
    rendered = 0
    for template in sorted((source / "include" / "openssl").glob("*.h.in")):
        result = subprocess.run(["perl", "-I.", "-Mconfigdata", "util/dofile.pl", "-oMakefile",
                                 str(template.relative_to(source))],
                                cwd=source, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        if result.returncode == 0 and result.stdout:
            template.with_suffix("").write_text(result.stdout, encoding="utf-8")
            rendered += 1
    if not (source / "include" / "openssl" / "opensslv.h").is_file():
        raise SystemExit("OpenSSL header generation produced no opensslv.h")
    if prefix.exists():
        shutil.rmtree(prefix)
    shutil.copytree(source / "include", prefix / "include")
    stamp.write_text(str(rendered) + "\n", encoding="utf-8")
    log("bootstrap", "prepared OpenSSL headers (" + str(rendered) + " generated)")
    return prefix


def build_bootstrap(package_id: str) -> None:
    """Compile the application bootstrap with this build's own package id.

    The published libcodex_app_bootstrap.so hard-codes the original package's
    private data root, so a co-installed build fails its check with
    NativeAdmissionError "arguments" (errno 22) before Python ever starts.
    Rebuilding it with -DCODEX_PACKAGE_ID makes the admission accept the actual
    data directory.
    """
    runtime = json.loads((PAYLOAD / "executor-assets" / "codex-python-runtime.json").read_text())
    inventory = WORK / "bootstrap-inventory"
    inventory.mkdir(parents=True, exist_ok=True)
    lines = ["/* Authenticated production inputs; the admission binary is hashed separately. */",
             "static const struct runtime_file runtime_files[] = {"]
    lines += ["    {%s, %d, %s}," % (json.dumps(item["path"]), item["bytes"], json.dumps(item["sha256"]))
              for item in runtime["dataFiles"]]
    lines += ["};", "static const struct runtime_alias runtime_aliases[] = {"]
    lines += ["    {%s, %s}," % (json.dumps(item["path"]), json.dumps(item["nativeLibrary"]))
              for item in runtime["runtimeAliases"]]
    lines += ["};", "static const struct runtime_file native_files[] = {"]
    lines += ["    {%s, %d, %s}," % (json.dumps(item["name"]), item["bytes"], json.dumps(item["sha256"]))
              for item in runtime["nativeFiles"]]
    lines += ["};", ""]
    (inventory / "runtime-inventory.h").write_text("\n".join(lines), encoding="ascii")

    env_json = json.loads((WORK / "env.json").read_text())
    sdk = Path(env_json["sdk"])
    ndk = sdk / "ndk" / NDK_VERSION
    libraries = PAYLOAD / "executor-jni" / "arm64-v8a"
    output = WORK / "bootstrap-build"
    if output.exists():
        shutil.rmtree(output)
    run("bootstrap", [sys.executable, "-B", ROOT / "tools" / "executor" / "runas-runtime"
                      / "build-bootstrap-windows.py", "--ndk", str(ndk),
                      "--prefix", str(openssl_prefix()), "--inventory", str(inventory / "runtime-inventory.h"),
                      "--libraries", str(libraries), "--output", str(output),
                      "--launch-origin", "android-app", "--package-id", package_id])
    # The produced library replaces the published one in the payload, so the
    # deployment inventory must describe the rebuilt bytes: app/build.gradle
    # re-hashes every packaged library at configuration time and fails with
    # "Executor JNI hash differs" otherwise.
    name = "libcodex_app_bootstrap.so"
    produced = output / name
    shutil.copy2(produced, PAYLOAD / "executor-jni" / "arm64-v8a" / name)
    deployment_path = PAYLOAD / "executor-assets" / "codex-executor-deployment.json"
    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    actual = digest(produced)
    if deployment["nativeLibraries"].get(name) != actual:
        deployment["nativeLibraries"][name] = actual
        deployment_path.write_text(json.dumps(deployment, indent=2, sort_keys=True) + "\n",
                                   encoding="utf-8")
        log("build", "recorded rebuilt digest for " + name + ": " + actual)
        # The qualification record pins the deployment digest, so refresh the chain.
        run("build", [sys.executable, "-B", ROOT / "tools" / "workstation"
                      / "rewrite-application-id.py", "--assets", PAYLOAD / "executor-assets",
                      "--from", "com.ai.codex", "--to", package_id])
    log("build", "rebuilt " + name + " for " + package_id)


def build():
    state = json.loads((WORK / "state.json").read_text())
    env_json = json.loads((WORK / "env.json").read_text())
    sdk, gradle = env_json["sdk"], env_json["gradle"]
    state_payload = {
        "runtimeJni": str(PAYLOAD / "runtime-five"),
        "executorJni": str(PAYLOAD / "executor-jni"),
        "executorAssets": str(PAYLOAD / "executor-assets"),
    }
    environment = dict(os.environ,
                       ANDROID_HOME=sdk, ANDROID_SDK_ROOT=sdk,
                       GRADLE_USER_HOME=str(WORK / "gradle-home"),
                       JAVA_HOME=os.environ["JAVA_HOME"])
    # Both installed entry points bake this build's package into themselves, so
    # they are rebuilt before packaging rather than reused from the published APK.
    build_python_cli(state["packageId"])
    build_bootstrap(state["packageId"])
    command = [
        gradle, "-p", str(ROOT / "android"), "assembleRelease", "--no-daemon", "--stacktrace",
        "-PcodexVersionCode=9001",
        "-PcodexVersionName=0.2.0-dev-coinstall",
        f"-PcodexApplicationId={state['packageId']}",
        # Target the platform the test device actually runs (Android 15 / API 35).
        # A higher value starts the process without the zygote seccomp filter.
        f"-PcodexTargetSdk={TARGET_SDK}",
        f"-PcodexRuntimeJni={state_payload['runtimeJni']}",
        f"-PcodexExecutorJni={state_payload['executorJni']}",
        # The transport libraries come from the published APK: the module rebuilds
        # them, and the deployment inventory pins the published bytes.
        f"-PcodexTransportJni={PAYLOAD / 'transport-jni'}",
        f"-PcodexExecutorAssets={state_payload['executorAssets']}",
        "-PcodexRequireExecutor=true",
        # Ship the image *metadata* but not the 1.3 GB archive: the app then
        # reads codex-phone-rootfs.tar.gz from Download and verifies it against
        # these hashes (EnvironmentPackageSource). This keeps the test APK small
        # enough to download, and lets an existing local archive be reused.
        f"-PcodexPhoneImageAssets={PAYLOAD / 'phone-image'}",
        "-PcodexEmbedPhoneImage=false",
        # Deliberately do NOT override codexDebugJni: the :lorie and :app
        # debug source sets must keep their default jniLibs locations, otherwise
        # Gradle skips the CMake output and libXlorie.so is never packaged.
        f"-PcodexDebugAssets={PAYLOAD / 'debug-assets-empty'}",
    ]
    # Gradle records these as inputs; a missing directory fails the task graph,
    # so keep an explicit (empty) staging tree for the debug-only sources this
    # build does not carry.
    (PAYLOAD / "debug-assets-empty").mkdir(parents=True, exist_ok=True)
    # libcodex_app_transport.so is compiled from source because it carries this
    # build's admission policy, but its packaged bytes are only known after the
    # APK exists. So: package once, read the library back out of that APK, write
    # the real digest into the inventory, then package again with the corrected
    # asset. The second assemble reuses the already-built native output, so the
    # library bytes are unchanged and the recorded digest stays true.
    run("build", command, env=environment)
    output_directory = ROOT / "android" / "app" / "build" / "outputs" / "apk" / "release"
    produced = sorted(output_directory.glob("*.apk"))
    if not produced:
        raise SystemExit("Gradle produced no release APK")
    if record_transport_digest_from_apk(produced[-1]):
        run("build", command, env=environment)
        produced = sorted(output_directory.glob("*.apk"))
        if not produced:
            raise SystemExit("Gradle produced no release APK after digest correction")
        if record_transport_digest_from_apk(produced[-1]):
            raise SystemExit("Packaged transport digest still disagrees with the inventory")

    OUT.mkdir(parents=True, exist_ok=True)
    for path in produced:
        shutil.copy2(path, OUT / path.name)
    log("build", json.dumps([p.name for p in produced], indent=2))


# -------------------------------------------------------------------------- verify

def verify():
    state = json.loads((WORK / "state.json").read_text())
    env_json = json.loads((WORK / "env.json").read_text())
    sdk = Path(env_json["sdk"])
    apksigner = sdk / "build-tools" / BUILD_TOOLS / "lib" / "apksigner.jar"
    java = Path(os.environ["JAVA_HOME"]) / "bin" / "java"
    apks = sorted(OUT.glob("*.apk"))
    if len(apks) != 1:
        raise SystemExit(f"Expected exactly one APK, found {len(apks)}")
    apk = apks[0]
    report = {"apk": apk.name, "bytes": apk.stat().st_size, "sha256": digest(apk)}
    signature = subprocess.run([str(java), "-jar", str(apksigner), "verify",
                                "--print-certs", str(apk)],
                               stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if signature.returncode:
        raise SystemExit("APK signature verification failed:\n" + signature.stdout)
    report["signature"] = signature.stdout.strip().splitlines()[:4]

    with zipfile.ZipFile(apk) as archive:
        names = set(archive.namelist())
        deployment = json.loads(archive.read("assets/codex-executor-deployment.json"))
        # The packaged library must match the inventory the app itself checks at
        # admission time; otherwise the APK installs and then refuses every
        # launch with "Packaged native library digest mismatch".
        for member in sorted(n for n in names if n.startswith("lib/arm64-v8a/libcodex_")):
            library = member.rsplit("/", 1)[1]
            expected = deployment["nativeLibraries"].get(library)
            if expected is None:
                continue
            actual = hashlib.sha256(archive.read(member)).hexdigest()
            if actual != expected:
                raise SystemExit("Packaged " + library + " does not match the deployment inventory: "
                                 + actual + " != " + expected)
        report["nativeInventoryMatches"] = True
        if deployment["packageName"] != state["packageId"]:
            raise SystemExit("Deployment asset names the wrong package")
        if state["packageId"] not in deployment["pythonRuntime"]["path"]:
            raise SystemExit("pythonRuntime path still names the original package")
        missing = [n for n in RUNTIME_LIBS if f"lib/arm64-v8a/{n}" not in names]
        if missing:
            raise SystemExit("APK lacks PRoot runtime libraries: " + ", ".join(missing))
        # The PRoot fix must be observable in the packaged dex: the helper class
        # and the PROOT_NO_SECCOMP literal both have to be present.
        blobs = b"".join(archive.read(n) for n in names if n.endswith(".dex"))
        for marker in (b"PROOT_NO_SECCOMP", b"disableSeccompAcceleration"):
            if marker not in blobs:
                raise SystemExit("Packaged dex lacks the PRoot launch fix marker: " + marker.decode())
        report["prootFixMarkers"] = ["PROOT_NO_SECCOMP", "disableSeccompAcceleration"]
        # The dumpable restore must survive packaging too: if the Application
        # subclass or the visibility helper were dropped from the dex, siblings
        # are hidden again and every native launch ends as
        # qualified_native_deployment_unavailable. The transport library carries
        # the prctl(PR_SET_DUMPABLE) call itself.
        for marker in (b"SiblingProcessVisibility", b"CodexApplication"):
            if marker not in blobs:
                raise SystemExit("Packaged dex lacks the sibling-visibility fix marker: "
                                 + marker.decode())
        transport_member = "lib/arm64-v8a/libcodex_app_transport.so"
        if transport_member not in names or b"makeSiblingVisible" not in archive.read(transport_member):
            raise SystemExit("Packaged transport library lacks the sibling-visibility restore")
        report["visibilityFixMarkers"] = ["SiblingProcessVisibility", "CodexApplication",
                                         "makeSiblingVisible"]
        report["dexCount"] = sum(1 for n in names if n.endswith(".dex"))

    # The merged manifest is the authority for the installed package id.
    aapt2 = sdk / "build-tools" / BUILD_TOOLS / "aapt2"
    badging = subprocess.run([str(aapt2), "dump", "badging", str(apk)],
                             stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    if badging.returncode:
        raise SystemExit("aapt2 could not read the APK:\n" + badging.stdout)
    found = re.search(r"package: name='([^']+)'", badging.stdout)
    if not found or found.group(1) != state["packageId"]:
        raise SystemExit("Merged manifest package id is " + (found.group(1) if found else "absent"))
    report["packageName"] = found.group(1)
    report["installableBeside"] = "com.ai.codex"
    report["note"] = ("Debug test build signed with a throwaway key; it installs "
                      "beside com.ai.codex and cannot update it.")
    (OUT / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    log("verify", json.dumps(report, indent=2))


STAGES = {"recover": recover, "toolchain": toolchain, "build": build, "verify": verify}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=sorted(STAGES))
    args = parser.parse_args()
    STAGES[args.stage]()


if __name__ == "__main__":
    main()
