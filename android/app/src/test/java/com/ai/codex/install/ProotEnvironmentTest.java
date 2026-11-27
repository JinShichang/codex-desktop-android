package com.ai.codex.install;

import java.io.IOException;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import org.junit.*;
import static org.junit.Assert.*;

public class ProotEnvironmentTest {
    private Path files, executable, root;
    private ProcessBuilder target;
    private final List<ProcessBuilder> calls = new ArrayList<>();

    @Before public void prepare() throws Exception {
        files = Files.createTempDirectory("codex-proot-test-");
        executable = files.resolve("libproot.so"); Files.writeString(executable, "fixture");
        root = Files.createDirectory(files.resolve("root"));
        target = new ProcessBuilder(executable.toString(), "--kill-on-exit", "-r", root.toString(), "-w", "/",
            "/usr/bin/env", "-i", "SECRET=do-not-copy", "/user-task", "do-not-execute");
        target.environment().put(ProotEnvironment.NO_SECCOMP, "1");
    }
    @After public void cleanup() throws Exception {
        Thread.interrupted();
        try (java.util.stream.Stream<Path> paths = Files.walk(files)) {
            for (Path path : (Iterable<Path>) paths.sorted(Comparator.reverseOrder())::iterator) Files.delete(path);
        }
    }
    private ProotEnvironment.Selection select(String platform, ProotEnvironment.Probe... results) throws Exception {
        return ProotEnvironment.prepare(target, files, platform, process -> { calls.add(process); return results[calls.size()-1]; });
    }
    private static ProotEnvironment.Probe pass(boolean enabled) { return new ProotEnvironment.Probe(true, enabled); }
    private static ProotEnvironment.Probe rejected() { return new ProotEnvironment.Probe(false, false); }

    @Test public void supportedKernelRetainsAccelerationWithoutRunningUserCommand() throws Exception {
        assertTrue(select("rom-one", pass(true)).accelerated);
        assertFalse(target.environment().containsKey(ProotEnvironment.NO_SECCOMP));
        ProcessBuilder probe = calls.get(0);
        assertFalse(probe.environment().containsKey(ProotEnvironment.NO_SECCOMP));
        for (String value : List.of("SECRET=do-not-copy", "/user-task", "do-not-execute")) assertFalse(probe.command().contains(value));
        assertTrue(probe.command().contains("--kill-on-exit"));
        assertEquals("1", probe.command().get(2));
    }
    @Test public void nestedExecFailureUsesVerifiedCompatibleMode() throws Exception {
        ProotEnvironment.Selection selected = select("rom-one", rejected(), pass(false));
        assertFalse(selected.accelerated); assertEquals("acceleration-failed", selected.reason);
        assertEquals("1", target.environment().get(ProotEnvironment.NO_SECCOMP));
        assertEquals("1", calls.get(1).environment().get(ProotEnvironment.NO_SECCOMP));
    }
    @Test public void missingAccelerationBannerCannotBeMistakenForSupport() throws Exception {
        ProotEnvironment.Selection selected = select("rom-one", pass(false), pass(false));
        assertFalse(selected.accelerated); assertEquals("acceleration-unavailable", selected.reason);
    }
    @Test public void failureInBothModesDoesNotCacheASystemDiagnosis() throws Exception {
        try { select("rom-one", rejected(), rejected()); fail("Expected probe failure"); }
        catch (IOException expected) { assertTrue(expected.getMessage().contains("均未通过")); }
        assertFalse(Files.exists(files.resolve(".proot-compat")));
        calls.clear(); assertTrue(select("rom-one", pass(true)).accelerated);
    }
    @Test public void cachedResultAvoidsRepeatingProbe() throws Exception {
        select("rom-one", rejected(), pass(false)); calls.clear();
        assertFalse(select("rom-one").accelerated); assertTrue(calls.isEmpty());
    }
    @Test public void systemNativeLibraryAndRootfsChangesInvalidateCache() throws Exception {
        select("rom-one", pass(true)); calls.clear();
        select("rom-two", pass(true)); assertEquals(1, calls.size()); calls.clear();
        Files.writeString(executable, "a changed native library fixture");
        select("rom-one", pass(true)); assertEquals(1, calls.size()); calls.clear();
        Path other = Files.createDirectory(files.resolve("new-root"));
        target.command().set(target.command().indexOf("-r") + 1, other.toString());
        select("rom-one", pass(true)); assertEquals(1, calls.size());
    }
    @Test public void incompleteCacheIsProbedAgain() throws Exception {
        select("rom-one", pass(true));
        try (java.util.stream.Stream<Path> paths = Files.list(files.resolve(".proot-compat"))) {
            Files.writeString(paths.findFirst().orElseThrow(), "partial record");
        }
        calls.clear(); assertTrue(select("rom-one", pass(true)).accelerated); assertEquals(1, calls.size());
    }
    @Test public void symlinkedCacheAndUnrelatedCommandsAreRejected() throws Exception {
        Files.createSymbolicLink(files.resolve(".proot-compat"), root);
        try { select("rom-one", pass(true)); fail("Expected symlink rejection"); }
        catch (IOException expected) { assertTrue(expected.getMessage().contains("cache directory")); }
        Files.delete(files.resolve(".proot-compat"));
        target.command().set(0, "/unrelated/program");
        try { select("rom-one", pass(true)); fail("Expected unrelated command rejection"); }
        catch (IOException expected) { }
        assertTrue(calls.isEmpty());
    }
    @Test public void cancellationDoesNotBecomeCompatibilityFailure() throws Exception {
        Thread.currentThread().interrupt();
        try { select("rom-one", rejected(), pass(false)); fail("Expected interruption"); }
        catch (InterruptedException expected) { }
        assertTrue(calls.isEmpty());
    }
    @Test public void realHostSubprocessChecksMarkerAndAccelerationSeparately() throws Exception {
        ProotEnvironment.Probe passed = ProotEnvironment.run(new ProcessBuilder("/bin/sh", "-c",
            "printf '" + ProotEnvironment.ACCELERATION + "\\n" + ProotEnvironment.MARKER + "'"), 2000);
        assertTrue(passed.passed); assertTrue(passed.accelerated);
        assertFalse(ProotEnvironment.run(new ProcessBuilder("/bin/sh", "-c", "printf " + ProotEnvironment.MARKER + "; exit 17"), 2000).passed);
        assertFalse(ProotEnvironment.run(new ProcessBuilder("/bin/sh", "-c", "printf '" + ProotEnvironment.ACCELERATION + "'"), 2000).passed);
    }
    @Test public void hangingAndFloodingSubprocessesAreBounded() throws Exception {
        long start = System.nanoTime();
        assertFalse(ProotEnvironment.run(new ProcessBuilder("/usr/bin/python3", "-c", "import time; time.sleep(30)"), 100).passed);
        assertTrue(System.nanoTime()-start < TimeUnit.SECONDS.toNanos(3));
        assertFalse(ProotEnvironment.run(new ProcessBuilder("/usr/bin/python3", "-c", "print('x'*20000)"), 2000).passed);
    }
    @Test public void nestedShellProbeHasNoExternalTaskOrWriteSideEffect() throws Exception {
        ProotEnvironment.Probe result = ProotEnvironment.run(new ProcessBuilder("/usr/bin/env", "-i", "PATH=/usr/bin:/bin",
            "/bin/sh", "-c", ProotEnvironment.SCRIPT), 2000);
        assertTrue(result.passed); assertFalse(result.accelerated);
    }
}
