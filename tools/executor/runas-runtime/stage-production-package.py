"""Package the explicit native candidate without claiming end-to-end qualification."""
import argparse
import ast
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[3]
TRANSPORT = ROOT / "tools/executor/shizuku-service/transport/src/main/assets/codex-executor"
SOURCE_INPUTS = Path(__file__).with_name("production-python-sources.json")
SOURCE_ROOTS = ("codex_app_bootstrap", "codex_native_bootstrap", "codex_shizuku_bootstrap",
                "tools.executor.bionic-supervisor.factory")
EMPTY_PACKAGES = {"tools/__init__.py", "tools/executor/__init__.py", "tools/policy/__init__.py"}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def package_sources(root=ROOT, manifest=SOURCE_INPUTS):
    """Read reviewed current bytes and prove their APK import closure before output.

    Empty ZIP package markers are explicit inputs, not substitutes for missing
    source files. Dynamic imports with computed arguments need a reviewed exact
    AST expression and module list; they cannot silently enlarge the package.
    """
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate source manifest JSON key: " + key)
            result[key] = value
        return result

    record = json.loads(manifest.read_bytes(), object_pairs_hook=unique_object)
    if (type(record) is not dict or set(record) != {"schema", "files", "externalModules", "dynamicImports"}
            or record["schema"] != "codex.production-python-sources.v1"
            or type(record["files"]) is not list):
        raise ValueError("Invalid production Python source manifest")

    def relative_path(value):
        if type(value) is not str:
            raise ValueError("Source path must be a string")
        path = PurePosixPath(value)
        if (not value or path.is_absolute() or path.as_posix() != value or ".." in path.parts
                or "\\" in value or ":" in value or not value.endswith(".py")):
            raise ValueError("Invalid production source path: " + value)
        return path

    sources, modules, trees, seen_paths, seen_inputs = {}, {}, {}, set(), set()
    for row in record["files"]:
        if type(row) is not dict or set(row) != {"path", "source", "bytes", "sha256"}:
            raise ValueError("Invalid production source entry")
        path = relative_path(row["path"])
        name = path.as_posix()
        if name.casefold() in seen_paths:
            raise ValueError("Duplicate production source path: " + name)
        seen_paths.add(name.casefold())
        if row["source"] is None:
            if name not in EMPTY_PACKAGES:
                raise ValueError("Undeclared generated package marker: " + name)
            data = b""
        else:
            source = relative_path(row["source"])
            transport_source = TRANSPORT.relative_to(ROOT).as_posix() + "/" + name
            if (name in EMPTY_PACKAGES or row["source"] not in (name, transport_source)
                    or not (name.startswith("tools/") or "/" not in name)):
                raise ValueError("Unexpected production source mapping: " + name)
            if row["source"].casefold() in seen_inputs:
                raise ValueError("Duplicate production source input: " + row["source"])
            seen_inputs.add(row["source"].casefold())
            target = root
            for component in source.parts:
                target /= component
                if target.is_symlink() or target.is_junction():
                    raise ValueError("Production source cannot contain path aliases: " + str(source))
            target.resolve(strict=True).relative_to(root.resolve(strict=True))
            if not target.is_file():
                raise ValueError("Production source must be a regular file: " + str(source))
            data = target.read_bytes()
        if (type(row["bytes"]) is not int or len(data) != row["bytes"]
                or type(row["sha256"]) is not str or re.fullmatch(r"[0-9a-f]{64}", row["sha256"]) is None
                or digest(data) != row["sha256"]):
            raise ValueError("Production source hash or length differs: " + name)
        compile(data, name, "exec")
        sources[name] = data
        module = (name[:-len("/__init__.py")] if name.endswith("/__init__.py") else name[:-3]).replace("/", ".")
        if module in modules:
            raise ValueError("Ambiguous production source module: " + module)
        modules[module] = name
        trees[name] = ast.parse(data, filename=name)
    if not EMPTY_PACKAGES <= set(sources):
        raise ValueError("Production ZIP package markers are incomplete")
    external = record["externalModules"]
    if (type(external) is not list or any(type(name) is not str for name in external)
            or len(external) != len(set(external)) or not set(external) <= sys.stdlib_module_names):
        raise ValueError("External source imports must name unique standard-library modules")
    if type(record["dynamicImports"]) is not list:
        raise ValueError("Computed import declarations must be a list")
    declarations = {}
    for row in record["dynamicImports"]:
        if (type(row) is not dict or set(row) != {"path", "expression", "modules"}
                or row["path"] not in sources or type(row["expression"]) is not str
                or type(row["modules"]) is not list or not row["modules"]
                or any(type(name) is not str or name not in modules for name in row["modules"])
                or len(set(row["modules"])) != len(row["modules"])):
            raise ValueError("Invalid computed import declaration")
        key = (row["path"], row["expression"])
        if key in declarations:
            raise ValueError("Duplicate computed import declaration")
        declarations[key] = row["modules"]
    reached, used_external, used_dynamic = set(), set(), set()
    pending = list(SOURCE_ROOTS)

    def require(module):
        if module in modules:
            pending.append(module)
            parts = module.split(".")
            for end in range(1, len(parts)):
                package = ".".join(parts[:end])
                if modules.get(package) != package.replace(".", "/") + "/__init__.py":
                    raise ValueError("Missing ZIP package initializer: " + package)
                pending.append(package)
        elif module.split(".")[0] in external:
            used_external.add(module.split(".")[0])
        else:
            raise ValueError("Unresolved production source import: " + module)

    class Imports(ast.NodeVisitor):
        def visit_If(self, node):
            # These modules also support standalone diagnostics. The APK loads
            # them with their declared package, so only that branch can execute.
            if isinstance(node.test, ast.Name) and node.test.id == "__package__":
                for child in node.body if package else node.orelse:
                    self.visit(child)
            else:
                self.generic_visit(node)

        def visit_Import(self, node):
            for alias in node.names:
                if alias.name.split(".")[0] == "importlib" and alias.asname is not None:
                    raise ValueError("Unreviewed importlib alias: " + name)
                require(alias.name)

        def visit_ImportFrom(self, node):
            if node.level:
                parts = package.split(".") if package else []
                if node.level > len(parts):
                    raise ValueError("Relative import escapes production package: " + name)
                base = ".".join(parts[:len(parts) - node.level + 1])
                imported = base + ("." + node.module if node.module else "")
            else:
                imported = node.module or ""
            if imported == "importlib" or imported.startswith("importlib."):
                raise ValueError("Unreviewed importlib member alias: " + name)
            require(imported)
            for alias in node.names:
                candidate = imported + "." + alias.name
                if candidate in modules:
                    require(candidate)

        def visit_Call(self, node):
            # Current sources use only this dynamic import form. Reject aliases
            # and other loaders below rather than pretending they were checked.
            if isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) and node.func.value.id == "importlib" and node.func.attr == "import_module":
                if len(node.args) != 1 or node.keywords:
                    raise ValueError("Unreviewed dynamic import signature: " + name)
                argument = node.args[0]
                if isinstance(argument, ast.Constant) and type(argument.value) is str:
                    require(argument.value)
                else:
                    key = (name, ast.unparse(argument))
                    if key not in declarations:
                        raise ValueError("Unreviewed computed import: " + repr(key))
                    used_dynamic.add(key)
                    for imported in declarations[key]:
                        require(imported)
            elif ((isinstance(node.func, ast.Name) and node.func.id in ("__import__", "import_module"))
                    or (isinstance(node.func, ast.Attribute) and node.func.attr in (
                        "__import__", "import_module", "spec_from_file_location", "exec_module", "load_module"))):
                raise ValueError("Unreviewed dynamic loader: " + name)
            self.generic_visit(node)

    while pending:
        module = pending.pop()
        if module not in modules:
            raise ValueError("Missing production source entrypoint: " + module)
        name = modules[module]
        if name in reached:
            continue
        reached.add(name)
        package = module if name.endswith("/__init__.py") else module.rpartition(".")[0]
        Imports().visit(trees[name])
    if reached != set(sources) or used_external != set(external) or used_dynamic != set(declarations):
        raise ValueError("Production source inventory differs from its reachable import closure")
    return sources


