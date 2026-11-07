"""Release metadata for a fresh, complete phone image (never a base-only update).

The APK must embed the resulting descriptor and inventory. A downloaded archive
cannot supply its own trusted descriptor. Existing v1/v2 integration pins and
installed user files are outside this separate first-install format.
"""
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import tarfile

FORMAT = "codex.phone-image.v1"
REQUIRED = {
    "usr/bin/env", "usr/bin/bash", "usr/bin/python3.13", "usr/bin/dbus-run-session",
    "usr/bin/gnome-keyring-daemon", "usr/bin/xfwm4", "usr/bin/wmctrl",
    "usr/lib/chatgpt/ChatGPT", "usr/lib/chatgpt/resources/app.asar",
    "usr/local/bin/codex-session", "usr/local/bin/codex-native",
    "usr/local/libexec/codex/codex-native", "usr/local/libexec/codex/codex-code-mode-host",
    "usr/local/lib/codex/codex_keyring.py", "usr/local/lib/codex/codex_ime.py",
    "usr/local/lib/codex/keyboard-focus.js", "usr/local/lib/codex/install-workspace-provider.py",
    "usr/local/lib/codex/install/initialize_keyring.py",
    "usr/local/lib/codex/install/supervise_keyring.py", "usr/share/X11/xkb/rules/evdev",
    "opt/codex-gpu/mesa-26.2.2-codex5/lib/libvulkan_freedreno.so",
}
RUNTIME_TREES = ("usr/lib/chatgpt", "usr/local", "usr/share/X11/xkb", "opt/codex-gpu")


def canonical(value):
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def path_name(value):
    if (not value or value.startswith("/") or "\\" in value
            or any(ord(c) < 32 or ord(c) == 127 for c in value)
            or str(PurePosixPath(value)) != value
            or any(p in ("", ".", "..") for p in value.split("/"))):
        raise ValueError("Unsafe phone image path")
    return value


def inspect_archive(path, expected_sha256):
    """Bound the exact authenticated archive consumed by RootfsExtractor."""
    if digest(path) != expected_sha256:
        raise ValueError("Phone image input digest mismatch")
    names, payload, tar_bytes = {}, 0, 0
    with tarfile.open(path, "r:gz") as archive:
        for member in archive:
            name = member.name.removeprefix("./").rstrip("/")
            if name == ".":
                name = ""
            if name:
                path_name(name)
            elif not member.isdir():
                raise ValueError("Only a directory may name the image root")
            if name in names or not (member.isdir() or member.isfile() or member.issym()):
                raise ValueError("Duplicate or unsupported image member (hardlinks must be materialized)")
            names[name] = "directory" if member.isdir() else "file" if member.isfile() else "symlink"
            if member.isfile():
                payload += member.size
            elif member.size:
                raise ValueError("Non-file image member has payload")
            if member.issym():
                # Guest-absolute links are valid. Relative links cannot climb
                # above the guest root; never resolve them on the build host.
                parts = [] if member.linkname.startswith("/") else name.split("/")[:-1]
                if not member.linkname or "\\" in member.linkname or "\0" in member.linkname:
                    raise ValueError("Invalid guest symlink")
                for part in member.linkname.split("/"):
                    if part == "..":
                        if not parts:
                            raise ValueError("Image symlink leaves guest root")
                        parts.pop()
                    elif part not in ("", "."):
                        parts.append(part)
        # gzip trailer/CRC and expanded byte count are checked independently.
    import gzip
    with gzip.open(path, "rb") as stream:
        while block := stream.read(1024 * 1024):
            tar_bytes += len(block)
    if "" not in names:
        raise ValueError("Image root directory is missing")
    for name in names:
        parent = str(PurePosixPath(name).parent) if name else "."
        if parent != "." and names.get(parent) != "directory":
            raise ValueError("Image has an undeclared parent")
    return {"sha256": expected_sha256, "compressedBytes": Path(path).stat().st_size,
            "payloadBytes": payload, "maxTarBytes": tar_bytes, "members": len(names)}


def inventory(root):
    """Immutable launch inputs; account, DNS and keyring are provisioned on Android."""
    root = Path(root)
    selected = set(REQUIRED)
    for name in RUNTIME_TREES:
        selected.add(name)
        selected.update(p.relative_to(root).as_posix() for p in (root / name).rglob("*"))
    records = []
    for name in sorted(selected):
        path_name(name)
        path = root / name
        info = path.lstat()
        record = {"path": name, "mode": stat.S_IMODE(info.st_mode)}
        if stat.S_ISREG(info.st_mode):
            record.update(kind="file", bytes=info.st_size, sha256=digest(path))
        elif stat.S_ISLNK(info.st_mode):
            record.update(kind="symlink", target=os.readlink(path))
        elif stat.S_ISDIR(info.st_mode):
            record.update(kind="directory")
        else:
            raise ValueError("Special file in immutable runtime input")
        records.append(record)
    return {"format": FORMAT, "scope": "immutable-launch-inputs", "files": records}


def require_pristine_profile(root):
    root = Path(root)
    if any((root / "home").iterdir()) or (root / "etc/codex-user").exists():
        raise ValueError("A phone image must not contain a selected user or home profile")
    for path in ("root/.config", "root/.codex", "root/.local/share/keyrings"):
        if (root / path).exists():
            raise ValueError("A phone image must not contain login or keyring state")
