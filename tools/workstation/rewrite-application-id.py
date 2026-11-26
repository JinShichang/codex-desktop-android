#!/usr/bin/env python3
"""Rewrite the packaged executor payload for a co-installed application id.

The published APK pins its own application id in two places that an installed
build re-verifies at admission time:

* ``codex-executor-deployment.json`` -> ``packageName`` and
  ``pythonRuntime.path`` (``Deployment`` compares ``packageName`` with
  ``Context.getPackageName()`` and ``PythonRuntime`` re-checks the path).
* ``codex-python-runtime.json`` -> ``runtimeHome`` plus every path record, whose
  SHA-256 is referenced from the deployment asset.

Only the application-id prefix is rewritten. Library inventories, Python data
hashes and native bytes are untouched, so the reused payload stays
byte-identical apart from the package owner and the assets whose hashes are
recomputed here.

Usage: rewrite-package.py --assets DIR --from com.ai.codex --to com.ai.codex.dev
"""
import argparse
import hashlib
import json
from pathlib import Path

# Text assets that embed the owning application id. Probe trees are diagnostics
# only but are rewritten too, so no asset disagrees with the installed package.
TEXT_ASSETS = (
    "codex-app-launch-build.json",
    "codex-executor-deployment.json",
    "codex-executor/codex_app_bootstrap.py",
    "codex-executor/codex_native_bootstrap.py",
    "codex-executor/tools/executor/native_session_recovery.py",
    "codex-python-runtime.json",
    "codex-tools/agent-environment.v1.json",
    "codex-tools/codex_tools.py",
    "gnu-executor/tools/executor/native_session_recovery.py",
    "native-executor-probe/tools/executor/native_session_recovery.py",
    "private-exec-probe/tools/executor/native_session_recovery.py",
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rewrite(assets, old, new):
    changed = []
    for relative in TEXT_ASSETS:
        path = assets / relative
        if not path.is_file():
            raise SystemExit("Missing expected asset: " + relative)
        before = path.read_bytes()
        after = before.replace(old.encode(), new.encode())
        if after != before:
            path.write_bytes(after)
            changed.append(relative)

    deployment_path = assets / "codex-executor-deployment.json"
    deployment = json.loads(deployment_path.read_text(encoding="utf-8"))
    if deployment.get("packageName") != new:
        raise SystemExit("Deployment packageName was not rewritten")
    if new not in deployment["pythonRuntime"]["path"]:
        raise SystemExit("pythonRuntime.path was not rewritten")

    # codex-python-runtime.json carries a SHA-256 that the deployment pins.
    manifest = assets / deployment["pythonRuntime"]["manifestAsset"]
    updated = digest(manifest)
    if deployment["pythonRuntime"]["manifestSha256"] != updated:
        deployment["pythonRuntime"]["manifestSha256"] = updated
        deployment_path.write_text(
            json.dumps(deployment, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        changed.append("codex-executor-deployment.json (manifestSha256)")

    runtime = json.loads(manifest.read_text(encoding="utf-8"))
    if new not in runtime.get("runtimeHome", ""):
        raise SystemExit("codex-python-runtime runtimeHome was not rewritten")
    # A plain substring test would also match the new id when it extends the old
    # one (com.ai.codex -> com.ai.codex.dev), so require a non-identifier boundary.
    import re
    pattern = re.compile(re.escape(old).encode() + rb"(?![A-Za-z0-9_.])")
    leftovers = [str(p.relative_to(assets)) for p in assets.rglob("*")
                 if p.is_file() and pattern.search(p.read_bytes())]
    print(json.dumps({"changed": changed, "leftoverAssets": leftovers}, indent=2))
    return leftovers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--from", dest="old", required=True)
    parser.add_argument("--to", dest="new", required=True)
    args = parser.parse_args()
    leftovers = rewrite(args.assets.resolve(strict=True), args.old, args.new)
    if leftovers:
        raise SystemExit("Assets still reference the original application id")


if __name__ == "__main__":
    main()
