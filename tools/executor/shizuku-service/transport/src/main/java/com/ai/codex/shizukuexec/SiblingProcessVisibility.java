package com.ai.codex.shizukuexec;

import android.content.Context;
import android.util.Log;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;

/**
 * Restore the application processes' own dumpable flag.
 *
 * Android mounts /proc with hidepid=invisible on some devices. On that mount the
 * kernel hides a sibling process unless ptrace_may_access() succeeds, which
 * requires the *target* to be dumpable. Zygote clears that flag for ordinary
 * application processes, so this application's two processes cannot read each
 * other's /proc/&lt;pid&gt;/stat even though they share a uid, gid and SELinux
 * domain. AndroidProcessPopulation.capture() then fails with
 * "java.nio.file.NoSuchFileException: /proc/&lt;pid&gt;/stat" and every native
 * launch ends as "qualified_native_deployment_unavailable".
 *
 * Because dumpable is a property of the target, each process must re-enable it
 * for itself; this class is called from both the main process and :runtime.
 *
 * Deliberate, documented weakening: a same-UID process can now ptrace this one
 * and the kernel may write a core image. It grants no privilege: transport
 * admission still demands the exact application uid/gid triple, untouched
 * no-new-privs, empty capability sets, and every captured identity is still read
 * from the kernel. It must not be presented as equivalent to the upstream
 * sandbox. See COM_AI_CODEX_ALLOW_SIBLING_PROC_POPULATION in app-spawn.c.
 */
public final class SiblingProcessVisibility {
    private static final String TAG = "Codex-executor";
    private static final String LIBRARY = "libcodex_app_transport.so";
    private static Boolean restored;

    private SiblingProcessVisibility() {}

    /** Idempotent; returns whether the kernel reports this process dumpable. */
    public static synchronized boolean restore(Context context) {
        if (restored != null) return restored;
        try {
            /* Only the installed, digest-attested library is ever loaded. The
             * application origin is required here: a Shizuku deployment never
             * captures the Android process population, so it needs no visibility. */
            JSONObject config;
            try (java.io.InputStream input = context.getAssets().open(Deployment.ASSET)) {
                config = new JSONObject(new String(Deployment.readBounded(input, 65536),
                        StandardCharsets.UTF_8));
            }
            if (!Deployment.applicationOrigin(config)) {
                restored = Boolean.FALSE;
                return false;
            }
            String expected = config.getJSONObject("nativeLibraries").getString(LIBRARY);
            File directory = new File(context.getApplicationInfo().nativeLibraryDir).getCanonicalFile();
            File library = InstalledLibrary.verify(directory, LIBRARY, expected);
            AppNativeSpawn.load(library.getPath());
            int value = AppNativeSpawn.makeSiblingVisible();
            restored = value == 1;
            if (restored) Log.i(TAG, "Application process is dumpable again; siblings are visible");
            else Log.e(TAG, "Kernel kept dumpable=" + value + "; siblings stay hidden");
        } catch (Exception | LinkageError error) {
            Log.e(TAG, "Cannot restore sibling process visibility", error);
            return false;
        }
        return restored;
    }

    /** Never asks for permission; only reports a value already obtained. */
    public static synchronized Boolean observed() { return restored; }
}
