#!/bin/bash
set -euo pipefail
# Admission is read-only and precedes DBus, runtime directories, AGENTS and
# integration. An unknown client must not start or alter the user's context.
workspace_adapter_args=(--asar /usr/lib/chatgpt/resources/app.asar
    --state /usr/local/share/codex/workspace-runtime/client-backup)
python3 -B /usr/local/lib/codex/install-workspace-provider.py --check "${workspace_adapter_args[@]}"
if [[ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]]; then
    exec dbus-run-session -- "$0"
fi
# UTF-8 is available in the pristine Debian base; Electron selects Simplified Chinese.
export LANG="${LANG:-C.UTF-8}"
export LANGUAGE="${LANGUAGE:-zh_CN:zh:en}"
export CODEX_CDP_PORT=9223
export XDG_RUNTIME_DIR="/tmp/runtime-$(id -u)"
mkdir -p "$XDG_RUNTIME_DIR" "$HOME/.local/state"
chmod 700 "$XDG_RUNTIME_DIR"
# Maintain diagnostic metadata; retire the legacy global instructions once before the client
# starts. The helper resolves the selected guest account and preserves user
# instructions; it neither alters Codex config nor claims model delivery.
context_args=(--clear-global-instructions-once --guest-root / --manifest /usr/local/share/codex/agent-environment.v1.json)
if [[ -n "${CODEX_HOME:-}" ]]; then
    context_args+=(--codex-home "$CODEX_HOME")
fi
python3 -B /usr/local/lib/codex/codex_agent_context.py "${context_args[@]}"

# A local, explicitly branded ARM64 distribution owns acquisition and repair.
# The adapter is applied only to fingerprint-reviewed official client bytes;
# the original ASAR remains in the provider's backup directory.
if [[ "${CODEX_PHONE_CLIENT_COMPAT:-0}" == 1 || -f /usr/local/share/codex/workspace-runtime/provider.json ]]; then
    python3 -B /usr/local/lib/codex/install-workspace-provider.py \
        "${workspace_adapter_args[@]}"
fi
if [[ -f /usr/local/share/codex/workspace-runtime/provider.json ]]; then
    export CODEX_WORKSPACE_PROVIDER=1
fi
timeout 20s python3 /usr/local/lib/codex/codex_keyring.py
python3 -B /usr/local/lib/codex/codex_phone_profile.py
python3 -B /usr/local/lib/codex/install_phone_mcp.py
if [[ "${CODEX_PHONE_CLIENT_COMPAT:-0}" == 1 ]]; then
    # Configuration uses the same ordinary app-UID filesystem as execution.
    export CODEX_NATIVE_PROJECT_ACCESS=ordinary-uid
    # GTK native pickers are independent of the Chromium content zoom.
    export GDK_SCALE=2 GDK_DPI_SCALE=1
    python3 -B /usr/local/lib/codex/codex_native_dialogs.py prepare
fi
# Keep our driver separate from both Debian Mesa and the official client. This
# selects libraries; inspect-gpu.py must still verify the client's actual use.
gpu_prefix=/opt/codex-gpu/mesa-26.2.2-codex5
if [[ -d "$gpu_prefix" ]]; then
    for required in lib/libGL.so.1 lib/libEGL.so.1 lib/libvulkan_freedreno.so share/vulkan/icd.d/freedreno_icd.aarch64.json; do
        if [[ ! -r "$gpu_prefix/$required" ]]; then
            echo "Codex GPU installation incomplete: $required" >&2
            exit 1
        fi
    done
    export VK_DRIVER_FILES="$gpu_prefix/share/vulkan/icd.d/freedreno_icd.aarch64.json"
    export LD_LIBRARY_PATH="$gpu_prefix/lib${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    export MESA_LOADER_DRIVER_OVERRIDE=zink
    export GALLIUM_DRIVER=zink
    echo "Codex GPU driver selected: Mesa 26.2.2 Zink/Turnip"
