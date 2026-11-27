"""Probe PRoot's real nested-exec path, outside any installer or user task.

The ordinary Android Python tool launchers need their own result: their caller
can inherit additional syscall restrictions compared with the Java app process.
This does not change Android's seccomp policy or the managed GNU executor mode.
"""
import fcntl
import hashlib
import os
from pathlib import Path
import selectors
import stat
import subprocess
import tempfile
import time

NO_SECCOMP = "PROOT_NO_SECCOMP"
MARKER = b"CODEX_PROOT_NESTED_EXEC_OK"
ACCELERATION = b"ptrace acceleration (seccomp mode 2"
SCRIPT = '/bin/sh -c "exec /usr/bin/env -i PATH=/usr/bin:/bin /bin/sh -c \'printf CODEX_PROOT_NESTED_EXEC_OK\'"; exit $?'
VERSION = "codex.proot.seccomp.v1"
LIMIT = 16384


def probe_command(arguments):
    guest = arguments.index("/usr/bin/env")
    root = arguments.index("-r")
    if (guest <= 0 or not 0 < root < guest - 1 or
            not arguments[0].endswith("/libproot.so") or "--kill-on-exit" not in arguments[:guest]):
        raise ValueError("Expected an owned PRoot launch with an explicit guest environment")
    return [arguments[0], "-v", "1", *arguments[1:guest], "/usr/bin/env", "-i",
            "PATH=/usr/bin:/bin", "LC_ALL=C", "/bin/sh", "-c", SCRIPT]


def run_probe(arguments, environment, timeout=5):
    try:
        child = subprocess.Popen(arguments, env=environment, stdin=subprocess.DEVNULL,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except OSError:
        return False, False
    data = bytearray()
    deadline = time.monotonic() + timeout
    try:
        os.set_blocking(child.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    return False, False
                if not selector.select(remaining):
                    return False, False
                chunk = os.read(child.stdout.fileno(), 4096)
                if not chunk:
                    break
                data.extend(chunk)
                if len(data) > LIMIT:
                    return False, False
        try:
            code = child.wait(timeout=max(0.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return False, False
        return code == 0 and MARKER in data, ACCELERATION in data
    finally:
        # --kill-on-exit PRoot handles SIGTERM and reaps its own tracees.
        try:
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    child.kill()
            child.wait(timeout=1)
        finally:
            child.stdout.close()


def read_record(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 256:
                return None
            text = stream.read(257).decode("ascii")
        if text == VERSION + "\naccelerated\nnested-exec-ok\n":
            return True
        if text in (VERSION + "\ncompatible\nacceleration-unavailable\n",
                    VERSION + "\ncompatible\nacceleration-failed\n"):
            return False
    except (OSError, UnicodeError):
        pass
    return None


def select_mode(arguments, environment, path, runner):
    selected = read_record(path)
    if selected is not None:
        return selected
    probe = probe_command(arguments)
    accelerated_env = dict(environment)
    accelerated_env.pop(NO_SECCOMP, None)
    passed, enabled = runner(probe, accelerated_env)
    if passed and enabled:
        selected, reason = True, "nested-exec-ok"
    else:
        compatible_env = dict(environment, PROOT_NO_SECCOMP="1")
        compatible, _ = runner(probe, compatible_env)
        if not compatible:
            raise OSError("PRoot nested-exec detection failed in both accelerated and compatible modes; no user task was executed")
        selected, reason = False, "acceleration-unavailable" if passed else "acceleration-failed"
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(prefix=".probe-", dir=path.parent)
        with os.fdopen(fd, "w", encoding="ascii") as stream:
            stream.write(VERSION + "\n" + ("accelerated" if selected else "compatible") + "\n" + reason + "\n")
        os.replace(temporary, path)
    except OSError:
        pass  # Cache persistence must not block a verified tool invocation.
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    return selected


def configure(arguments, environment, files_directory, platform, runner=run_probe):
    # Validate the launch even on cache hits; never reuse a result for an
    # unrelated executable/rootfs, APK installation or system image.
    probe_command(arguments)
    executable = Path(arguments[0]).resolve(strict=True)
    root = Path(arguments[arguments.index("-r") + 1]).resolve(strict=True)
    info = executable.stat()
    identity = "\n".join((VERSION, platform, os.uname().release, str(executable),
                          str(info.st_size), str(info.st_mtime_ns), str(root)))
    directory = Path(files_directory) / ".proot-compat"
    directory.mkdir(mode=0o700, exist_ok=True)
    state = directory.lstat()
    if not stat.S_ISDIR(state.st_mode) or state.st_uid != os.getuid():
        raise OSError("Invalid PRoot compatibility cache directory")
    path = directory / ("tools-" + hashlib.sha256(identity.encode()).hexdigest() + ".txt")
    lock = os.open(directory / "tools.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        state = os.fstat(lock)
        if not stat.S_ISREG(state.st_mode) or state.st_uid != os.getuid():
            raise OSError("Invalid PRoot compatibility lock")
        fcntl.flock(lock, fcntl.LOCK_EX)
        selected = select_mode(arguments, environment, path, runner)
    finally:
        os.close(lock)
    if selected:
        environment.pop(NO_SECCOMP, None)
    else:
        environment[NO_SECCOMP] = "1"
    return selected