def admit_stage_pty(stage, inventory, *, ordinary_uid):
    """Validate the optional real stage before any package output is created."""
    name = "libcodex_direct_pty_supervisor.so"
    binary = stage / "jniLibs/arm64-v8a" / name
    if "ordinaryPtyBuild" not in inventory and not binary.exists():
        return None
    if not ordinary_uid:
        raise ValueError("Model PTY cannot be selected outside the ordinary UID profile")
    provenance = inventory.get("ordinaryPtyBuild")
    if type(provenance) is not dict or type(provenance.get("path")) is not str:
        raise ValueError("Model PTY requires its reviewed build attestation")
    spec = importlib.util.spec_from_file_location("codex_package_pty_stage",
        Path(__file__).with_name("pty-admission.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    runner, actual = module.production_pty(ROOT / provenance["path"])
    if provenance != actual or binary.read_bytes() != runner:
        raise ValueError("Model PTY staged bytes differ from its reviewed build")
    expected = {"name": name, "bytes": len(runner), "sha256": digest(runner)}
    runtime = json.loads((stage / "assets/codex-python-runtime.json").read_bytes())
    if [row for row in runtime["nativeFiles"] if row["name"] == name] != [expected]:
        raise ValueError("Model PTY stage lacks its exact runtime inventory entry")
    recorded = {"path": "jniLibs/arm64-v8a/" + name, "bytes": len(runner), "sha256": digest(runner)}
    if [row for row in inventory["files"] if row["path"] == recorded["path"]] != [recorded]:
        raise ValueError("Model PTY stage lacks its exact frozen file inventory entry")
    return actual


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native-stage", type=Path, required=True)
    parser.add_argument("--admission-build", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--host-v2", action="store_true")
    parser.add_argument("--launch-origin", choices=("run-as", "android-app"), default="run-as")
    parser.add_argument("--app-transport-build", type=Path)
    parser.add_argument("--ordinary-uid", action="store_true",
                        help="Explicitly include ordinary Android UID execution for upstream Full access")
    parser.add_argument("--source-build-candidate", action="store_true",
                        help="Use fresh admitted source-build evidence; makes no device-qualification claim")
    args = parser.parse_args()
    stage, admission, output = (getattr(args, name).resolve() for name in ("native_stage", "admission_build", "output"))
    for path in (stage, admission, output):
        path.relative_to(ROOT)
    inventory = json.loads((stage / "manifest.json").read_text())
    source_build_inputs = None
    if args.source_build_candidate:
        if (args.launch_origin != "android-app" or not args.ordinary_uid
                or "sourceBuildInputs" not in inventory):
            raise ValueError("Source-build candidate requires explicit fresh inputs, Android app launch and ordinary UID")
        spec = importlib.util.spec_from_file_location("codex_package_fresh_inputs",
            Path(__file__).with_name("source-production-inputs.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source_build_inputs = module.readmit(stage, inventory)
    elif "sourceBuildInputs" in inventory:
        raise ValueError("Fresh inputs require the explicit source-build candidate evidence profile")
    for item in inventory["files"]:
        data = (stage / item["path"]).read_bytes()
        if len(data) != item["bytes"] or digest(data) != item["sha256"]:
            raise ValueError("Frozen native stage differs: " + item["path"])
    build = json.loads((admission / "build.json").read_text())
    if digest((stage / "runtime-inventory.h").read_bytes()) != build["inventorySha256"]:
        raise ValueError("Admission inventory differs from the selected native stage")
    app_launch = None
    if args.launch_origin == "android-app":
        if args.app_transport_build is None:
            raise ValueError("Application launch requires its separate source-attested JNI build")
        spec = importlib.util.spec_from_file_location("codex_app_launch_admission", Path(__file__).with_name("app-launch-admission.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        app_launch, launch_libraries = module.admit_builds(admission, args.app_transport_build,
                                                         (stage / "runtime-inventory.h").read_bytes())
    else:
        if args.app_transport_build is not None or build.get("schema") != "codex.native-admission-build.v1" or "launchOrigin" in build:
            raise ValueError("Run-as launch cannot use an application-origin build")
        bootstrap = (admission / "libcodex_native_bootstrap.so").read_bytes()
        if digest(bootstrap) != build["executableSha256"]:
            raise ValueError("Admission build digest differs")
        launch_libraries = {"libcodex_native_bootstrap.so": bootstrap}
    direct_name = "libcodex_direct_runner.so"
    if args.ordinary_uid and ("ordinaryUidBuild" not in inventory
            or not (stage / "jniLibs/arm64-v8a" / direct_name).is_file()):
        raise ValueError("Ordinary UID selection requires its source-attested native-stage runner")
    if args.ordinary_uid:
        provenance = inventory["ordinaryUidBuild"]
        if type(provenance) is not dict or type(provenance.get("path")) is not str:
            raise ValueError("Ordinary UID build provenance is malformed")
        spec = importlib.util.spec_from_file_location("codex_package_native_stage",
            Path(__file__).with_name("stage-production-native.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        runner, actual = module.production_direct(ROOT / provenance["path"])
        if provenance != actual or (stage / "jniLibs/arm64-v8a" / direct_name).read_bytes() != runner:
            raise ValueError("Ordinary UID stage differs from its actual build provenance and compiled runner")
    pty_name = "libcodex_direct_pty_supervisor.so"
    admit_stage_pty(stage, inventory, ordinary_uid=args.ordinary_uid)
    ripgrep_names = {"libcodex_rg.so", "libcodex_pcre2_jit_probe.so"}
    staged_ripgrep = {name for name in ripgrep_names if (stage / "jniLibs/arm64-v8a" / name).exists()}
    if staged_ripgrep or "ripgrepBuild" in inventory:
        provenance = inventory.get("ripgrepBuild")
        if (staged_ripgrep != ripgrep_names or type(provenance) is not dict
                or type(provenance.get("path")) is not str):
            raise ValueError("Ripgrep selection requires both attested native outputs")
        spec = importlib.util.spec_from_file_location("codex_package_ripgrep_stage",
            Path(__file__).with_name("stage-production-native.py"))
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        binaries, actual = module.production_ripgrep(ROOT / provenance["path"])
        if (provenance != actual or set(binaries) != ripgrep_names
                or any((stage / "jniLibs/arm64-v8a" / name).read_bytes() != data
                       for name, data in binaries.items())):
            raise ValueError("Ripgrep stage differs from its source-attested native build")
        notices = inventory.get("ripgrepToolchainNotices")
        if type(notices) is not dict or type(notices.get("path")) is not str:
            raise ValueError("Ripgrep stage lacks its toolchain notice attestation")
        notice_assets, actual_notices = module.production_toolchain_notices(ROOT / notices["path"])
        if notices != actual_notices:
            raise ValueError("Ripgrep toolchain notice stage provenance differs")
        actual_names = {p.relative_to(stage / "assets").as_posix()
                       for p in (stage / "assets/notices/ripgrep-toolchain").rglob("*") if p.is_file()}
        if (actual_names != set(notice_assets)
                or any((stage / "assets" / name).read_bytes() != data for name, data in notice_assets.items())):
            raise ValueError("Ripgrep toolchain notice staged assets differ")
    elif ("ripgrepToolchainNotices" in inventory or (stage / "assets/notices/ripgrep-toolchain").exists()):
        raise ValueError("Toolchain notices staged without native ripgrep")
    sources = package_sources()
    output.mkdir(parents=True, exist_ok=False)
    shutil.copytree(stage / "assets", output / "assets")
    shutil.copytree(stage / "jniLibs", output / "jniLibs")
    assets, jni = output / "assets", output / "jniLibs/arm64-v8a"
    for name, data in launch_libraries.items():
        if (jni / name).exists():
            raise ValueError("Native stage unexpectedly contains a launch executable: " + name)
        (jni / name).write_bytes(data)
    native = {p.name: digest(p.read_bytes()) for p in sorted(jni.iterdir())}
    # The frozen transport module is the unique packager of these same bytes.
    for name in ("libcodex_shizuku_transport.so", "libcodex_bionic_cwd.so"):
        (jni / name).unlink()
    runtime_path = "/data/user/0/com.ai.codex/files/native-runtime-v1/python"
    marker = "@nativeLibraryDir/"
    config = {
        "schema": "codex.native.deployment.v1", "packageName": "com.ai.codex",
        "pythonLibrary": "libcodex_python_cli.so", "pythonSha256": native["libcodex_python_cli.so"],
        "nativeLibraries": native,
        "pythonRuntime": {"path": runtime_path, "manifestAsset": "codex-python-runtime.json",
                          "manifestSha256": digest((assets / "codex-python-runtime.json").read_bytes())},
        "backendFactory": "tools.executor.bionic-supervisor.factory:factory",
        "backendOptions": {
            "helper": marker + "libcodex_native_files.so", "handleHelper": marker + "libcodex_native_file_handle.so",
            "processRunner": marker + "libcodex_bionic_supervisor.so",
            "executables": {"bash": marker + "libcodex_bash.so", "python": marker + "libcodex_python_cli.so",
                            "python3": marker + "libcodex_python_cli.so"},
            "runtime": [{"path": path, "execute": execute} for path, execute in (
                ("/system/lib64", True), ("/system/bin", True), ("/apex/com.android.runtime", True),
                ("/linkerconfig/ld.config.txt", False), ("/dev/__properties__", False),
                ("/apex/com.android.tzdata/etc/tz/tzdata", False), (runtime_path, False))],
            "limits": {},
            "cwdShim": {"path": marker + "libcodex_bionic_cwd.so", "sha256": native["libcodex_bionic_cwd.so"]}}}
    if app_launch is not None:
        config.update(schema="codex.native.deployment.v2", launchOrigin="android-app")
        (assets / "codex-app-launch-build.json").write_text(json.dumps(app_launch, indent=2) + "\n")
    if args.ordinary_uid:
        config["backendOptions"]["ordinaryUid"] = {"processRunner": marker + direct_name, "limits": {}}
        if "ordinaryPtyBuild" in inventory:
            config["backendOptions"]["ordinaryUid"]["ptyProcessRunner"] = marker + pty_name
    if "ripgrepBuild" in inventory:
        config["backendOptions"]["executables"]["rg"] = marker + "libcodex_rg.so"
    (assets / "codex-executor-deployment.json").write_text(json.dumps(config, indent=2) + "\n")
    if args.host_v2:
        runner = "libcodex_host_supervisor.so"
        if runner not in native:
            raise ValueError("Explicit human v2 selection requires its attested native-stage ELF")
        (assets / "codex-host-deployment.json").write_text(json.dumps({
            "schema": "codex.host.v2", "runner": runner, "runnerSha256": native[runner]}, indent=2) + "\n")
    source_manifest = []
    # Ship the whole reviewed closure for every candidate. The existing native
    # attestations and deployment options alone select ordinary UID and PTY.
    for relative, data in sorted(sources.items()):
        target = assets / "codex-executor" / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        source_manifest.append({"path": relative, "sha256": digest(data)})
    (assets / "codex-executor-manifest.json").write_text(json.dumps(source_manifest, indent=2) + "\n")
    if source_build_inputs is not None:
        # These are genuine build receipts. They must never assert that the new
        # application, broker or controller has passed Android qualification.
        evidence = (json.dumps({"schema": "codex.native-source-build-evidence.v1",
            "scope": "source-build-only", "androidProductionExecuted": False,
            "sourceBuildInputs": source_build_inputs,
            "nativeStageManifestSha256": digest((stage / "manifest.json").read_bytes()),
            "nativeLibraries": native}, indent=2) + "\n").encode()
    else:
        # Preserve historical broker qualification bytes and their actual scope.
        evidence = (ROOT / "downloads/runas-broker-v2/device-reports/run_broker_v2.json").read_bytes()
    (assets / "codex-executor-evidence.json").write_bytes(evidence)
    qualification = {"schema": "codex.native.package.v1", "scope": "native-production-candidate",
        "androidProductionExecuted": False,
        "deploymentSha256": digest((assets / "codex-executor-deployment.json").read_bytes()),
        "sourceManifestSha256": digest((assets / "codex-executor-manifest.json").read_bytes()),
        "evidenceSha256": digest(evidence)}
    if source_build_inputs is not None:
        qualification["sourceBuildInputs"] = source_build_inputs
    if app_launch is not None:
        qualification.update(launchOrigin="android-app",
            appLaunchBuildSha256=digest((assets / "codex-app-launch-build.json").read_bytes()))
    if args.host_v2:
        qualification["hostDeploymentSha256"] = digest((assets / "codex-host-deployment.json").read_bytes())
    if args.ordinary_uid:
        qualification["ordinaryUidBuild"] = inventory["ordinaryUidBuild"]
    if "ordinaryPtyBuild" in inventory:
        qualification["ordinaryPtyBuild"] = inventory["ordinaryPtyBuild"]
    if "ripgrepBuild" in inventory:
        qualification["ripgrepBuild"] = inventory["ripgrepBuild"]
        qualification["ripgrepNoticesSha256"] = digest((assets / "notices/ripgrep.txt").read_bytes())
        qualification["ripgrepToolchainNotices"] = inventory["ripgrepToolchainNotices"]
    (assets / "codex-executor-qualification.json").write_text(json.dumps(qualification, indent=2) + "\n")
    print(json.dumps({"output": str(output), "sources": len(source_manifest), "nativeLibraries": len(native),
                      "androidProductionExecuted": False}))


if __name__ == "__main__":
    main()
