package com.ai.codex;

import android.content.Context;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;

/**
 * Launch guest commands with real chroot(2) instead of PRoot.
 *
 * <p>App processes inherit the zygote seccomp filter, which breaks PRoot's
 * {@code SECCOMP_RET_TRACE} acceleration on the second guest {@code execve}
 * ({@code proot info: vpid 1: terminated with signal 11}). Falling back to
 * {@code PROOT_NO_SECCOMP} stops the crash, but then {@code gnome-keyring-daemon}
 * cannot establish its private session bus, so keyring preparation never finishes.
 *
 * <p>Real chroot has neither problem: it needs no ptrace and the guest gets a
 * genuine identity, D-Bus socket and {@code /proc}. On a rooted device with the
 * packaged Debian tree this is both correct and dramatically faster.
 *
 * <p>Mounts are made inside a private mount namespace by the packaged launcher
 * script, so the host mount table is never modified. Root is required and is
 * obtained through the same {@code su} channel the project already uses; when it
 * is unavailable the caller must fall back to PRoot.
 */
public final class CodexChrootChannel {
    /** Asset path of the launcher script shipped inside the APK. */
    private static final String LAUNCHER_ASSET = "chroot/codex-chroot.sh";
    /** Where the launcher is materialised inside the app's private files. */
    private static final String LAUNCHER_NAME = "codex-chroot.sh";

    private CodexChrootChannel() {}

    /**
     * True when chroot can be used: the user enabled the root channel, a
     * {@code su} exists and the guest tree is prepared.
     *
     * <p>The root capability is an explicit user choice in this app, so it is
     * honoured here too. Chroot must never become a way to obtain root behind
     * that switch.
     */
    public static boolean isAvailable(Context context) {
        try {
            if (!CodexDeviceFeatures.enabled(context, "root")) return false;
            if (suPath() == null) return false;
            return new java.io.File(context.getFilesDir(), "debian/usr/bin/env").isFile();
        } catch (Exception error) {
            return false;
        }
    }

    private static String suPath() {
        for (String candidate : new String[] {"/system/bin/su", "/system/xbin/su", "/sbin/su",
                "/debug_ramdisk/su"}) {
            if (new java.io.File(candidate).canExecute()) return candidate;
        }
        return null;
    }

    /**
     * Materialise the packaged launcher and return its absolute path.
     *
     * <p>The script is re-written from the APK on every call so an APK update
     * always deploys its own launcher; a stale copy can never drive a newer
     * guest tree.
     */
    static java.io.File installLauncher(Context context) throws Exception {
        java.io.File target = new java.io.File(context.getFilesDir(), LAUNCHER_NAME);
        try (java.io.InputStream input = context.getAssets().open(LAUNCHER_ASSET);
             java.io.FileOutputStream output = new java.io.FileOutputStream(target)) {
            byte[] buffer = new byte[8192];
            int count;
            while ((count = input.read(buffer)) != -1) output.write(buffer, 0, count);
        }
        if (!target.setExecutable(true, true)) {
            throw new IllegalStateException("cannot mark the chroot launcher executable");
        }
        return target;
    }

    /**
     * Run one guest command and return its standard output.
     *
     * @param root      guest root, normally {@code files/debian}
     * @param uid       guest uid to become; must be the app's own uid
     * @param home      guest HOME
     * @param timeoutMs wall-clock bound
     * @param guestEnv  extra {@code NAME=value} entries for the guest environment
     */
    public static String run(Context context, java.io.File root, int uid, String home,
            long timeoutMs, List<String> guestEnv, List<String> command) throws Exception {
        return run(context, root, uid, home, timeoutMs, guestEnv, List.of(), command);
    }

