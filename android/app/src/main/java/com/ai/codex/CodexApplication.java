package com.ai.codex;

import android.app.Application;
import android.util.Log;

/**
 * Restores this process's own dumpable flag before any executor admission runs.
 *
 * Android creates one Application instance in every process this application
 * starts, so registering this class covers the main process and :runtime at the
 * earliest point where application code runs. Both need it: the main process is
 * the target whose /proc/&lt;pid&gt;/stat :runtime must read, and :runtime is the
 * one doing the reading. See SiblingProcessVisibility for why the flag matters.
 *
 * Failure is logged, never fatal: the executor then reports its own admission
 * error instead of the application dying at start-up.
 */
public final class CodexApplication extends Application {
    private static final String TAG = "Codex";

    @Override public void onCreate() {
        super.onCreate();
        try {
            if (!com.ai.codex.shizukuexec.SiblingProcessVisibility.restore(this)) {
                Log.w(TAG, "Sibling process visibility was not restored in "
                        + getApplicationInfo().processName);
            }
        } catch (Throwable error) {
            /* Never abort start-up for a hardening downgrade. */
            Log.e(TAG, "Sibling process visibility restoration failed", error);
        }
    }
}
