package com.ai.codex.install;

import java.io.IOException;

/** Existing runtime needs APK-owned payload bytes before it can start. */
public final class PayloadRequiredException extends IOException {
    public PayloadRequiredException(String message) { super(message); }
    public PayloadRequiredException(String message, Throwable cause) { super(message, cause); }
}