    /**
     * Run one guest command with extra host paths bound at the same absolute
     * path inside the guest.
     *
     * <p>The keyring vault lives in {@code no_backup/}, outside the guest root.
     * The guest initializer opens it by its absolute Android path, so that path
     * has to exist inside the chroot with identical content.
     *
     * @param extraBinds host paths to bind; only existing absolute paths are used
     */
    public static String run(Context context, java.io.File root, int uid, String home,
            long timeoutMs, List<String> guestEnv, List<java.io.File> extraBinds,
            List<String> command) throws Exception {
        if (!command.isEmpty()) {
            String head = command.get(0);
            if (head.contains("/") && !head.startsWith("/"))
                throw new IllegalArgumentException("Guest command must be absolute: " + head);
        }
        String guard = "codex-chroot-guard";
        if (command.contains(guard))
            throw new IllegalArgumentException("Guest command collides with the launcher guard");
        java.io.File launcher = installLauncher(context);
        List<String> argv = new ArrayList<>();
        argv.add("/system/bin/sh");
        argv.add(launcher.getAbsolutePath());
        argv.add(root.getAbsolutePath());
        argv.add(Integer.toString(uid));
        argv.add(home);
        argv.add(Long.toString(Math.max(1, (timeoutMs + 999) / 1000)));
        argv.addAll(command);

        String su = suPath();
        if (su == null) throw new IllegalStateException("no su available for chroot");
        // su carries the launcher path; the launcher itself re-validates the root.
        List<String> privileged = new ArrayList<>(List.of(su, "-c", shellJoin(argv)));
        ProcessBuilder actual = new ProcessBuilder(privileged).redirectErrorStream(true);
        actual.environment().clear();
        actual.environment().put("PATH", "/system/bin");
        applyGuestEnvironment(actual, guestEnv, extraBinds);
        Process process = actual.start();
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        Thread reader = new Thread(() -> {
            try (java.io.InputStream input = process.getInputStream()) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (bytes.size() + count > 1 << 20) {
                        process.destroyForcibly();
                        break;
                    }
                    bytes.write(buffer, 0, count);
                }
            } catch (Exception ignored) {
            }
        }, "Codex-chroot-output");
        reader.setDaemon(true);
        reader.start();
        try {
            process.getOutputStream().close();
            if (!process.waitFor(timeoutMs + 15_000, TimeUnit.MILLISECONDS)) {
                process.destroyForcibly();
                throw new java.io.IOException("chroot command deadline expired");
            }
            reader.join(2_000);
            String text = bytes.toString(StandardCharsets.UTF_8);
            if (process.exitValue() != 0)
                throw new java.io.IOException("chroot command failed (exit "
                        + process.exitValue() + "): " + text);
            return text;
        } finally {
            if (process.isAlive()) process.destroyForcibly();
        }
    }

    /**
     * Run one guest command feeding a credential over an anonymous pipe.
     *
     * <p>Same launch path as {@link #run}, except the credential bytes become
     * the guest's standard input. The bytes are never placed in argv or in the
     * environment, so they cannot appear in the process list or a crash report;
     * the array is zeroed after the write.
     */
    public static String runGuest(Context context, java.io.File root, int uid, String home,
            long timeoutMs, List<String> guestEnv, List<java.io.File> extraBinds,
            List<String> command, byte[] credential) throws Exception {
        if (credential == null || credential.length == 0 || credential.length > 8192)
            throw new IllegalArgumentException("Invalid credential length");
        java.io.File launcher = installLauncher(context);
        List<String> argv = new ArrayList<>();
        argv.add("/system/bin/sh");
        argv.add(launcher.getAbsolutePath());
        argv.add(root.getAbsolutePath());
        argv.add(Integer.toString(uid));
        argv.add(home);
        argv.add(Long.toString(Math.max(1, (timeoutMs + 999) / 1000)));
        argv.addAll(command);

        String su = suPath();
        if (su == null) throw new IllegalStateException("no su available for chroot");
        ProcessBuilder actual = new ProcessBuilder(su, "-c", shellJoin(argv)).redirectErrorStream(true);
        actual.environment().clear();
        actual.environment().put("PATH", "/system/bin");
        applyGuestEnvironment(actual, guestEnv, extraBinds);
        Process process = actual.start();
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        Thread reader = new Thread(() -> {
            try (java.io.InputStream input = process.getInputStream()) {
                byte[] buffer = new byte[8192];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (bytes.size() + count > 1 << 20) {
                        process.destroyForcibly();
                        break;
                    }
                    bytes.write(buffer, 0, count);
                }
            } catch (Exception ignored) {
            }
        }, "Codex-chroot-output");
        reader.setDaemon(true);
        reader.start();
        try {
            try (java.io.OutputStream stdin = process.getOutputStream()) {
                stdin.write(credential);
            } catch (java.io.IOException ignored) {
                // A guest that exits before reading is reported by its status.
            }
            java.util.Arrays.fill(credential, (byte) 0);
            if (!process.waitFor(timeoutMs + 15_000, TimeUnit.MILLISECONDS)) {
                process.destroyForcibly();
                throw new java.io.IOException("chroot command deadline expired");
            }
            reader.join(2_000);
            String text = bytes.toString(StandardCharsets.UTF_8);
            if (process.exitValue() != 0)
                throw new java.io.IOException("chroot command failed (exit "
                        + process.exitValue() + "): " + text);
            return text;
        } finally {
            if (process.isAlive()) process.destroyForcibly();
        }
    }

    /** Validate and forward the guest environment and bind list. */
    private static void applyGuestEnvironment(ProcessBuilder actual, List<String> guestEnv,
            List<java.io.File> extraBinds) {
        if (!guestEnv.isEmpty()) {
            for (String entry : guestEnv) {
                if (!entry.matches("[A-Z_][A-Z0-9_]*=[^\\n\\r\\0]*"))
                    throw new IllegalArgumentException("Invalid guest environment entry: " + entry);
            }
            actual.environment().put("CODEX_GUEST_ENV", String.join(" ", guestEnv));
        }
        if (!extraBinds.isEmpty()) {
            List<String> entries = new ArrayList<>();
            for (java.io.File bind : extraBinds) {
                String path = bind.getAbsolutePath();
                if (!bind.isAbsolute() || path.contains(";") || path.contains(":")
                        || path.contains("\\n") || path.contains("\\r"))
                    throw new IllegalArgumentException("Invalid bind path: " + path);
                if (bind.exists()) entries.add(path);
            }
            if (!entries.isEmpty())
                actual.environment().put("CODEX_EXTRA_BINDS", String.join(";", entries));
        }
    }

    /** Single-quote every argument so the privileged shell sees it verbatim. */
    private static String shellJoin(List<String> argv) {
        StringBuilder shell = new StringBuilder();
        for (String argument : argv) {
            if (shell.length() > 0) shell.append(' ');
            shell.append('\'').append(argument.replace("'", "'\\''")).append('\'');
        }
        return shell.toString();
    }
}
