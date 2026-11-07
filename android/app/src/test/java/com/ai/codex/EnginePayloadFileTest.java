package com.ai.codex;

import java.io.ByteArrayInputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.MessageDigest;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public final class EnginePayloadFileTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();
    private byte[] elf() {
        byte[] data = new byte[65537];
        data[0] = 0x7f; data[1] = 'E'; data[2] = 'L'; data[3] = 'F';
        data[4] = 2; data[5] = 1; data[18] = (byte)183;
        return data;
    }
    private String digest(byte[] data) throws Exception {
        return EnginePayloadFile.hex(MessageDigest.getInstance("SHA-256").digest(data));
    }
    @Test public void stagesArm64PayloadUsingSmallReads() throws Exception {
        byte[] data = elf();
        Path staged = temporary.newFile().toPath();
        InputStream partial = new ByteArrayInputStream(data) {
            @Override public synchronized int read(byte[] bytes, int offset, int length) {
                return super.read(bytes, offset, Math.min(length, 7));
            }
        };
        EnginePayloadFile.stage(partial, staged, data.length, digest(data));
        assertArrayEquals(data, Files.readAllBytes(staged));
    }
    @Test public void rejectsTruncatedOversizedAndWrongDigestWithoutLeavingPartialFile() throws Exception {
        byte[] data = elf();
        for (int change : new int[]{-1, 0, 1}) {
            Path staged = temporary.newFile().toPath();
            String expected = change == 0 ? "0".repeat(64) : digest(data);
            assertThrows(IOException.class, () -> EnginePayloadFile.stage(new ByteArrayInputStream(data), staged, data.length + change, expected));
            assertFalse(Files.exists(staged));
        }
    }
    @Test public void rejectsWrongArchitectureAndInterruptedInput() throws Exception {
        byte[] data = elf(); data[18] = 62;
        Path staged = temporary.newFile().toPath();
        assertThrows(IOException.class, () -> EnginePayloadFile.stage(new ByteArrayInputStream(data), staged, data.length, digest(data)));
        assertFalse(Files.exists(staged));
        Path broken = temporary.newFile().toPath();
        assertThrows(IOException.class, () -> EnginePayloadFile.stage(new InputStream() {
            @Override public int read() throws IOException { throw new IOException("interrupted payload"); }
        }, broken, data.length, digest(data)));
        assertFalse(Files.exists(broken));
    }
}
