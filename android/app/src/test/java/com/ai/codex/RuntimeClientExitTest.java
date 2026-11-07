package com.ai.codex;

import java.nio.file.Files;
import java.nio.file.Path;
import org.junit.Rule;
import org.junit.Test;
import org.junit.rules.TemporaryFolder;
import static org.junit.Assert.*;

public final class RuntimeClientExitTest {
    @Rule public TemporaryFolder temporary = new TemporaryFolder();

    @Test public void onlyReadySuccessfulCurrentSessionIsNormal() throws Exception {
        Path receipt = temporary.getRoot().toPath().resolve("stopped");
        Files.writeString(receipt, "current-token\n");
        assertTrue(RuntimeClientExit.isNormal(0, true, receipt, "current-token"));
        assertFalse(RuntimeClientExit.isNormal(0, false, receipt, "current-token"));
        assertFalse(RuntimeClientExit.isNormal(139, true, receipt, "current-token"));
        assertFalse(RuntimeClientExit.isNormal(137, true, receipt, "current-token"));
        assertFalse(RuntimeClientExit.isNormal(0, true, receipt, "older-token"));
    }

    @Test public void missingOversizeOrSymlinkReceiptCannotDisableRecovery() throws Exception {
        Path root = temporary.getRoot().toPath();
        Path receipt = root.resolve("missing");
        assertFalse(RuntimeClientExit.isNormal(0, true, receipt, "token"));
        Files.writeString(receipt, "token" + " ".repeat(200));
        assertFalse(RuntimeClientExit.isNormal(0, true, receipt, "token"));
        Path target = root.resolve("target");
        Files.writeString(target, "token\n");
        Files.delete(receipt);
        Files.createSymbolicLink(receipt, target);
        assertFalse(RuntimeClientExit.isNormal(0, true, receipt, "token"));
    }
}
