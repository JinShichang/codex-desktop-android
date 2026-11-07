package com.ai.codex;

import android.content.Context;
import android.os.Environment;
import android.system.Os;
import android.system.StructStat;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.UUID;

/** The user's explicit shared project location; no permission is self-granted. */
public final class SharedProjectStorage {
    private SharedProjectStorage() {}
    public static File root() throws Exception {
        File volume = Environment.getExternalStorageDirectory().getCanonicalFile();
        File root = new File(volume, "codex/Projects").getCanonicalFile();
        if (!root.toPath().startsWith(volume.toPath()) || root.equals(volume))
            throw new SecurityException("Shared project directory left primary storage");
        return root;
    }
    public static JSONObject inspect(Context context) throws Exception {
        JSONObject status = new JSONObject().put("allFilesAccess", Environment.isExternalStorageManager());
        if (!Environment.isExternalStorageManager()) return status.put("readWriteVerified", false);
        File root = root();
        if (!root.isDirectory() && !root.mkdirs()) throw new java.io.IOException("Cannot create shared project directory");
        byte[] expected = "Codex shared storage access\n".getBytes(StandardCharsets.UTF_8);
        File probe = new File(root, ".codex-access-" + UUID.randomUUID());
        try {
            Files.write(probe.toPath(), expected, java.nio.file.StandardOpenOption.CREATE_NEW);
            if (!java.util.Arrays.equals(expected, Files.readAllBytes(probe.toPath())))
                throw new java.io.IOException("Shared storage read/write verification failed");
        } finally {
            Files.deleteIfExists(probe.toPath());
        }
        StructStat named = Os.stat(root.getPath());
        status.put("root", root.getPath()).put("uid", named.st_uid).put("gid", named.st_gid)
                .put("mode", Integer.toOctalString(named.st_mode & 07777)).put("device", named.st_dev)
                .put("readWriteVerified", true);
        Files.writeString(new File(context.getFilesDir(), "shared-storage-status.json").toPath(), status.toString(2));
        return status;
    }
}
