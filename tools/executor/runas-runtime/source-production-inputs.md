# Fresh source-built native inputs

The public alpha's default production stager retains its historical byte pins.
For a clean build, select the new source input profile explicitly. It does not
relax the managed executor, Landlock admission, or client version checks.

1. Build the pinned official Python CLI, the production-prefix Bash double
   build, and the model/direct runners with the existing recipes and NDK r29.
2. Run `build-runtime-support.py --ndk NDK --output NEW_BUILD` to compile the
   file helpers, legacy JNI transport and cwd library twice. Both compilations
   must match; source snapshots and actual ELF checks are retained.
3. Run `tools/executor/bionic-runtime/stage-runtime.py` with the pinned official
   Python archive and the selected Python/Bash executables.
4. Give `stage-production-native.py` all three explicit options:
   `--source-runtime-stage`, `--source-python-archive`, `--source-support-build`,
   and the required `--model-build`. Existing CLI/Bash/direct options still apply.
   Admission reconstructs the complete runtime from its authenticated archive
   and checks every payload byte, alias and manifest field except descriptive
   origin strings. The Python CLI source and its build record are also checked.
5. Build the Android app bootstrap against this stage's generated inventory.
   Run `stage-production-package.py` with `--launch-origin android-app`, its
   app transport build, `--ordinary-uid`, and `--source-build-candidate`.
   This readmits the fresh inputs before packaging and writes evidence with
   scope `source-build-only` and `androidProductionExecuted: false`.
   Historical broker qualification bytes are used only by the original profile.
6. Select a JNI directory containing just the two transport libraries through
   `codexFrozenTransportJni`, and the corresponding support build through
   `codexRuntimeSupportBuild`. Gradle checks the source inventory against the
   current checkout and both compiled transport copies. The candidate builder
   derives the support build from the explicitly selected package provenance.

Run the artifact admission regressions with:

```sh
python3 -B tools/executor/runas-runtime/test-source-build-inputs.py \
  --support-build downloads/YOUR_SUPPORT_BUILD \
  --native-stage downloads/YOUR_NATIVE_STAGE
```

These checks cover genuine build inputs and refusal of changed ELF, repeat
compile, source, JSON, NDK, file alias and standard-library data. They do not
execute Android code. Run `verify-production-apk.py` on the final APK as well;
its fresh profile also checks evidence scope and the complete native inventory.

The fresh profile does not make a complete installation image or qualify a
desktop client. Those require separately authenticated Debian, GPU, engine and
client integration inputs, followed by actual application UID/device tests.
