package com.ai.codex;

import java.io.File;
import java.util.Locale;

/** A typed bridge path check; ordinary project tools retain their app-UID access. */
public final class DeviceFilePolicy {
    private DeviceFilePolicy() {}
    public static void checkComponents(String path) {
        if (path == null || path.length() > 4096 || !path.startsWith("/") || path.indexOf(0) >= 0)
            throw new DeviceCommandPolicy.Blocked("invalid_file_path");
        for (String part : path.split("/")) {
            String name = part.toLowerCase(Locale.ROOT);
            if (name.equals("..") || name.equals(".dsh") || name.equals(".ssh")
                    || name.equals(".android") || name.equals(".codex") || name.equals(".gnupg")
                    || name.equals(".pki") || name.equals("keyrings"))
                throw new DeviceCommandPolicy.Blocked("credential_path_denied");
        }
    }
    static String[] sharedComponents(String path) {
        if (path == null || path.length() > 4096 || path.indexOf(0) >= 0)
            throw new DeviceCommandPolicy.Blocked("invalid_file_path");
        for (String root : new String[]{"/sdcard", "/storage/emulated/0"}) {
            if (path.equals(root) || path.equals(root + "/")) return new String[0];
            if (!path.startsWith(root + "/")) continue;
            String relative = path.substring(root.length() + 1);
            if (relative.endsWith("/")) relative = relative.substring(0, relative.length() - 1);
            String[] parts = relative.split("/", -1);
            for (String part : parts) {
                if (part.isEmpty() || part.equals(".") || part.equals(".."))
                    throw new DeviceCommandPolicy.Blocked("invalid_file_path");
            }
            return parts;
        }
        throw new DeviceCommandPolicy.Blocked("file_outside_shared_storage");
    }
    static void requireSharedApk(String path) {
        if (sharedComponents(path).length == 0 || !path.toLowerCase(Locale.ROOT).endsWith(".apk"))
            throw new DeviceCommandPolicy.Blocked("apk_file_required");
    }
    public static File readable(File candidate, File privateProjects, File sharedRoot) throws Exception {
        checkComponents(candidate.getPath());
        File actual = candidate.getCanonicalFile();
        checkComponents(actual.getPath());
        if (!actual.toPath().startsWith(privateProjects.getCanonicalFile().toPath())
                && !actual.toPath().startsWith(sharedRoot.getCanonicalFile().toPath()))
            throw new DeviceCommandPolicy.Blocked("file_outside_project_or_shared_storage");
        return actual;
    }
}
