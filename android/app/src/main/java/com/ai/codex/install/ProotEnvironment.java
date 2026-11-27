package com.ai.codex.install;

import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.nio.file.attribute.PosixFilePermissions;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.*;
import java.util.concurrent.*;

/** Tests the actual PRoot exec path before running any installer or user task.
 * Android's inherited seccomp policy is never disabled. The managed GNU
 * executor has its own translation-order requirements and keeps its fixed mode.
 */
public final class ProotEnvironment {
    public static final String NO_SECCOMP = "PROOT_NO_SECCOMP";
    static final String MARKER = "CODEX_PROOT_NESTED_EXEC_OK";
    static final String ACCELERATION = "ptrace acceleration (seccomp mode 2";
    static final String SCRIPT = "/bin/sh -c \"exec /usr/bin/env -i PATH=/usr/bin:/bin /bin/sh -c 'printf " + MARKER + "'\"; exit $?";
    private static final String VERSION = "codex.proot.seccomp.v1";
    private static final int OUTPUT_LIMIT = 16384;
    private ProotEnvironment() {}

    public static final class Selection {
        public final boolean accelerated;
        public final String reason;
        Selection(boolean accelerated, String reason) { this.accelerated = accelerated; this.reason = reason; }
        @Override public String toString() { return (accelerated ? "accelerated" : "compatible") + ": " + reason; }
    }
    interface Runner { Probe run(ProcessBuilder process) throws IOException, InterruptedException; }
    static final class Probe {
        final boolean passed, accelerated;
        Probe(boolean passed, boolean accelerated) { this.passed = passed; this.accelerated = accelerated; }
    }

    public static Selection prepare(ProcessBuilder target, Path filesDirectory, String platform) throws IOException {
        try { return prepare(target, filesDirectory, platform, process -> run(process, 5000)); }
        catch (InterruptedException error) {
            Thread.currentThread().interrupt();
            throw new InterruptedIOException("PRoot compatibility detection interrupted");
        }
    }

