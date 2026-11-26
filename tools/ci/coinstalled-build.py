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
    build      run the Gradle assembleDebug with explicit payload inputs
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
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "work" / "coinstall"
PAYLOAD = WORK / "payload"
OUT = WORK / "out"
BASE_VERSION = "v85"
# Pinned from the published asset digest; a different APK is refused.
BASE_APK_SHA256 = "d07eec662cfac91486468610b7eea6f16cc96f1ea1c9ba841652c44cf695cf74"
GRADLE_VERSION = "9.7.1"
NDK_VERSION = "29.0.14206865"
CMAKE_VERSION = "3.22.1"
BUILD_TOOLS = "36.0.0"
SDK_PLATFORM = "android-37.0"
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
        skip = ("assets/phone-runtime/", "assets/desktop-client/", "assets/gnu-engine/")
        for name in names:
            if not name.startswith("assets/") or name.endswith("/") or name.startswith(skip):
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
    for name in needed:
        (PAYLOAD / "executor-jni" / "arm64-v8a" / name).write_bytes(libraries[name])
    # libXlorie.so is produced by the :lorie CMake project, which the co-installed
    # build does not rebuild. Reuse the published bytes so the app can load it.
    if "libXlorie.so" not in libraries:
        raise SystemExit("Base APK lacks libXlorie.so")
    (PAYLOAD / "runtime-five" / "arm64-v8a" / "libXlorie.so").write_bytes(libraries["libXlorie.so"])
    log("recover", json.dumps({"assets": assets, "libraries": len(libraries),
                               "executorJni": len(needed)}, indent=2))
    return deployment


def recover():
    package_id = os.environ.get("PACKAGE_ID", "com.ai.codex.dev")
    if not re.fullmatch(r"[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+", package_id):
        raise SystemExit("Invalid application id: " + package_id)
    if package_id == "com.ai.codex":
        raise SystemExit("The co-installed build must use a new application id")
    version = os.environ.get("BASE_VERSION", BASE_VERSION)
    url = ("https://github.com/JinShichang/codex-desktop-android/releases/download/"
           + version + "/Codex-Android-" + version + "-full.apk")
    apk = fetch(url, WORK / "base" / f"{version}.apk", expected=BASE_APK_SHA256)
    log("recover", "Base APK verified: " + BASE_APK_SHA256)
    extract_payload(apk)
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
    command = [
        gradle, "-p", str(ROOT / "android"), "assembleDebug", "--no-daemon", "--stacktrace",
        "-PcodexVersionCode=9001",
        "-PcodexVersionName=0.2.0-dev-coinstall",
        f"-PcodexApplicationId={state['packageId']}",
        f"-PcodexRuntimeJni={state_payload['runtimeJni']}",
        f"-PcodexExecutorJni={state_payload['executorJni']}",
        f"-PcodexExecutorAssets={state_payload['executorAssets']}",
        "-PcodexRequireExecutor=true",
        # Deliberately do NOT override codexDebugJni: the :lorie and :app
        # debug source sets must keep their default jniLibs locations, otherwise
        # Gradle skips the CMake output and libXlorie.so is never packaged.
        f"-PcodexDebugAssets={PAYLOAD / 'debug-assets-empty'}",
    ]
    # Gradle records these as inputs; a missing directory fails the task graph,
    # so keep an explicit (empty) staging tree for the debug-only sources this
    # build does not carry.
    (PAYLOAD / "debug-assets-empty").mkdir(parents=True, exist_ok=True)
    run("build", command, env=environment)
    produced = list((ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug").glob("*.apk"))
    if not produced:
        raise SystemExit("Gradle produced no debug APK")
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
