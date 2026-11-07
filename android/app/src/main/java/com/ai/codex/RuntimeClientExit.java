package com.ai.codex;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;

/** A zero exit is intentional only after the actual client reached its window. */
public final class RuntimeClientExit {
    private RuntimeClientExit() { }

    public static boolean isNormal(int exit, boolean ready, Path receipt, String token) {
        if (exit != 0 || !ready || token == null || token.isEmpty()) return false;
        try {
            return Files.isRegularFile(receipt, LinkOption.NOFOLLOW_LINKS)
                    && Files.size(receipt) <= 128 && token.equals(Files.readString(receipt).trim());
        } catch (IOException error) { return false; }
    }
}
