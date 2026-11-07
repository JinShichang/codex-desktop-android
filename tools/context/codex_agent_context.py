"""Maintain diagnostic device metadata without injecting global model instructions.

Runs against an explicitly selected guest root, never ADB. Does not change
config.toml, client binaries, Android permissions or any file outside that root.
An explicit one-time migration clears the old global AGENTS files. Later user edits survive.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile

LIMIT = 32768


def unique(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError("Duplicate manifest key")
        value[key] = item
    return value


def canonical(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def read(path, limit=LIMIT):
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Context input must be a single-link regular file")
        data = stream.read(limit + 1)
        if len(data) > limit or b"\0" in data:
            raise ValueError("Context input exceeds its text bound")
        data.decode("utf-8", errors="strict")
        return data


def manifest(path):
    value = json.loads(read(path), object_pairs_hook=unique)
    if set(value) != {"schema", "revision", "clientHost", "guest", "compute", "capabilities", "rules"} or value["schema"] != "codex.agent-environment.v1":
        raise ValueError("Unsupported context manifest")
    if type(value["clientHost"].get("androidRoot")) is not bool:
        raise ValueError("Root observation must be boolean metadata, not a policy directive")
    identifiers = set()
    for entry in value["capabilities"]:
        if set(entry) != {"id", "status", "description", "evidence"} or entry["id"] in identifiers or entry["status"] not in {"verified-bounded", "diagnostic-only", "unavailable"}:
            raise ValueError("Unknown or duplicate context capability")
        identifiers.add(entry["id"])
    return value


def real_directory(path, create=False):
    path = Path(path).absolute()
    if path.parent != path:
        real_directory(path.parent)
    try:
        info = path.lstat()
    except FileNotFoundError:
        if not create:
            raise
        path.mkdir(mode=0o700)
        info = path.lstat()
    if not stat.S_ISDIR(info.st_mode):
        raise ValueError("Context path traverses a non-directory or symlink")
    return path


def guest_path(root, guest):
    path = PurePosixPath(guest)
    if not path.is_absolute() or str(path) != guest or any(part in (".", "..") for part in path.parts):
        raise ValueError("Context guest path must be canonical and absolute")
    return root.joinpath(*path.parts[1:])


def identity(root):
    etc = real_directory(root / "etc")
    selected = read(etc / "codex-user", 128).decode()
    if re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}\n", selected) is None:
        raise ValueError("Invalid selected guest account")
    user = selected[:-1]
    rows = [line.split(":") for line in read(etc / "passwd", 1048576).decode().splitlines()]
    if any(len(row) != 7 or not row[2].isdecimal() or not row[3].isdecimal() for row in rows):
        raise ValueError("Malformed guest passwd")
    if len({int(row[2]) for row in rows}) != len(rows):
        raise ValueError("Ambiguous guest UID")
    selected = [row for row in rows if row[0] == user]
    if len(selected) != 1 or int(selected[0][2]) <= 0 or int(selected[0][3]) <= 0 or selected[0][5:] != ["/home/" + user, "/bin/bash"]:
        raise ValueError("Invalid selected nonroot guest identity")
    row = selected[0]
    groups = [line.split(":") for line in read(etc / "group", 1048576).decode().splitlines()]
    if any(len(item) != 4 or not item[2].isdecimal() for item in groups):
        raise ValueError("Malformed guest group")
    matching = [item for item in groups if item[0] == user or int(item[2]) == int(row[3])]
    if len(matching) != 1 or matching[0][0] != user or int(matching[0][2]) != int(row[3]):
        raise ValueError("Guest primary group differs")
    real_directory(guest_path(root, row[5]))
    return {"user": user, "uid": int(row[2]), "gid": int(row[3]), "home": row[5], "shell": row[6]}


def metadata(value, account, codex_home):
    bound = {"manifest": value, "guestBinding": account, "codexHome": codex_home,
             "bindingSource": "selected-guest-root-files", "modelDeliveryVerified": False}
    payload = canonical(bound)
    if len(payload) > LIMIT:
        raise ValueError("Device metadata exceeds its bound")
    sha = hashlib.sha256(payload).hexdigest()
    return payload, sha, codex_home + "/codex/environment-" + sha + ".json"


def atomic(path, data):
    previous = path.lstat() if path.exists() or path.is_symlink() else None
    if previous is not None:
        read(path)
        if previous.st_uid != os.geteuid():
            raise ValueError("Existing context file must belong to the synchronizing account")
    descriptor, scratch = tempfile.mkstemp(prefix=".codex-context-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            if previous is not None:
                os.fchmod(stream.fileno(), stat.S_IMODE(previous.st_mode))
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(scratch, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(scratch):
            os.unlink(scratch)


def synchronize(root, source, codex_home=None, check=False, clear_global_instructions_once=False):
    root = real_directory(root)
    value = manifest(source)
    account = identity(root)
    if root == Path("/") and (os.geteuid() != account["uid"] or os.getegid() != account["gid"] or os.environ.get("HOME") != account["home"]):
        raise ValueError("Live context synchronization requires the selected nonroot guest account and HOME")
    codex_home = codex_home or account["home"] + "/.codex"
    target = guest_path(root, codex_home)
    real_directory(target, create=not check)
    lock = os.open(target / ".codex-context.lock", os.O_RDWR | (0 if check else os.O_CREAT) | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(lock)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Invalid context synchronization lease")
        fcntl.flock(lock, fcntl.LOCK_EX)
        payload, sha, location = metadata(value, account, codex_home)
        store = real_directory(target / "codex", create=not check)
        destination = store / ("environment-" + sha + ".json")
        marker = store / "global-instructions-cleared-v2.json"
        receipt = canonical({"schema": "codex.global-instructions-cleared.v2", "automaticInjection": False})
        if check:
            if read(destination) != payload:
                raise ValueError("Diagnostic metadata is out of sync")
        else:
            if destination.exists() or destination.is_symlink():
                if read(destination) != payload:
                    raise ValueError("Content-addressed metadata differs")
            else:
                atomic(destination, payload)
        if clear_global_instructions_once:
            if marker.exists() or marker.is_symlink():
                if read(marker) != receipt:
                    raise ValueError("Instruction migration receipt differs")
            elif check:
                raise ValueError("Global instruction migration has not run")
            else:
                paths = [target / "AGENTS.md", target / "AGENTS.override.md"]
                # Validate both files before clearing either. Never follow links.
                for path in paths:
                    if path.exists() or path.is_symlink():
                        read(path)
                        if path.lstat().st_uid != os.geteuid():
                            raise ValueError("Global instructions must belong to the guest account")
                for path in paths:
                    if path.name == "AGENTS.md" or path.exists():
                        atomic(path, b"")
                atomic(marker, receipt)
        return {"status": "IN_SYNC", "automaticInstructionInjection": False,
                "manifestGuestFile": location, "manifestSha256": sha,
                "guestBinding": account, "modelDeliveryVerified": False,
                "scope": "diagnostic metadata only; no AGENTS injection"}
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--guest-root", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--codex-home", help="Actual absolute guest CODEX_HOME; defaults to selected HOME/.codex")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--clear-global-instructions-once", action="store_true",
                        help="Clear legacy global AGENTS/override once, preserving subsequent user edits")
    args = parser.parse_args()
    print(json.dumps(synchronize(args.guest_root, args.manifest, args.codex_home, args.check, args.clear_global_instructions_once), indent=2))


if __name__ == "__main__":
    main()
