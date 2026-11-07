#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname -- "${BASH_SOURCE[0]}")/../.."
out=$(mktemp -d /tmp/codex-device-policy.XXXXXX)
trap 'rm -rf -- "$out"' EXIT
: "${JAVA_HOME:?Set JAVA_HOME to a JDK 21 installation}"
"$JAVA_HOME/bin/javac" -encoding UTF-8 -d "$out" android/app/src/main/java/com/ai/codex/{DeviceCommandPolicy,DeviceFilePolicy,CodexDeviceFileRead}.java tools/device-policy/{DevicePolicyCheck,DeviceFilesCheck}.java
cc -shared -fPIC -Wall -Wextra -Werror -I"$JAVA_HOME/include" -I"$JAVA_HOME/include/linux" android/install-native/device-files.c -o "$out/libcodex-device-files.so"
"$JAVA_HOME/bin/java" -cp "$out" com.ai.codex.DevicePolicyCheck
"$JAVA_HOME/bin/java" --add-opens java.base/java.io=ALL-UNNAMED -Djava.library.path="$out" -cp "$out" com.ai.codex.DeviceFilesCheck
python3 -B -m unittest tools.context.test_codex_agent_context tools.install.test_guest_bundle
json=${CODEX_JSON_JAR:-}
if [[ -z "$json" ]]; then
    json=$(find "${GRADLE_USER_HOME:-$HOME/.gradle}/caches/modules-2/files-2.1/org.json/json" -name '*.jar' -type f -print -quit 2>/dev/null || true)
fi
[[ -f "$json" ]] || { printf '%s\n' 'Set CODEX_JSON_JAR to the local org.json dependency jar.' >&2; exit 1; }
"$JAVA_HOME/bin/javac" -encoding UTF-8 -cp "$json" -d "$out" tools/device-policy/fixtures/android/{content/Context,content/pm/ApplicationInfo,util/AtomicFile,system/Os}.java android/app/src/main/java/com/ai/codex/CodexDeviceHttp.java tools/device-policy/DeviceHttpCheck.java
"$JAVA_HOME/bin/java" -cp "$out:$json" com.ai.codex.DeviceHttpCheck
"$JAVA_HOME/bin/javac" -encoding UTF-8 -cp "$out:$json" -d "$out" tools/device-policy/fixtures/com/ai/codex/CodexDeviceFeatures.java android/app/src/main/java/com/ai/codex/CodexRootChannel.java tools/device-policy/RootEntryCheck.java
"$JAVA_HOME/bin/java" -cp "$out:$json" com.ai.codex.RootEntryCheck
