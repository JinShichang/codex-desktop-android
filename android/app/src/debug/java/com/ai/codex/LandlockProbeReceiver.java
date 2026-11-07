package com.ai.codex;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;
import java.io.File;
import java.util.concurrent.TimeUnit;

/** Runs fixed native diagnostics with the real app UID and Zygote filters. */
public final class LandlockProbeReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        PendingResult pending = goAsync();
        new Thread(() -> {
            Process process = null;
            try {
                // Only these compiled-in experiments may run. There is no
                // externally supplied command, path, or production policy.
                boolean broker = "com.ai.codex.PROBE_BROKER".equals(intent.getAction());
                boolean proot = "com.ai.codex.PROBE_PROOT".equals(intent.getAction());
                boolean shell = "com.ai.codex.PROBE_SHELL".equals(intent.getAction());
                boolean linuxShell = "com.ai.codex.PROBE_LINUX_SHELL".equals(intent.getAction());
                String name = linuxShell ? "linux-shell" : proot ? "proot" : shell ? "shell" : broker ? "broker" : "landlock";
                File output = new File(context.getCacheDir(), name + "-probe.log");
                String nativeDir = context.getApplicationInfo().nativeLibraryDir;
                ProcessBuilder diagnostic = proot || linuxShell
                    ? new ProcessBuilder(nativeDir + "/libcodex-" + name + "-probe.so", context.getDataDir().getAbsolutePath(), nativeDir)
                    : new ProcessBuilder(nativeDir + "/libcodex-" + name + "-probe.so", context.getCacheDir().getAbsolutePath());
                process = diagnostic
                    .redirectErrorStream(true).redirectOutput(output).start();
                if (!process.waitFor(25, TimeUnit.SECONDS)) {
                    process.destroyForcibly();
                    throw new java.io.IOException("Diagnostic timeout");
                }
                Log.i("Codex-Probe", name + " experiment exit=" + process.exitValue());
            } catch (Exception exception) {
                Log.e("Codex-Probe", "Landlock experiment failed", exception);
            } finally {
                if (process != null && process.isAlive()) process.destroyForcibly();
                pending.finish();
            }
        }, "Codex-kernel-probe").start();
    }
}
