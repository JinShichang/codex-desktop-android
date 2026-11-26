#!/system/bin/sh
# Codex chroot launcher.
#
# Runs one guest command inside the app's Debian root with real chroot(2) instead
# of PRoot. Mounts are made in a private mount namespace (`unshare -m`), so the
# host mount table is never modified and nothing leaks between sessions.
#
# Caller arguments:
#   $1 root      absolute guest root (the app's private files/debian)
#   $2 uid       guest uid to become (the app's own uid; identity is real)
#   $3 home      guest HOME
#   $4 seconds   wall-clock bound for the guest process
#   remaining    command and arguments, executed inside the root
#
# CODEX_GUEST_ENV, when set, is word-split into extra NAME=value entries for the
# guest environment (for example XDG_RUNTIME_DIR). It is never used to pass a
# shell fragment: entries must look like NAME=value and are rejected otherwise.
#
# CODEX_EXTRA_BINDS, when set, is a semicolon-separated list of host paths that
# the guest must see at the same absolute path (bind mounted inside the private
# namespace). Entries may use "hostpath:guestpath" to change the guest path.
#
# It must already be running as root. Anything unexpected is refused instead of
# degrading into an unprotected launch.
#
# Parameters reach the namespace helper through the environment: `sh -c` assigns
# positional parameters from its own arguments, so passing them positionally
# would silently consume $0.

set -eu

root="$1"; uid="$2"; home="$3"; seconds="$4"
shift 4

fail() {
    echo "codex-chroot: $*" >&2
    exit 125
}

[ "$(id -u)" = "0" ] || fail "not root"
# Admitted roots: the activated guest tree, or the staging tree a first install
# is still preparing. Both are inside the app's private files directory; the
# staging form keeps chroot usable during that first run.
case "$root" in
    /data/user/0/*/files/debian|/data/data/*/files/debian) ;;
    /data/user/0/*/files/.codex-install/fresh/stages/*/root) ;;
    /data/data/*/files/.codex-install/fresh/stages/*/root) ;;
    *) fail "refusing root outside the app's private guest trees: $root" ;;
esac
[ -d "$root" ] || fail "guest root is missing"
[ -x "$root/usr/bin/env" ] || fail "guest root is not a prepared Debian tree"

# Resolve the real path once: a symlinked root could point the bind targets
# somewhere other than the tree validated above.
root=$(cd "$root" && pwd -P) || fail "cannot resolve guest root"

for mountpoint in proc sys dev dev/pts apex; do
    [ -d "$root/$mountpoint" ] || mkdir -p "$root/$mountpoint" || fail "cannot create /$mountpoint"
done

CODEX_ROOT="$root" CODEX_UID="$uid" CODEX_HOME="$home" CODEX_SECONDS="$seconds" \
exec unshare -m /system/bin/sh -c '
set -eu
root="$CODEX_ROOT"; uid="$CODEX_UID"; home="$CODEX_HOME"; seconds="$CODEX_SECONDS"

# Private propagation: mounts made here never reach the host namespace.
mount --make-rprivate / 2>/dev/null || true

for pair in /proc:proc /sys:sys /dev:dev /apex:apex; do
    src="${pair%%:*}"; dst="${pair##*:}"
    [ -d "$src" ] && mount --bind "$src" "$root/$dst" 2>/dev/null || true
done
[ -d /dev/pts ] && mount --bind /dev/pts "$root/dev/pts" 2>/dev/null || true

# Extra host paths the guest must see at the same absolute path. The keyring
# vault lives in no_backup/, outside the guest root, and the initializer opens
# it by its absolute Android path. Each entry is "hostpath" or "hostpath:guestpath"
# and is created (as a directory) inside the root before binding.
if [ -n "${CODEX_EXTRA_BINDS:-}" ]; then
    old_ifs="$IFS"; IFS=";"
    for entry in $CODEX_EXTRA_BINDS; do
        [ -n "$entry" ] || continue
        src="$entry"; dst="$entry"
        case "$entry" in
            *:*) src="${entry%%:*}"; dst="${entry#*:}" ;;
        esac
        [ -e "$src" ] || continue
        mkdir -p "$root$dst" 2>/dev/null || continue
        mount --bind "$src" "$root$dst" 2>/dev/null || \
            echo "codex-chroot: bind $src -> $dst failed" >&2
    done
    IFS="$old_ifs"
fi

# Confirm the essential trees really arrived; a silent failure here would make
# the guest look broken in confusing ways later.
[ -e "$root/proc/self" ] || { echo "codex-chroot: /proc is not mounted" >&2; exit 125; }
[ -e "$root/dev/null" ] || { echo "codex-chroot: /dev is not mounted" >&2; exit 125; }

[ -f "$root/etc/hostname" ] || echo codex > "$root/etc/hostname"

# Android'"'"'s /system/bin/chroot is toybox and has no --userspec, so the identity
# switch happens inside the guest with its own setpriv (util-linux). Doing it
# after chroot also means the guest passwd/group database is the source of truth.
cd "$root"
exec timeout -k 5 "$seconds" /system/bin/chroot "$root" \
    /usr/bin/setpriv --reuid "$uid" --regid "$uid" --clear-groups \
    /usr/bin/env -i HOME="$home" USER=codex LOGNAME=codex \
        PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
        TERM=xterm-256color \
        ${CODEX_GUEST_ENV:-} \
        "$@"
' codex-chroot "$@"
