"""Phone GTK styling and window sizing, scoped to this desktop client."""
import argparse
import ctypes
import os
from pathlib import Path
import re
import stat
import subprocess
import time

BEGIN = '/* codex-phone-dialogs:begin */'
END = '/* codex-phone-dialogs:end */'
CHOOSER_TITLE = re.compile(
    r'^(?:Select Project Root|Open(?: File| Folder)?|Save(?: As)?|'
    r'(?:Select|Choose) .*(?:File|Folder|Directory)|打开.*|保存.*|选择.*)$', re.I)


def prepare():
    home = Path.home().resolve()
    directory = home / '.config/gtk-3.0'
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(home):
        raise ValueError('GTK settings must remain within the guest home')
    target = directory / 'gtk.css'
    previous = ''
    if target.exists() or target.is_symlink():
        info = target.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_size > 1024 * 1024:
            raise ValueError('GTK stylesheet is not an owned bounded regular file')
        previous = target.read_text(encoding='utf-8')
    start, end = previous.find(BEGIN), previous.find(END)
    if ((start < 0) != (end < 0) or (start >= 0 and
            (end < start or previous.count(BEGIN) != 1 or previous.count(END) != 1))):
        raise ValueError('Ambiguous phone dialog stylesheet markers')
    css = Path(__file__).with_name('codex-phone-dialogs.css').read_text(encoding='utf-8')
    block = BEGIN + '\n' + css.rstrip() + '\n' + END
    updated = (previous.rstrip() + '\n\n' + block + '\n') if start < 0 else (
        previous[:start] + block + previous[end + len(END):])
    if updated != previous:
        temporary = directory / '.codex-dialogs.css.next'
        with temporary.open('w', encoding='utf-8') as output:
            output.write(updated)
            output.flush()
            os.fsync(output.fileno())
        temporary.chmod(0o600)
        temporary.replace(target)


def command(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=3)


class WindowProperties:
    """Read EWMH metadata using GTK's existing X11 library; no extra X utilities."""
    def __init__(self):
        self.lib = ctypes.CDLL('libX11.so.6')
        pointer, number = ctypes.c_void_p, ctypes.c_ulong
        self.lib.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.lib.XOpenDisplay.restype = pointer
        self.lib.XInternAtom.argtypes = [pointer, ctypes.c_char_p, ctypes.c_int]
        self.lib.XInternAtom.restype = number
        self.lib.XGetWindowProperty.argtypes = [pointer, number, number, ctypes.c_long,
            ctypes.c_long, ctypes.c_int, number, ctypes.POINTER(number),
            ctypes.POINTER(ctypes.c_int), ctypes.POINTER(number), ctypes.POINTER(number),
            ctypes.POINTER(pointer)]
        self.lib.XGetWindowProperty.restype = ctypes.c_int
        self.lib.XFree.argtypes = [pointer]
        self.lib.XCloseDisplay.argtypes = [pointer]
        self.lib.XSetErrorHandler.argtypes = [pointer]
        self.lib.XSetErrorHandler.restype = pointer
        # A dialog may close between listing its ID and reading its properties.
        self.error_handler = ctypes.CFUNCTYPE(ctypes.c_int, pointer, pointer)(lambda *_: 0)
        self.old_handler = self.lib.XSetErrorHandler(ctypes.cast(self.error_handler, pointer))
        self.display = self.lib.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError('Native dialog sizing requires the active X11 display')
        self.dialog_atom = self.atom('_NET_WM_WINDOW_TYPE_DIALOG')

    def atom(self, name):
        return self.lib.XInternAtom(self.display, name.encode('ascii'), False)

    def property(self, window, name):
        kind, size, count, remaining = ctypes.c_ulong(), ctypes.c_int(), ctypes.c_ulong(), ctypes.c_ulong()
        data = ctypes.c_void_p()
        result = self.lib.XGetWindowProperty(self.display, int(window, 16), self.atom(name),
            0, 1024, False, 0, ctypes.byref(kind), ctypes.byref(size), ctypes.byref(count),
            ctypes.byref(remaining), ctypes.byref(data))
        try:
            if result or not data.value or remaining.value:
                return None
            if size.value == 32:
                values = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))
                return [values[index] for index in range(count.value)]
            if size.value == 8:
                return ctypes.string_at(data, count.value).decode('utf-8', 'replace')
            return None
        finally:
            if data.value:
                self.lib.XFree(data)

    def is_chooser(self, window, title):
        types = self.property(window, '_NET_WM_WINDOW_TYPE') or []
        if not isinstance(types, list) or self.dialog_atom not in types:
            return False
        role = self.property(window, 'WM_WINDOW_ROLE') or ''
        return (isinstance(role, str) and 'filechooser' in role.lower()) or bool(CHOOSER_TITLE.fullmatch(title))

    def close(self):
        self.lib.XCloseDisplay(self.display)
        self.lib.XSetErrorHandler(self.old_handler)


def watch(pid):
    handled = set()
    properties = WindowProperties()
    try:
        watch_windows(pid, handled, properties)
    finally:
        properties.close()


def watch_windows(pid, handled, properties):
    while True:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return
        result = command('wmctrl', '-lp')
        present = set()
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                fields = line.split(None, 4)
                if len(fields) != 5 or fields[2] != str(pid):
                    continue
                window, title = fields[0], fields[4]
                present.add(window)
                if window in handled or not re.fullmatch(r'0x[0-9a-fA-F]+', window):
                    continue
                if not properties.is_chooser(window, title):
                    continue
                resized = command('wmctrl', '-i', '-r', window, '-b',
                                  'add,maximized_vert,maximized_horz')
                if resized.returncode == 0:
                    handled.add(window)
        handled.intersection_update(present)
        time.sleep(0.75)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('prepare', 'watch'))
    parser.add_argument('--pid', type=int)
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.pid is None or args.pid <= 1:
        parser.error('watch requires the actual desktop client PID')
    else:
        watch(args.pid)
