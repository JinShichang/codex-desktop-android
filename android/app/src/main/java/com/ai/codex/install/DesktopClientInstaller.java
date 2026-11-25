package com.ai.codex.install;

import android.content.Context;
import android.content.res.AssetManager;
import android.system.Os;
import android.system.ErrnoException;
import android.system.OsConstants;
import android.system.StructStat;
import com.ai.codex.InputStreams;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.Comparator;
import java.util.stream.Collectors;
import org.json.JSONObject;

/** Installs an optional, APK-authenticated desktop payload alongside the existing client. */
public final class DesktopClientInstaller {
    private static final String ASSETS = "desktop-client";
    private static final String CLIENTS = "usr/local/lib/codex/desktops";

    private DesktopClientInstaller() {}

    public static String install(Context context, File installedRoot, Runnable onExtract)
            throws Exception {
        return install(context, installedRoot, onExtract, null);
    }

    /** Reuses a desktop tree from an unpublished, authenticated full image. */
    public static String install(Context context, File installedRoot, Runnable onExtract, Path imagePayload)
            throws Exception {
        AssetManager assets = context.getAssets();
        String[] entries = assets.list(ASSETS);
        if (entries == null || !Arrays.asList(entries).contains("manifest.json")) return null;

        JSONObject manifest;
        try (InputStream input = assets.open(ASSETS + "/manifest.json")) {
            byte[] metadata = InputStreams.readNBytes(input, 8193);
            if (metadata.length > 8192) throw new IOException("Desktop payload manifest exceeds limit");
            manifest = new JSONObject(new String(metadata, StandardCharsets.UTF_8));
        }
        String version = manifest.getString("version");
        if (!"codex.desktop.payload.v1".equals(manifest.getString("schema"))
                || !"arm64".equals(manifest.getString("architecture"))
                || !version.matches("[0-9]{2}\\.[0-9]{4}\\.[0-9]{4,6}")) {
            throw new IOException("Unsupported desktop payload");
        }
        RootfsExtractor.Spec spec = new RootfsExtractor.Spec(manifest.getString("sha256"),
                manifest.getLong("compressedBytes"), manifest.getLong("payloadBytes"),
                manifest.getLong("maxTarBytes"), manifest.getInt("members"));
        String name = version + "-" + spec.sha256.substring(0, 16);

        Path files = context.getFilesDir().getCanonicalFile().toPath();
        Path root = installedRoot.getCanonicalFile().toPath();
        if (root.equals(files) || !root.startsWith(files)) throw new IOException("Desktop root is not app-owned");
        int uid = context.getApplicationInfo().uid;
        Path parent = root;
        for (Path component : Path.of(CLIENTS)) {
            parent = parent.resolve(component);
            if (!Files.exists(parent, LinkOption.NOFOLLOW_LINKS)) createPrivateDirectory(parent);
            requireDirectory(parent, uid);
        }
        Path destination = parent.resolve(name);
        if (!Files.exists(destination, LinkOption.NOFOLLOW_LINKS)) {
            if (!Arrays.asList(entries).contains("client.tgz") && imagePayload == null) {
                // Split releases keep the original client in the authenticated
                // environment; v79 versioned clients remain preferred above.
                Path descriptor = root.resolve("usr/local/share/codex/desktop-runtime.json");
                StructStat metadata;
                try { metadata = Os.lstat(descriptor.toString()); }
                catch (ErrnoException absent) {
                    if (absent.errno != OsConstants.ENOENT) throw absent;
                    throw new PayloadRequiredException("环境中的桌面端需要更新。", absent);
                }
                if (!OsConstants.S_ISREG(metadata.st_mode) || metadata.st_uid != uid
                        || metadata.st_size > 8192 || (metadata.st_mode & 0022) != 0)
                    throw new IOException("Invalid environment desktop descriptor");
                JSONObject environment = new JSONObject(Files.readString(descriptor, StandardCharsets.UTF_8));
                for (String key : new String[]{"schema", "version", "architecture", "sha256"})
                    if (!manifest.getString(key).equals(environment.getString(key)))
                        throw new PayloadRequiredException("环境中的桌面版本与当前 APK 不兼容，请下载配套环境包。");
                Path bundled = root.resolve("usr/lib/chatgpt");
                requireClient(bundled, uid);
                return "/usr/lib/chatgpt";
            }
            onExtract.run();
            AndroidRootfsTransaction.Posix posix = new AndroidRootfsTransaction.Posix();
            if (imagePayload != null) {
                requireClient(imagePayload, uid);
                Files.move(imagePayload, destination, StandardCopyOption.ATOMIC_MOVE);
                posix.syncDirectory(parent);
                requireClient(destination, uid);
                return "/" + CLIENTS + "/" + name;
            }
            Path stage = Files.createTempDirectory(parent, ".incoming-",
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            try (InputStream input = assets.open(ASSETS + "/client.tgz", AssetManager.ACCESS_STREAMING)) {
                Path extracted = RootfsExtractor.prepare(input, stage, spec, posix).root;
                requireClient(extracted, uid);
                Files.move(extracted, destination, StandardCopyOption.ATOMIC_MOVE);
                posix.syncDirectory(parent);
            } finally {
                try (var paths = Files.walk(stage)) {
                    for (Path path : paths.sorted(Comparator.reverseOrder()).collect(Collectors.toList())) Files.delete(path);
                }
            }
        }
        requireClient(destination, uid);
        return "/" + CLIENTS + "/" + name;
    }

    private static void createPrivateDirectory(Path path) throws IOException {
        Files.createDirectory(path,
                PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
    }

    private static void requireDirectory(Path path, int uid) throws Exception {
        StructStat state = Os.lstat(path.toString());
        if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid || (state.st_mode & 0022) != 0) {
            throw new IOException("Invalid desktop payload directory");
        }
    }

    private static void requireClient(Path directory, int uid) throws Exception {
        requireDirectory(directory, uid);
        requireDirectory(directory.resolve("resources"), uid);
        for (String name : new String[]{"codex-launcher", "ChatGPT", "resources/codex", "resources/app.asar"}) {
            StructStat state = Os.lstat(directory.resolve(name).toString());
            if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_size == 0
                    || (state.st_mode & 0022) != 0 || (!name.endsWith(".asar") && (state.st_mode & 0100) == 0)) {
                throw new IOException("Invalid desktop payload file: " + name);
            }
        }
    }
}
