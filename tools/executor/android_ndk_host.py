"""Select and record a native Windows/Linux x86_64 Android NDK toolchain.

Build-time helper only. Unsupported hosts and missing native executables fail
before a builder creates its output; no other host or installed NDK is tried.
"""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform


def digest(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


@dataclass(frozen=True)
class NdkHost:
    root: Path
    host_tag: str
    suffix: str
    system: str
    machine: str
    wsl: bool

    def tool(self, name):
        if name not in {"clang", "llvm-readelf"}:
            raise ValueError("Undeclared NDK host tool: " + name)
        path = self.root / "bin" / (name + self.suffix)
        if not path.is_file() or self.system == "Linux" and not os.access(path, os.X_OK):
            raise FileNotFoundError("Missing executable for selected NDK host: " + str(path))
        return path


def select_toolchain(ndk):
    system, machine = platform.system(), platform.machine().lower()
    if system == "Windows" and machine in {"amd64", "x86_64"}:
        tag, suffix = "windows-x86_64", ".exe"
    elif system == "Linux" and machine == "x86_64":
        tag, suffix = "linux-x86_64", ""
    else:
        raise ValueError(f"Unsupported NDK build host: {system}/{machine}; Windows or Linux x86_64 required")
    root = Path(ndk).resolve(strict=True) / "toolchains/llvm/prebuilt" / tag
    if not root.is_dir():
        raise FileNotFoundError("NDK does not contain selected native host toolchain: " + str(root))
    host = NdkHost(root, tag, suffix, system, machine,
                   system == "Linux" and "microsoft" in platform.release().lower())
    for name in ("clang", "llvm-readelf"):
        host.tool(name)
    return host


def write_host_evidence(output, host, builder):
    """Preserve added build inputs without changing existing admission schemas."""
    output = Path(output)
    helper = Path(__file__).resolve()
    snapshot = output / "android_ndk_host.py"
    with snapshot.open("xb") as target:
        target.write(helper.read_bytes())
    if digest(snapshot) != digest(helper):
        raise ValueError("NDK host helper changed during snapshot")
    record = {
        "schema": "codex.ndk-host-tools.v1", "hostTag": host.host_tag,
        "system": host.system, "machine": host.machine, "wslExecuted": host.wsl,
        "prebuiltDirectory": str(host.root), "helperSha256": digest(snapshot),
        "builderSha256": digest(builder),
        "tools": {name: {"path": str(host.tool(name)), "sha256": digest(host.tool(name))}
                  for name in ("clang", "llvm-readelf")},
    }
    with (output / "host-toolchain.json").open("x", encoding="utf-8") as target:
        json.dump(record, target, indent=2)
        target.write("\n")
