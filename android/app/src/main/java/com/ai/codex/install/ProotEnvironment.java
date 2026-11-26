package com.ai.codex.install;

import java.util.Map;

/**
 * Environment every packaged PRoot launch must agree on.
 *
 * <p>PRoot accelerates syscall translation by installing its own seccomp filter
 * and consuming {@code SECCOMP_RET_TRACE} events through
 * {@code PTRACE_EVENT_SECCOMP}. That acceleration is not reliable on current
 * Android kernels: once the guest execs a second time, the tracee dies with
 * {@code SIGSEGV} and the launcher reports only
 * {@code proot info: vpid 1: terminated with signal 11}, with no Python or PRoot
 * diagnostic of its own.
 *
 * <p>This was reproduced on a OnePlus 13 (Android 15, kernel 5.15.149) with the
 * packaged libraries, both inside a seccomp-filtered app process and from an
 * unfiltered root shell inside the app's mount namespace. The trigger is therefore
 * the vendored acceleration path itself, not only the zygote filter that app
 * processes happen to inherit.
 *
 * <p>A single direct {@code execve} still works, so the failure only appears once
 * the guest execs twice. Keyring preparation ({@code env} then {@code python3}),
 * package installation, the runtime smoke test and the desktop session all do, and
 * all of them failed at startup with
 * {@code Private provisioning process failed: exit=255 stage=UNKNOWN
 * code=NO_RECOGNIZED_DIAGNOSTIC}.
 *
 * <p>{@code PROOT_NO_SECCOMP=1} keeps PRoot on the plain {@code PTRACE_SYSCALL}
 * path, which survives nested exec. The GNU executor already pins this value for
 * its own launches ({@code tools/executor/gnu-runtime/gnu-managed-runtime.h});
 * the Android launch sites use this helper so they cannot drift from it again. The
 * variable is read by PRoot itself and is not forwarded to the guest, whose own
 * environment is supplied explicitly by {@code env -i}.
 */
public final class ProotEnvironment {
    public static final String NO_SECCOMP = "PROOT_NO_SECCOMP";

    private ProotEnvironment() {}

    /** Select PRoot's portable {@code PTRACE_SYSCALL} path for this launch. */
    public static void disableSeccompAcceleration(Map<String, String> environment) {
        environment.put(NO_SECCOMP, "1");
    }
}
