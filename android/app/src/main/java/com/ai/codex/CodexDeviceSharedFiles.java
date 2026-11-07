package com.ai.codex;

import android.os.ParcelFileDescriptor;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import java.io.File;
import java.io.FileDescriptor;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.UUID;

/** Opens device-command paths relative to already opened directories. */
final class CodexDeviceSharedFiles {
    private static final String ROOT = "/storage/emulated/0";

    private CodexDeviceSharedFiles() {}

    static ParcelFileDescriptor openInput(String path) throws Exception {
        String[] parts = DeviceFilePolicy.sharedComponents(path);
        if (parts.length == 0 || path.endsWith("/")) throw new DeviceCommandPolicy.Blocked("regular_file_required");
        try (ParcelFileDescriptor directory = openParent(parts)) {
            return open(child(directory, parts[parts.length - 1]), OsConstants.O_RDONLY | OsConstants.O_NONBLOCK);
        }
    }

    static ParcelFileDescriptor openApk(String path) throws Exception {
        DeviceFilePolicy.requireSharedApk(path);
        ParcelFileDescriptor source;
        try {
            source = openInput(path);
        } catch (ErrnoException error) {
            if (error.errno == OsConstants.ENOENT) throw new IllegalArgumentException("apk_not_found", error);
            if (error.errno == OsConstants.EACCES || error.errno == OsConstants.EPERM)
                throw new IllegalArgumentException("apk_read_denied", error);
            throw new IllegalArgumentException("apk_open_failed", error);
        }
        try {
            if (size(source) == 0) throw new DeviceCommandPolicy.Blocked("empty_apk");
            return source;
        } catch (Exception failure) {
            try { source.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    static long size(ParcelFileDescriptor source) throws ErrnoException {
        StructStat stat = Os.fstat(source.getFileDescriptor());
        if (!OsConstants.S_ISREG(stat.st_mode) || stat.st_size < 0)
            throw new DeviceCommandPolicy.Blocked("regular_file_required");
        return stat.st_size;
    }

    static File descriptorPath(ParcelFileDescriptor file) {
        return new File("/proc/self/fd/" + file.getFd());
    }

    static long copy(String sourcePath, String destination) throws Exception {
        String[] parts = DeviceFilePolicy.sharedComponents(destination);
        String sourceName = new File(sourcePath).getName();
        try (ParcelFileDescriptor source = openInput(sourcePath);
             ParcelFileDescriptor directory = openParent(parts)) {
            if (parts.length == 0) return copyTo(source, child(directory, sourceName));
            String target = child(directory, parts[parts.length - 1]);
            StructStat existing = statIfPresent(target);
            if (existing != null && OsConstants.S_ISDIR(existing.st_mode)) {
                try (ParcelFileDescriptor targetDirectory = openDirectory(target)) {
                    return copyTo(source, child(targetDirectory, sourceName));
                }
            }
            if (destination.endsWith("/")) throw new DeviceCommandPolicy.Blocked("directory_required");
            return copyTo(source, target);
        }
    }

    private static long copyTo(ParcelFileDescriptor source, String target) throws Exception {
        long remaining = size(source);
        long total = remaining;
        StructStat original = Os.fstat(source.getFileDescriptor());
        StructStat existing = statIfPresent(target);
        if (existing != null && (!OsConstants.S_ISREG(existing.st_mode)
                || original.st_dev == existing.st_dev && original.st_ino == existing.st_ino))
            throw new DeviceCommandPolicy.Blocked("invalid_copy_destination");

        String temporary = target.substring(0, target.lastIndexOf('/') + 1) + ".codex-copy-" + UUID.randomUUID();
        StructStat created = null;
        try {
            try (ParcelFileDescriptor output = open(temporary, OsConstants.O_WRONLY | OsConstants.O_CREAT | OsConstants.O_EXCL);
                 OutputStream sink = new ParcelFileDescriptor.AutoCloseOutputStream(output);
                 InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(source)) {
                created = Os.fstat(output.getFileDescriptor());
                byte[] buffer = new byte[65536];
                while (remaining > 0) {
                    int read = input.read(buffer, 0, (int) Math.min(remaining, buffer.length));
                    if (read < 0) throw new IOException("source_changed_during_copy");
                    sink.write(buffer, 0, read);
                    remaining -= read;
                }
            }
            Os.rename(temporary, target);
        } catch (Exception failure) {
            if (created != null) removePartial(temporary, created, failure);
            throw failure;
        }
        return total;
    }

    private static StructStat statIfPresent(String path) throws ErrnoException {
        try {
            return Os.lstat(path);
        } catch (ErrnoException missing) {
            if (missing.errno == OsConstants.ENOENT) return null;
            throw missing;
        }
    }

    private static void removePartial(String target, StructStat created, Exception failure) {
        try {
            StructStat current = Os.lstat(target);
            if (current.st_dev == created.st_dev && current.st_ino == created.st_ino) Os.remove(target);
        } catch (ErrnoException cleanup) {
            if (cleanup.errno != OsConstants.ENOENT) failure.addSuppressed(cleanup);
        }
    }

    private static ParcelFileDescriptor openParent(String[] parts) throws Exception {
        ParcelFileDescriptor directory = openDirectory(ROOT);
        try {
            for (int index = 0; index < parts.length - 1; index++) {
                try (ParcelFileDescriptor parent = directory) {
                    directory = openDirectory(child(parent, parts[index]));
                }
            }
            return directory;
        } catch (Exception failure) {
            try { directory.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    private static String child(ParcelFileDescriptor directory, String name) {
        return descriptorPath(directory).getPath() + "/" + name;
    }

    private static ParcelFileDescriptor openDirectory(String path) throws Exception {
        ParcelFileDescriptor directory = open(path, OsConstants.O_RDONLY | OsConstants.O_NONBLOCK);
        try {
            if (!OsConstants.S_ISDIR(Os.fstat(directory.getFileDescriptor()).st_mode))
                throw new DeviceCommandPolicy.Blocked("directory_required");
            return directory;
        } catch (Exception failure) {
            try { directory.close(); } catch (IOException cleanup) { failure.addSuppressed(cleanup); }
            throw failure;
        }
    }

    private static ParcelFileDescriptor open(String path, int flags) throws Exception {
        FileDescriptor file;
        try {
            file = Os.open(path, flags | OsConstants.O_CLOEXEC | OsConstants.O_NOFOLLOW, 0600);
        } catch (ErrnoException failure) {
            if (failure.errno == OsConstants.ELOOP || failure.errno == OsConstants.ENOTDIR)
                throw new DeviceCommandPolicy.Blocked("symlink_or_non_directory_path");
            throw failure;
        }
        try {
            return ParcelFileDescriptor.dup(file);
        } finally {
            Os.close(file);
        }
    }
}
