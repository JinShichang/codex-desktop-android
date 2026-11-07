package com.ai.codex;

import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;

/** Streams one signed APK payload into an unpublished file; never edits a live binary. */
public final class EnginePayloadFile {
    private EnginePayloadFile() { }

    public static void stage(InputStream input, Path target, long size, String expected) throws Exception {
        if (size < 20 || size > 536870912L || !expected.matches("[a-f0-9]{64}"))
            throw new IOException("Invalid GNU engine payload descriptor");
        MessageDigest digest = MessageDigest.getInstance("SHA-256");
        byte[] header = new byte[20];
        long written = 0;
        boolean complete = false;
        try {
            // The caller creates a fresh temporary file in the admitted directory.
            try (FileOutputStream output = new FileOutputStream(target.toFile())) {
                byte[] buffer = new byte[65536];
                int count;
                while ((count = input.read(buffer)) != -1) {
                    if (written + count > size) throw new IOException("GNU engine payload exceeds descriptor");
                    if (written < header.length)
                        System.arraycopy(buffer, 0, header, (int)written, Math.min(count, header.length - (int)written));
                    output.write(buffer, 0, count);
                    digest.update(buffer, 0, count);
                    written += count;
                }
                if (written != size || !hex(digest.digest()).equals(expected))
                    throw new IOException("GNU engine payload is incomplete or differs from APK descriptor");
                if (header[0] != 0x7f || header[1] != 'E' || header[2] != 'L' || header[3] != 'F'
                        || header[4] != 2 || header[5] != 1 || (header[18] & 255) != 183 || header[19] != 0)
                    throw new IOException("GNU engine payload is not ARM64 ELF");
                output.getFD().sync();
            }
            complete = true;
        } finally {
            if (!complete) Files.deleteIfExists(target);
        }
    }

    static String hex(byte[] bytes) {
        StringBuilder result = new StringBuilder(bytes.length * 2);
        for (byte value : bytes) {
            result.append(Character.forDigit((value & 255) >>> 4, 16));
            result.append(Character.forDigit(value & 15, 16));
        }
        return result.toString();
    }
}
