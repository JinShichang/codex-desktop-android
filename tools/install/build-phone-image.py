"""Assemble a new complete first-install image from explicit authenticated inputs.

Run as Linux build-host root. This never reads a phone, user home or login state.
The output descriptor is a release input for the APK, not download metadata.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

import guest_bundle
import official_client_package as client
import phone_image as image

ROOT = Path(__file__).resolve().parents[2]
CLIENT_FINGERPRINT = "3BFA0E4AE8B8CC16A2D9BA684A3B4A566C4660E4"


def run(args, **kwargs):
    subprocess.run(list(map(str, args)), check=True, **kwargs)


def authenticated_client(upstream, output):
    """The pinned official signing identity authenticates index and package bytes."""
    verified = subprocess.check_output([
        "gpgv", "--status-fd", "1", "--keyring", str(upstream / "repository-key.gpg"),
        str(upstream / "InRelease")], text=True)
    if f"[GNUPG:] VALIDSIG {CLIENT_FINGERPRINT} " not in verified:
        raise ValueError("Unexpected official repository signer")
    index = (upstream / "Packages.arm64").read_bytes()
    binding = f" {hashlib.sha256(index).hexdigest()} {len(index):16d} main/binary-arm64/Packages"
    # Whitespace is representational; the signed SHA-256 and length are exact.
    signed = (upstream / "InRelease").read_text().split("SHA256:\n", 1)[1].split("SHA512:", 1)[0]
    if not any(line.split() == binding.split() for line in signed.splitlines()):
        raise ValueError("Official ARM64 package index is not bound by the signature")
    records = [client.deb822(record) for record in index.split(b"\n\n") if record.strip()]
    records = [record for record in records if record.get("package") == "chatgpt" and record.get("architecture") == "arm64"]
    if len(records) != 1:
        raise ValueError("Official package index is ambiguous")
    record = records[0]
    source = upstream / Path(record["filename"]).name
    descriptor = client.descriptor({"format": client.FORMAT, "sourceUrl": client.SOURCE_URL,
        "sourceDocument": client.SOURCE_DOCUMENT, "package": "chatgpt", "architecture": "arm64",
        "version": record["version"], "sha256": record["sha256"], "bytes": int(record["size"]),
        "maxTarBytes": 3 * 1024 ** 3, "maxMembers": 100000})
    with source.open("rb") as stream:
        inspected = client.inspect(stream, descriptor)
    (output / "official-client-inspection.json").write_bytes(image.canonical(inspected))
    for name in ("InRelease", "Packages.arm64", "repository-key.gpg"):
        shutil.copy2(upstream / name, output / name)
    return source, descriptor


def install_guest_sources(root):
    for source, (destination, mode) in guest_bundle.SOURCES.items():
        if not destination.startswith("payload/"):
            continue
        target = root / destination.removeprefix("payload/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / source).read_bytes().replace(b"\r\n", b"\n"))
        target.chmod(0o600 if target.name in ("initialize_keyring.py", "supervise_keyring.py") else mode)
    for name in ("install-workspace-provider.py", "codex-workspace-provider.cjs",
                 "workspace-node-check.cjs", "workspace-python-check.py", "workspace-render-check.py"):
        target = root / "usr/local/lib/codex" / name
        target.write_bytes((ROOT / "tools/runtime" / name).read_bytes().replace(b"\r\n", b"\n"))
        target.chmod(0o644)


def engine_inputs(args):
    deadline = time.monotonic() + args.wait_engine_seconds
    while True:
        state = json.loads(args.engine_state.read_text())
        if state.get("buildCompleted") and state.get("packageCompleted"):
            break
        if state.get("buildExitCode") not in (None, 0) or time.monotonic() >= deadline:
            raise ValueError("A successfully built and packaged GNU engine is required")
        time.sleep(10)
    engine = Path(state["build"]) / "package"
    if image.digest(state["package"]) != state["packageSha256"]:
        raise ValueError("GNU engine release archive differs from its build state")
    with tarfile.open(state["package"], "r:gz") as archive:
        manifest = json.load(archive.extractfile("manifest.json"))
    for expected in manifest["files"]:
        name = image.path_name(expected["path"])
        if ("sha256" not in expected or (engine / name).is_symlink()
                or image.digest(engine / name) != expected["sha256"]
                or (engine / name).stat().st_size != expected["bytes"]):
            raise ValueError("GNU engine package changed: " + name)
    return state, engine


def assemble(args):
    if sys.platform != "linux" or os.geteuid() != 0:
        raise RuntimeError("Use build-host Linux root; no Android root is needed")
    if args.output.exists():
        raise FileExistsError("Output must be a new release directory")
    args.output.mkdir(mode=0o755)
    evidence = args.output / "evidence"
    evidence.mkdir()
    if image.digest(args.base) != args.base_sha256 or image.digest(args.gpu) != args.gpu_sha256:
        raise ValueError("Explicit base/GPU release input digest differs")
    package_source, descriptor = authenticated_client(args.official_input, evidence)
    work = Path(tempfile.mkdtemp(prefix="codex-phone-image-", dir="/var/tmp"))
    root = work / "rootfs"
    root.mkdir()
    (evidence / "build-directory.txt").write_text(str(work) + "\n")
    run(["tar", "--extract", "--gzip", "--file", args.base, "--directory", root, "--numeric-owner"])
    run([sys.executable, "-B", ROOT / "tools/install/verify_rootfs.py", root],
        stdout=(evidence / "pristine-base-verification.json").open("w"))
    # Complete the package dependency closure on the disposable build host.
    # APT keeps signature validation enabled and saves every downloaded .deb.
    dns = root / "etc/resolv.conf"
    original_dns = dns.read_bytes()
    dns.write_bytes(Path("/etc/resolv.conf").read_bytes())
    source = root / "tmp/codex-official-client.deb"
    shutil.copyfile(package_source, source)
    env = dict(os.environ, DEBIAN_FRONTEND="noninteractive", LC_ALL="C.UTF-8")
    for name in ("http_proxy", "https_proxy", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "all_proxy"):
        env.pop(name, None)
    apt = ["chroot", root, "/usr/bin/apt-get", "-o", "Acquire::ForceIPv4=true",
           "-o", "Acquire::AllowInsecureRepositories=false", "-o", "APT::Get::AllowUnauthenticated=false",
           "-o", "Binary::apt::APT::Keep-Downloaded-Packages=true"]
    with (evidence / "client-apt.log").open("w") as log:
        run([*apt, "update"], env=env, stdout=log, stderr=subprocess.STDOUT)
        run([*apt, "install", "-y", "--no-install-recommends", "/tmp/codex-official-client.deb"],
            env=env, stdout=log, stderr=subprocess.STDOUT)
    source.unlink()
    dns.write_bytes(original_dns)
    installed = subprocess.check_output(["dpkg-query", "--admindir=" + str(root / "var/lib/dpkg"),
        "-W", "-f=${binary:Package}\t${Version}\t${Architecture}\t${db:Status-Abbrev}\n"])
    (evidence / "complete-installed-packages.tsv").write_bytes(installed)
    extra = evidence / "additional-debs"
    extra.mkdir()
    for archive in (root / "var/cache/apt/archives").glob("*.deb"):
        shutil.copy2(archive, extra / archive.name)
        archive.unlink()
    shutil.copytree(root / "var/lib/apt/lists", evidence / "complete-apt-lists", symlinks=True)
    # Keep the official client unchanged. Its adapter is admitted at launch;
    # optional workspace distribution selection remains an explicit later input.
    with package_source.open("rb") as stream:
        inspected = client.inspect(stream, descriptor)
    for item in inspected["files"]:
        if item["kind"] == "file" and image.digest(root / item["path"]) != item["sha256"]:
            raise ValueError("Installed official client differs: " + item["path"])
    print("Official client installed and revalidated; waiting for the separate GNU engine package", flush=True)
    state, engine = engine_inputs(args)
    install_guest_sources(root)
    with tarfile.open(args.gpu, "r:gz") as archive:
        if any(not x.name.startswith("opt/codex-gpu/mesa-26.2.2-codex5") for x in archive.getmembers()):
            raise ValueError("GPU payload has an unexpected prefix")
        archive.extractall(root, filter="data")
    destination = root / "usr/local/libexec/codex"
    destination.mkdir(parents=True, exist_ok=True)
    for name, target in (("codex", "codex-native"), ("codex-code-mode-host", "codex-code-mode-host")):
        shutil.copy2(engine / name, destination / target)
        (destination / target).chmod(0o755)
    image.require_pristine_profile(root)
    immutable = image.inventory(root)
    assets = args.output / "assets/phone-runtime"
    assets.mkdir(parents=True)
    inventory = image.canonical(immutable)
    (assets / "inventory.json").write_bytes(inventory)
    archive = args.output / "codex-phone-rootfs.tar.gz"
    # Materialize hardlinked files in this separate image. This avoids requiring
    # Android link(2) and preserves guest symlinks without following host paths.
    with archive.open("xb") as output:
        tar = subprocess.Popen(["tar", "--sort=name", "--hard-dereference", "--numeric-owner",
            "--format=posix", "--pax-option=delete=atime,delete=ctime", "-C", root, "-cf", "-", "."], stdout=subprocess.PIPE)
        run(["gzip", "-n", "-6"], stdin=tar.stdout, stdout=output)
        tar.stdout.close()
        if tar.wait() != 0:
            raise RuntimeError("Phone image tar failed")
    spec = image.inspect_archive(archive, image.digest(archive))
    release = {"format": image.FORMAT, "archive": archive.name, "spec": spec,
        "inventorySha256": hashlib.sha256(inventory).hexdigest(), "inventoryBytes": len(inventory),
        "initializerSha256": image.digest(root / "usr/local/lib/codex/install/initialize_keyring.py"),
        "supervisorSha256": image.digest(root / "usr/local/lib/codex/install/supervise_keyring.py"),
        "baseSha256": args.base_sha256, "gpuSha256": args.gpu_sha256,
        "client": descriptor, "enginePackageSha256": state["packageSha256"],
        "accountIncluded": False, "keyringIncluded": False, "androidExecuted": False}
    (assets / "release.json").write_bytes(image.canonical(release))
    shutil.copy2(args.engine_state, evidence / "engine-build-state.json")
    (evidence / "source-files.json").write_bytes(image.canonical({
        str(p.relative_to(ROOT)): image.digest(p) for p in [Path(__file__), ROOT / "tools/install/phone_image.py",
        *[ROOT / source for source in guest_bundle.SOURCES]]}))
    print(json.dumps({"output": str(args.output), "image": spec, "androidExecuted": False}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("base", "gpu", "engine-state", "official-input", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    for name in ("base-sha256", "gpu-sha256"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--wait-engine-seconds", type=int, default=0)
    assemble(parser.parse_args())
