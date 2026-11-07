# Production Python package inputs

`stage-production-package.py` reads the versioned
`production-python-sources.json` instead of extracting source names from the
private historical `downloads/native-app-server-host-v3-20260908/manifest.json`.
The manifest records current repository source paths, APK paths, byte lengths
and SHA-256 values. It is an input to source review, not a device qualification.

Before creating the package output, the packager checks all recorded bytes and
parses their real Python AST. It traverses imports from the three installed
bootstrap modules and `tools.executor.bionic-supervisor.factory`, including
relative imports, imports inside functions and branches, and literal
`importlib.import_module` calls. Imports of standard-library modules use a
versioned top-level list; no third-party dependencies are admitted there.
For modules with a standalone diagnostic `if __package__` branch, validation
uses the package branch that executes when loading the installed APK.

The two computed dynamic-import arguments are explicitly reviewed by source
path, normalized AST expression and possible module names. Missing or unused
declarations fail. New import loaders or aliases require an explicit checker
change and review; this check does not execute arbitrary Python to infer its
behavior. Source hashes require review when any code changes.

All 42 source outputs must be reachable, every local import must resolve, and
each parent ZIP package needs its initializer. Only the three declared empty
ZIP markers (`tools`, `tools.executor`, `tools.policy`) are generated. Missing
physical source files, including the real `bionic-supervisor/__init__.py`, fail.
Duplicate paths (also ignoring case), duplicate JSON keys, path traversal,
path aliases, hash/size mismatches and unused source entries fail as well.

The full source closure includes ordinary UID and PTY code in every candidate.
The existing native build attestations and deployment selection still control
whether those profiles can execute. This change does not select a profile or
alter managed-policy behavior. Native inventory, application-origin admission,
PTY/ripgrep build admission, and the original broker evidence remain required.
In particular, `downloads/runas-broker-v2/device-reports/run_broker_v2.json` is
still read verbatim; no replacement qualification is synthesized.

## Updating or verifying the source list

1. Review changes to the source code and its imports, including computed import
   targets. Keep the manifest and source changes together in the same review.
2. Update the exact file list and its byte lengths/SHA-256 values, and update the
   reviewed external/computed import declarations if necessary. Do not silently
   refresh pins while packaging.
3. Keep exact checkout bytes portable with `.gitattributes`. Most sources use
   LF; the already qualified `native_files.py` and
   `native_environment_unicode.py` deliberately retain their original bytes
   with `-text`. Do not normalize those files when refreshing hashes.
4. From the repository root, run:

   ```sh
   python -B tools/executor/runas-runtime/test-package-source-closure.py
   ```

The offline tests use fresh temporary directories under `work/` and clean up
their own fixtures. They require no downloads, native compilation, old build
artifacts, ADB or Android execution. The current list contains 42 output files
and 468495 bytes, including three zero-byte generated markers.

## Native inputs still requiring a separate migration

This source-list change alone does not make a public clone capable of building
the complete production candidate. `stage-production-native.py` still requires:

- The exact historical Python stage under
  `downloads/shizuku-lab/runtime-stage-20260907`, with its pinned manifest hash.
- The frozen supervisor/native-files build under
  `downloads/bionic-supervisor/codex-bionic-supervisor-qKM94iHA`, with its pinned
  `BINARIES.sha256` digest.
- The exact transport/cwd libraries under
  `tools/executor/shizuku-lab/build/frozen-transport-jni/arm64-v8a`, with two
  individually pinned ELF hashes.

A subsequent migration should make each input an explicit path plus a
versioned, source-attested admission contract. For Python, regenerate the stage
from the hash-pinned official archive via `bionic-runtime/stage-runtime.py`,
verify the production-prefix CLI build and every data/native/alias inventory
entry, and record the new stage's actual manifest. For the supervisor and file
helpers, retain the real sources/compiler commands, inspect ARM64/API35 ELF
outputs, and verify repeated native builds against their actual records. For
transport/cwd, similarly record the original JNI sources and build recipe;
the separate application-transport build does not replace these two libraries.

Each new contract should reject incomplete, altered or mismatched records and
retain the original historical-input route explicitly if it remains supported.
Copying newly built files into the old paths or changing the old digest pins
would not establish the required provenance. None of these native admission
changes are implemented by this source-list patch.
