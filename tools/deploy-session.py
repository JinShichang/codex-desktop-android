"""Update only Codex's own guest integration scripts in the debug APK."""
import argparse
from pathlib import Path
import subprocess

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--serial", required=True)
args = parser.parse_args()
root = Path(__file__).resolve().parents[1]
adb = ["adb", "-s", args.serial]
for name, target in {
    "runtime/guest/codex_keyring.py": "usr/local/lib/codex/codex_keyring.py",
    "runtime/guest/codex_ime.py": "usr/local/lib/codex/codex_ime.py",
    "runtime/guest/keyboard-focus.js": "usr/local/lib/codex/keyboard-focus.js",
    "runtime/guest/codex-session.sh": "usr/local/bin/codex-session",
}.items():
    data = (root / name).read_bytes().replace(b"\r\n", b"\n")
    subprocess.run(adb + ["shell", "run-as", "com.ai.codex", "sh", "-c",
                         f"'cat > files/debian/{target}'"], input=data, check=True)
subprocess.run(adb + ["shell", "run-as", "com.ai.codex", "chmod", "700",
                     "files/debian/usr/local/bin/codex-session"], check=True)
print("Updated guest integration scripts. Restart Codex to load them.")
