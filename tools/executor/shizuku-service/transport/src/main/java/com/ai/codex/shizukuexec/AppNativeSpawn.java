package com.ai.codex.shizukuexec;

/** A distinct JNI entry for the installed application's Zygote lineage. */
final class AppNativeSpawn {
    private AppNativeSpawn() {}
    static synchronized void load(String path) { System.load(path); }
    static native int launch(String executable, String[] argv, int applicationUid, String canonicalData,
            int input, int output, int report, int control);
    static native int waitChild(int pid);
    /** Restores this process's dumpable flag; returns what the kernel reports. */
    static native int makeSiblingVisible();
}
