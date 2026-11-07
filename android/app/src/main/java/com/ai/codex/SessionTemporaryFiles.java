package com.ai.codex;

import java.io.IOException;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.SimpleFileVisitor;
import java.nio.file.FileVisitResult;
import java.nio.file.attribute.BasicFileAttributes;

/** Call only after the native owner, Linux launcher and remaining helpers end. */
public final class SessionTemporaryFiles {
    private SessionTemporaryFiles() { }

    public record Result(long entries, long bytes, int failures) { }

    public static Result clearAfterExit(Path cacheDirectory) throws IOException {
        if (!Files.isDirectory(cacheDirectory, LinkOption.NOFOLLOW_LINKS))
            throw new IOException("Application cache is not a real directory");
        Path cache = cacheDirectory.toRealPath();
        long[] removed = new long[3];
        for (String name : new String[]{"x11", "shm"}) {
            Path directory = cache.resolve(name);
            if (!Files.exists(directory, LinkOption.NOFOLLOW_LINKS)) continue;
            if (!Files.isDirectory(directory, LinkOption.NOFOLLOW_LINKS))
                throw new IOException("Session temporary root is not a real directory: " + name);
            try (DirectoryStream<Path> children = Files.newDirectoryStream(directory)) {
                for (Path child : children) {
                    String leaf = child.getFileName().toString();
                    // Xlorie belongs to the Java VM and stays alive during a
                    // desktop restart. Never unlink its live socket or lock.
                    if (name.equals("x11") && (leaf.equals(".X11-unix") || leaf.matches("\\.X[0-9]+-lock"))) continue;
                    Files.walkFileTree(child, new SimpleFileVisitor<Path>() {
                        private void remove(Path path, long bytes) {
                            try {
                                Files.delete(path);
                                removed[0]++;
                                removed[1] += bytes;
                            } catch (IOException error) { removed[2]++; }
                        }
                        @Override public FileVisitResult visitFile(Path path, BasicFileAttributes attrs) {
                            // walkFileTree does not follow symlinks. Remove the
                            // link itself, never a target outside this cache.
                            remove(path, attrs.isRegularFile() ? attrs.size() : 0);
                            return FileVisitResult.CONTINUE;
                        }
                        @Override public FileVisitResult visitFileFailed(Path path, IOException error) {
                            removed[2]++;
                            return FileVisitResult.CONTINUE;
                        }
                        @Override public FileVisitResult postVisitDirectory(Path path, IOException error) {
                            if (error != null) removed[2]++;
                            remove(path, 0);
                            return FileVisitResult.CONTINUE;
                        }
                    });
                }
            }
        }
        return new Result(removed[0], removed[1], (int)removed[2]);
    }
}