else
    echo "Codex GPU driver not installed; using Debian graphics libraries" >&2
fi
if [[ -f /usr/local/lib/codex/libquiet_xext.so ]]; then
    export LD_PRELOAD="/usr/local/lib/codex/libquiet_xext.so${LD_PRELOAD:+:$LD_PRELOAD}"
fi
python3 -u /usr/local/lib/codex/codex_ime.py > "$HOME/.local/state/codex-ime.log" 2>&1 &
ime_pid=$!
# A window manager implements maximize, modal dialogs and display-size changes.
# Starting the application alone leaves these X11 requests unhandled.
xfwm4 > "$HOME/.local/state/codex-wm.log" 2>&1 &
wm_pid=$!
# Start user-space PulseAudio server for native microphone and speaker bridging
export PULSE_SERVER=127.0.0.1:4713
if [[ -f /usr/local/share/codex/pulseaudio.pa ]]; then
    pulseaudio -k 2>/dev/null || true
    pulseaudio -n -F /usr/local/share/codex/pulseaudio.pa --daemonize=true || true
fi
dialogs_pid=""
trap 'kill "$ime_pid" "$wm_pid" ${dialogs_pid:+"$dialogs_pid"} 2>/dev/null || true; pulseaudio -k 2>/dev/null || true' EXIT
# Explicit, user-approved compatibility mode for Chromium under Android PRoot.
# Android app isolation and Codex permission routing are separate and unchanged.
client_compat_args=()
if [[ "${CODEX_PHONE_CLIENT_COMPAT:-0}" == 1 ]]; then
    client_compat_args+=(--no-sandbox --no-zygote --enable-logging=stderr)
fi
chatgpt "${client_compat_args[@]}" --lang="${CODEX_LANGUAGE:-zh-CN}" --ozone-platform=x11 --force-device-scale-factor="${CODEX_SCALE:-1.5}" --start-maximized --remote-debugging-address=127.0.0.1 --remote-debugging-port="$CODEX_CDP_PORT" &
client_pid=$!
if [[ "${CODEX_PHONE_CLIENT_COMPAT:-0}" == 1 ]]; then
    python3 -B /usr/local/lib/codex/codex_native_dialogs.py watch --pid "$client_pid" \
        > "$HOME/.local/state/codex-dialogs.log" 2>&1 &
    dialogs_pid=$!
fi
# Ask the window manager for fullscreen using the application's actual window ID.
# EWMH fullscreen follows XRandR/IME resizes without a fixed pixel geometry.
while kill -0 "$client_pid" 2>/dev/null; do
    if clients=$(wmctrl -lpx 2>/dev/null); then
        window=$(awk -v pid="$client_pid" '$3 == pid { print $1; exit }' <<< "$clients")
    else
        window=""
    fi
    if [[ -n "$window" ]]; then
        # The phone adapter uses BrowserWindow.setFullScreen(true), the F11 path.
        # Do not race that with an outer-window-only EWMH state change.
        if [[ "${CODEX_PHONE_CLIENT_COMPAT:-0}" != 1 ]]; then
            wmctrl -i -r "$window" -b add,fullscreen
        fi
        # Actual client window discovered; bind the signal to this Android launch.
        if [[ -n "${CODEX_SESSION_TOKEN:-}" ]]; then
            printf '%s\n' "$CODEX_SESSION_TOKEN" > /tmp/codex-client-ready
        fi
        break
    fi
    sleep 0.1
done
client_exit=0
wait "$client_pid" || client_exit=$?
# A normal desktop Quit is a user stop, not crash-recovery authority. Bind the
# receipt to this launch; a leftover receipt cannot stop a later generation.
if [[ "$client_exit" == 0 && -n "${CODEX_SESSION_TOKEN:-}" ]]; then
    printf '%s\n' "$CODEX_SESSION_TOKEN" > /tmp/codex-client-stopped
fi
exit "$client_exit"
