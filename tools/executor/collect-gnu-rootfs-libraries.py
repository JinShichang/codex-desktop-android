"""Collect GNU engine dependencies from an explicitly authenticated new base.

This is a build-host library collection, never historical/device evidence.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def needed(path):
    text = subprocess.check_output(["aarch64-linux-gnu-readelf", "--dynamic", "--wide", str(path)], text=True)
    return re.findall(r"\(NEEDED\).*Shared library: \[([^\]]+)\]", text)


def collect(args):
    if digest(args.rootfs_archive) != args.rootfs_sha256:
        raise ValueError("Explicit rootfs release digest differs")
    args.output.mkdir(mode=0o755)
    records = []
    with tarfile.open(args.rootfs_archive, "r:gz") as archive:
        prefix = "usr/lib/aarch64-linux-gnu/"
        members = {x.name.removeprefix("./"): x for x in archive.getmembers()}

        def resolve(name):
            path = prefix + name
            seen = set()
            while True:
                if path in seen or path not in members or not path.startswith(prefix):
                    raise ValueError("Unresolved or escaping GNU dependency: " + name)
                seen.add(path)
                member = members[path]
                if member.isfile():
                    return member
                if not member.issym():
                    raise ValueError("GNU library is not a regular file or symlink")
                parts = [] if member.linkname.startswith("/") else path.split("/")[:-1]
                for part in member.linkname.split("/"):
                    if part == "..":
                        if not parts:
                            raise ValueError("GNU library link escapes root")
                        parts.pop()
                    elif part not in ("", "."):
                        parts.append(part)
                path = "/".join(parts)

        pending = ["ld-linux-aarch64.so.1"]
        for binary in ("codex", "codex-code-mode-host"):
            pending.extend(needed(args.binaries / binary))
        done = set()
        while pending:
            name = pending.pop()
            if name in done:
                continue
            if name != Path(name).name:
                raise ValueError("GNU dependency must be a basename")
            member = resolve(name)
            destination = args.output / name
            with archive.extractfile(member) as source, destination.open("xb") as target:
                while block := source.read(1024 * 1024):
                    target.write(block)
            destination.chmod(0o644)
            if destination.read_bytes()[:7] != b"\x7fELF\x02\x01\x01":
                raise ValueError("GNU dependency is not ELF64 little-endian")
            records.append({"path": name, "sourceMember": member.name, "sha256": digest(destination),
                            "bytes": destination.stat().st_size})
            done.add(name)
            pending.extend(needed(destination))
    result = {"schema": "codex.gnu-library-collection.v1", "origin": "source-built-debian-rootfs",
              "rootfsArchiveSha256": args.rootfs_sha256, "androidCollected": False,
              "files": sorted(records, key=lambda x: x["path"])}
    (args.output / "collection.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "libraries": len(records), "androidCollected": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("rootfs-archive", "binaries", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--rootfs-sha256", required=True)
    collect(parser.parse_args())
