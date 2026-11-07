package com.ai.codex;
/** Every path component is opened relative to the preceding descriptor with O_NOFOLLOW. */
public final class CodexDeviceFileRead {
    static { System.loadLibrary("codex-device-files"); }
    private CodexDeviceFileRead() {}
    public static byte[] read(String path,int limit) throws java.io.IOException {
        return readUtf8(path.getBytes(java.nio.charset.StandardCharsets.UTF_8),limit);
    }
    public static byte[][] list(String path,int limit) throws java.io.IOException {
        return listUtf8(path.getBytes(java.nio.charset.StandardCharsets.UTF_8),limit);
    }
    public static long copy(String path,int outputFd,long limit)throws java.io.IOException {
        return copyUtf8(path.getBytes(java.nio.charset.StandardCharsets.UTF_8),outputFd,limit);
    }
    private static native long copyUtf8(byte[] path,int outputFd,long limit)throws java.io.IOException;
    private static native byte[] readUtf8(byte[] path,int limit) throws java.io.IOException;
    private static native byte[][] listUtf8(byte[] path,int limit) throws java.io.IOException;
}
