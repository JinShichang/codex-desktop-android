# Guest session integration

These sources run inside the Linux guest hosted by Codex:

- `codex-session.sh` starts the desktop session and its integration services.
- `codex_keyring.py` unlocks the existing keyring using the private input supplied by Android.
- `codex_ime.py` connects desktop input events to the Android keyboard bridge.
- `keyboard-focus.js` observes deliberate input focus; it stays beside the IME script.

The guest bundle and deployment tools select these files explicitly. Installed
paths remain `/usr/local/bin/codex-session` and `/usr/local/lib/codex/`.
Run the focused regressions from the repository root; see [tests](../../tests/README.md).
