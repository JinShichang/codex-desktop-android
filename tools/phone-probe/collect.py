"""Collect fixed app-owned fixtures and independently verify a phone-probe run.

No test is started, no phone setting is changed, and no app data is deleted.
The installed diagnostic APK must match the explicitly selected build report.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[2]
PACKAGE = "com.ai.codex.phoneprobe"
CASES = {"pipe-files-exit", "missing-exec", "cancel-tree", "timeout-tree", "orphan-cleanup", "pty-stdio"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--adb", required=True, type=Path)
    parser.add_argument("--serial", required=True)
    parser.add_argument("--build", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    build = args.build.resolve(strict=True)
    output = args.output.resolve()
    output.relative_to(ROOT / "work")
    output.mkdir(parents=True, exist_ok=False)
    descriptor = json.loads((build / "build.json").read_text(encoding="utf-8"))
    if descriptor.get("package") != PACKAGE:
        raise ValueError("Not a phone diagnostic build")
    command = [str(args.adb.resolve(strict=True)), "-s", args.serial]

    def read(*argv):
        result = subprocess.run([*command, *argv], capture_output=True, timeout=20)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors="replace"))
        return result.stdout

    selected = read("exec-out", "run-as", PACKAGE, "cat", "files/latest-run.txt").decode().strip()
    if not re.fullmatch(r"run-[0-9]+", selected):
        raise ValueError("Unexpected fixture directory")
    raw = read("exec-out", "run-as", PACKAGE, "cat", "files/" + selected + "/results.jsonl")
    (output / "device-results.jsonl").write_bytes(raw)
    rows = [json.loads(line) for line in raw.splitlines()]

    def single(kind):
        matching = [row for row in rows if row.get("type") == kind]
        if len(matching) != 1:
            raise ValueError("Expected exactly one " + kind)
        return matching[0]

    context, native = single("android-context"), single("native-context")
    summary, final = single("summary"), single("android-result")
    cases = [row for row in rows if row.get("type") == "case"]
    fixture = read("exec-out", "run-as", PACKAGE, "cat", "files/" + selected + "/pipe-files-exit/roundtrip.txt")
    (output / "roundtrip.txt").write_bytes(fixture)
    installed = read("shell", "pm", "path", PACKAGE).decode().strip()
    if not re.fullmatch(r"package:/data/app/[A-Za-z0-9_./=+~\-]+/base\.apk", installed):
        raise ValueError("Unexpected or split diagnostic APK path")
    installed_sha = hashlib.sha256(read("exec-out", "cat", installed.removeprefix("package:"))).hexdigest()
    processes = read("shell", "ps", "-A", "-o", "UID,PID,PPID,NAME").decode().splitlines()
    observed = {native["pid"], *(case["ownerPid"] for case in cases)}
    for case in cases:
        for line in case["stdout"].splitlines():
            if line.startswith('{"worker":'):
                observed.add(json.loads(line)["pid"])
    live = set()
    selected_processes = []
    for line in processes[1:]:
        fields = line.split()
        if len(fields) >= 4 and fields[1].isdigit() and int(fields[1]) in observed:
            live.add(int(fields[1])); selected_processes.append(line)
    (output / "remaining-fixture-processes.txt").write_text("\n".join(selected_processes) + "\n", encoding="utf-8")
    report = {
        "schema": "codex.phone-probe.device.v1", "serial": args.serial, "run": selected,
        "appUid": context["uid"], "appUidMatchesNative": context["uid"] == native["uid"] and context["uid"] >= 10000,
        "nativeParentMatchesActivity": native["ppid"] == context["pid"], "inheritedSeccomp": native["seccomp"],
        "caseCount": len(cases), "caseNamesCorrect": len(cases) == len(CASES) and {case["name"] for case in cases} == CASES,
        "allCasesPassed": all(case["passed"] and case["actualOwnerWait"] and case["allPipesEof"]
                              and case["observedWorkersExited"] for case in cases),
        "finalReportedSuccess": summary["passed"] and summary["successes"] == 6 and final["passed"] and final["ownerExit"] == 0,
        "fileBytesCorrect": fixture == b"phone-probe\n", "liveFixturePids": sorted(live),
        "installedApkSha256": installed_sha, "installedApkMatchesBuild": installed_sha == descriptor["apkSha256"],
        "sourceManifestSha256": descriptor["sourceManifestSha256"],
        "rawResultsSha256": hashlib.sha256(raw).hexdigest(), "androidExecuted": True,
        "scope": "Fixed native direct/PTY owners in a separate Android application; not full Codex or GUI qualification",
    }
    report["passed"] = (all(report[key] for key in (
        "appUidMatchesNative", "nativeParentMatchesActivity", "caseNamesCorrect", "allCasesPassed",
        "finalReportedSuccess", "fileBytesCorrect", "installedApkMatchesBuild"))
        and report["inheritedSeccomp"] == 2 and not live)
    (output / "device-report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