    // Serialize probes within the Android process. Atomic records are safe to
    // read after a crash; Java and native-tool callers use separate profiles.
    static synchronized Selection prepare(ProcessBuilder target, Path filesDirectory, String platform, Runner runner)
            throws IOException, InterruptedException {
        if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
        List<String> command = target.command();
        int guest = command.indexOf("/usr/bin/env"), rootIndex = command.indexOf("-r");
        if (guest < 1 || rootIndex < 1 || rootIndex + 1 >= guest
                || !command.get(0).endsWith("/libproot.so") || !command.contains("--kill-on-exit"))
            throw new IOException("Expected an owned PRoot launch with an explicit guest environment");
        Path executable = Path.of(command.get(0)).toRealPath();
        Path root = Path.of(command.get(rootIndex + 1)).toRealPath();
        String identity = VERSION + "\n" + platform + "\n" + System.getProperty("os.version", "") + "\n"
            + executable + "\n" + Files.size(executable) + "\n" + Files.getLastModifiedTime(executable).toMillis() + "\n" + root;
        Path directory = filesDirectory.resolve(".proot-compat");
        if (Files.exists(directory, LinkOption.NOFOLLOW_LINKS) && !Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Invalid PRoot compatibility cache directory");
        Path record = directory.resolve("android-" + digest(identity) + ".txt");
        Selection selection = read(record);
        if (selection == null) {
            Probe accelerated = runner.run(probe(target, guest, true));
            if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
            if (accelerated.passed && accelerated.accelerated) selection = new Selection(true, "nested-exec-ok");
            else {
                Probe compatible = runner.run(probe(target, guest, false));
                if (Thread.currentThread().isInterrupted()) throw new InterruptedException();
                if (!compatible.passed)
                    throw new IOException("PRoot 嵌套启动检测失败：加速与兼容模式均未通过，请导出日志。没有执行安装或用户任务。");
                selection = new Selection(false, accelerated.passed ? "acceleration-unavailable" : "acceleration-failed");
            }
            // A cache failure must not prevent a verified runtime from starting.
            try { write(directory, record, selection); } catch (IOException ignored) { }
        }
        if (selection.accelerated) target.environment().remove(NO_SECCOMP);
        else target.environment().put(NO_SECCOMP, "1");
        return selection;
    }

    private static ProcessBuilder probe(ProcessBuilder target, int guest, boolean accelerated) {
        List<String> args = new ArrayList<>(target.command().subList(0, guest));
        args.add(1, "-v"); args.add(2, "1");
        args.addAll(List.of("/usr/bin/env", "-i", "PATH=/usr/bin:/bin", "LC_ALL=C", "/bin/sh", "-c", SCRIPT));
        ProcessBuilder process = new ProcessBuilder(args).directory(target.directory()).redirectErrorStream(true);
        process.environment().clear(); process.environment().putAll(target.environment());
        if (accelerated) process.environment().remove(NO_SECCOMP);
        else process.environment().put(NO_SECCOMP, "1");
        return process;
    }

    static Probe run(ProcessBuilder builder, long timeoutMillis) throws IOException, InterruptedException {
        Process child;
        try { child = builder.start(); } catch (IOException error) { return new Probe(false, false); }
        ExecutorService reader = Executors.newSingleThreadExecutor(task -> {
            Thread thread = new Thread(task, "Codex-proot-compatibility"); thread.setDaemon(true); return thread;
        });
        Future<byte[]> output = reader.submit(() -> {
            try (InputStream input = child.getInputStream(); ByteArrayOutputStream bytes = new ByteArrayOutputStream()) {
                byte[] buffer = new byte[1024]; int count;
                while ((count = input.read(buffer)) != -1) {
                    if (bytes.size() + count > OUTPUT_LIMIT) { child.destroy(); throw new IOException("PRoot probe output exceeded bound"); }
                    bytes.write(buffer, 0, count);
                }
                return bytes.toByteArray();
            }
        });
        try {
            child.getOutputStream().close();
            if (!child.waitFor(timeoutMillis, TimeUnit.MILLISECONDS)) return new Probe(false, false);
            byte[] bytes;
            try { bytes = output.get(1, TimeUnit.SECONDS); }
            catch (ExecutionException | TimeoutException error) { return new Probe(false, false); }
            String text = new String(bytes, StandardCharsets.UTF_8);
            return new Probe(child.exitValue() == 0 && text.contains(MARKER), text.contains(ACCELERATION));
        } finally {
            // SIGTERM lets the packaged --kill-on-exit tracer reap its tracees.
            boolean interrupted = Thread.interrupted();
            try {
                if (child.isAlive()) { child.destroy(); if (!child.waitFor(500, TimeUnit.MILLISECONDS)) child.destroyForcibly(); }
                if (!child.waitFor(1000, TimeUnit.MILLISECONDS)) throw new IOException("PRoot probe cleanup timed out");
            } catch (InterruptedException stop) { interrupted = true; child.destroyForcibly(); }
            finally {
                output.cancel(true); reader.shutdownNow();
                try { child.getInputStream().close(); } catch (IOException ignored) { }
                if (interrupted) Thread.currentThread().interrupt();
            }
        }
    }

    private static String digest(String value) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256").digest(value.getBytes(StandardCharsets.UTF_8));
            StringBuilder result = new StringBuilder(); for (byte part : bytes) result.append(String.format(Locale.ROOT, "%02x", part & 255));
            return result.toString();
        } catch (NoSuchAlgorithmException impossible) { throw new AssertionError(impossible); }
    }
    private static Selection read(Path path) {
        try {
            if (!Files.isRegularFile(path, LinkOption.NOFOLLOW_LINKS) || Files.size(path) > 256) return null;
            List<String> lines = Files.readAllLines(path, StandardCharsets.US_ASCII);
            if (lines.size() != 3 || !VERSION.equals(lines.get(0))) return null;
            if (lines.get(1).equals("accelerated") && lines.get(2).equals("nested-exec-ok")) return new Selection(true, lines.get(2));
            if (lines.get(1).equals("compatible") && Set.of("acceleration-unavailable", "acceleration-failed").contains(lines.get(2)))
                return new Selection(false, lines.get(2));
        } catch (IOException ignored) { }
        return null;
    }
    private static void write(Path directory, Path record, Selection selection) throws IOException {
        if (!Files.exists(directory, LinkOption.NOFOLLOW_LINKS))
            Files.createDirectory(directory, PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
        if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Invalid PRoot compatibility cache");
        Path temporary = Files.createTempFile(directory, ".probe-", ".tmp",
            PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rw-------")));
        try {
            Files.writeString(temporary, VERSION + "\n" + (selection.accelerated ? "accelerated" : "compatible") + "\n" + selection.reason + "\n",
                StandardCharsets.US_ASCII, StandardOpenOption.TRUNCATE_EXISTING);
            Files.move(temporary, record, StandardCopyOption.ATOMIC_MOVE, StandardCopyOption.REPLACE_EXISTING);
        } finally { Files.deleteIfExists(temporary); }
    }
}
