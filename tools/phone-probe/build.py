"""Build a separate offline diagnostic APK from explicit local toolchains.

No Gradle, network, ADB operation or production signing identity is used.
The selected NDK is recorded, not represented as a qualified production NDK.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import zipfile


ROOT = Path(__file__).resolve().parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", required=True, type=Path)
    parser.add_argument("--jdk", required=True, type=Path)
    parser.add_argument("--ndk", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    sdk, jdk, ndk = (p.resolve(strict=True) for p in (args.sdk, args.jdk, args.ndk))
    output = args.output.resolve()
    output.relative_to(ROOT / "work")
    output.mkdir(parents=True, exist_ok=False)
    tools = sdk / "build-tools/36.0.0"
    android = sdk / "platforms/android-37/android.jar"
    compiler = ndk / "toolchains/llvm/prebuilt/windows-x86_64/bin/clang.exe"
    java = jdk / "bin/java.exe"
    for path in (android, compiler, java, tools / "aapt.exe", tools / "lib/d8.jar", tools / "lib/apksigner.jar"):
        if not path.is_file():
            raise ValueError("Required local tool is unavailable: " + str(path))

    names = ["AndroidManifest.xml", "ProbeActivity.java", "probe.c", "worker.c", "build.py"]
    inputs = {"phone-probe/" + name: Path(__file__).with_name(name) for name in names}
    for name in ("direct-runner.c", "tty-runner.c", "direct-api.md", "direct_wire.py", "tty_wire.py"):
        inputs["bionic-supervisor/" + name] = ROOT / "tools/executor/bionic-supervisor" / name
    source = output / "source"
    inventories = []
    for name, origin in inputs.items():
        target = source / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(origin, target)
        inventories.append({"path": name, "sha256": digest(target), "bytes": target.stat().st_size})
    (output / "sources.json").write_text(json.dumps(inventories, indent=2) + "\n", encoding="utf-8")
    shutil.copyfile(ndk / "source.properties", output / "ndk-source.properties")

    environment = os.environ.copy()
    environment["TEMP"] = environment["TMP"] = str(output)
    environment["JAVA_HOME"] = str(jdk)

    def run(name, command):
        command = list(map(str, command))
        (output / (name + ".command.json")).write_text(json.dumps(command, indent=2) + "\n", encoding="utf-8")
        result = subprocess.run(command, cwd=output, env=environment, capture_output=True, timeout=120)
        (output / (name + ".log")).write_bytes(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"{name} failed ({result.returncode}); see {output / (name + '.log')}")

    native = output / "native"
    native.mkdir()
    pairs = {
        "libcodex_phone_probe.so": "phone-probe/probe.c",
        "libcodex_probe_worker.so": "phone-probe/worker.c",
        "libcodex_direct_runner.so": "bionic-supervisor/direct-runner.c",
        "libcodex_tty_runner.so": "bionic-supervisor/tty-runner.c",
    }
    for name, relative in pairs.items():
        run(name, [compiler, "--target=aarch64-linux-android35", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                   "-fPIE", "-pie", "-fstack-protector-strong", "-pthread",
                   "-Wl,--no-undefined,-z,relro,-z,now,-z,noexecstack,-z,max-page-size=16384,-z,common-page-size=16384",
                   source / relative, "-o", native / name])

    classes = output / "classes"
    classes.mkdir()
    run("javac", [jdk / "bin/javac.exe", "-encoding", "UTF-8", "-source", "17", "-target", "17",
                  "-cp", android, "-d", classes, source / "phone-probe/ProbeActivity.java"])
    jar = output / "classes.jar"
    with zipfile.ZipFile(jar, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in classes.rglob("*.class"):
            archive.write(path, path.relative_to(classes).as_posix())
    dex = output / "dex"
    dex.mkdir()
    run("d8", [java, "-cp", tools / "lib/d8.jar", "com.android.tools.r8.D8", "--lib", android,
               "--min-api", "30", "--output", dex, jar])
    base = output / "base.apk"
    run("aapt", [tools / "aapt.exe", "package", "-f", "-M", source / "phone-probe/AndroidManifest.xml",
                 "-I", android, "-F", base])
    unaligned = output / "unaligned.apk"
    shutil.copyfile(base, unaligned)
    with zipfile.ZipFile(unaligned, "a", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.write(dex / "classes.dex", "classes.dex")
        for name in pairs:
            archive.write(native / name, "lib/arm64-v8a/" + name)
    aligned = output / "aligned.apk"
    run("zipalign", [tools / "zipalign.exe", "-P", "16", "-f", "4", unaligned, aligned])
    keystore = output / "diagnostic-only.p12"
    run("keytool", [jdk / "bin/keytool.exe", "-genkeypair", "-keystore", keystore, "-storepass", "android",
                    "-keypass", "android", "-alias", "probe", "-keyalg", "RSA", "-keysize", "3072",
                    "-validity", "365", "-dname", "CN=Codex phone diagnostic", "-storetype", "PKCS12", "-noprompt"])
    apk = output / "codex-phone-probe.apk"
    signer = [java, "-jar", tools / "lib/apksigner.jar"]
    run("sign", [*signer, "sign", "--ks", keystore, "--ks-pass", "pass:android", "--key-pass", "pass:android",
                 "--ks-key-alias", "probe", "--out", apk, aligned])
    run("verify-signature", [*signer, "verify", "--verbose", "--print-certs", apk])
    run("verify-badging", [tools / "aapt.exe", "dump", "badging", apk])
    for item in inventories:
        if digest(inputs[item["path"]]) != item["sha256"] or digest(source / item["path"]) != item["sha256"]:
            raise ValueError("Source changed during build")
    report = {"schema": "codex.phone-probe.build.v1", "package": "com.ai.codex.phoneprobe",
              "apk": str(apk), "apkSha256": digest(apk), "sdk": 37, "minSdk": 30,
              "ndkProperties": (ndk / "source.properties").read_text(),
              "sourceManifestSha256": digest(output / "sources.json"),
              "native": {name: digest(native / name) for name in pairs},
              "androidExecuted": False, "productionPayload": False}
    (output / "build.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
