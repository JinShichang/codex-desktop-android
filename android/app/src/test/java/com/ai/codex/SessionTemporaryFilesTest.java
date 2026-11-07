package com.ai.codex;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public final class SessionTemporaryFilesTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    @Test public void removesSessionFilesWhilePreservingXServerAndUserData() throws Exception {
        Path root = temporary.getRoot().toPath();
        Path cache = Files.createDirectory(root.resolve("cache"));
        Path x11 = Files.createDirectory(cache.resolve("x11"));
        Path socket = Files.createDirectories(x11.resolve(".X11-unix")).resolve("X2");
        Files.writeString(socket, "live X server");
        Files.writeString(x11.resolve(".X2-lock"), "pid");
        Files.writeString(x11.resolve(".org.chromium.Chromium.old"), "old cache");
        Files.writeString(Files.createDirectories(x11.resolve("proot-old/nested")).resolve("file"), "temporary");
        Path shm = Files.createDirectory(cache.resolve("shm"));
        Files.writeString(shm.resolve("shared-region"), "temporary");
        Path project = Files.createDirectories(root.resolve("files/projects" )).resolve("important.txt");
        Files.writeString(project, "user work");
        Files.createSymbolicLink(x11.resolve("external-project"), project.getParent());
        Files.createSymbolicLink(x11.resolve("external-file"), project);
        Path otherCache = Files.createDirectories(cache.resolve("unrelated")).resolve("keep");
        Files.writeString(otherCache, "unrelated cache");

        SessionTemporaryFiles.Result result = SessionTemporaryFiles.clearAfterExit(cache);
        assertEquals(0, result.failures());
        assertTrue(result.entries() >= 7);
        assertTrue(Files.exists(socket));
        assertTrue(Files.exists(x11.resolve(".X2-lock")));
        assertEquals("user work", Files.readString(project));
        assertTrue(Files.exists(otherCache));
        assertFalse(Files.exists(x11.resolve(".org.chromium.Chromium.old")));
        assertFalse(Files.exists(x11.resolve("proot-old")));
        try (var children = Files.list(shm)) { assertEquals(0L, children.count()); }
        assertEquals(0, SessionTemporaryFiles.clearAfterExit(cache).entries());
    }

    @Test public void refusesSymlinkedTemporaryRoot() throws Exception {
        Path root = temporary.getRoot().toPath();
        Path cache = Files.createDirectory(root.resolve("cache"));
        Path outside = Files.createDirectory(root.resolve("outside"));
        Path important = outside.resolve("important");
        Files.writeString(important, "keep");
        Files.createSymbolicLink(cache.resolve("x11"), outside);
        assertThrows(IOException.class, () -> SessionTemporaryFiles.clearAfterExit(cache));
        assertEquals("keep", Files.readString(important));
    }
}
