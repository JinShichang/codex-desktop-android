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
