package com.ai.codex.install;

import android.content.Context;
import android.content.res.AssetManager;
import android.os.PowerManager;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import com.ai.codex.GnuEngineInstaller;
import com.ai.codex.InputStreams;
import java.io.File;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.attribute.PosixFilePermissions;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;
import java.util.function.Consumer;
import org.json.JSONArray;
import org.json.JSONObject;

/** Cover updates reuse the same APK-owned image as first install. Only desktop
 * and GNU payloads are materialized; accounts, projects and guest settings stay put. */
public final class EmbeddedRuntimePayloadInstaller {
    private static final String TEMP_PREFIX = ".codex-payload-update-";
    private static final String DESKTOP = "usr/lib/chatgpt";
    private static final String ENGINE = "usr/local/libexec/codex";

    private EmbeddedRuntimePayloadInstaller() { }

    public static synchronized void install(Context context, File installedRoot, Consumer<String> progress)
            throws Exception {
        AssetManager assets = context.getAssets();
        if (!Arrays.asList(assets.list("phone-runtime")).contains("codex-phone-rootfs.tgz")) return;
        // Standalone/split payload installers retain their existing behavior.
        if (Arrays.asList(assets.list("desktop-client")).contains("client.tgz")) return;
        JSONObject release = metadata(assets, "phone-runtime/release.json");
        JSONObject desktop = metadata(assets, "desktop-client/manifest.json");
        JSONObject engine = metadata(assets, "gnu-engine/manifest.json");
        requireBinding(release, desktop, engine);
        Path files = context.getFilesDir().getCanonicalFile().toPath();
        Path root = installedRoot.getCanonicalFile().toPath();
        if (root.equals(files) || !root.startsWith(files)) throw new IOException("Image update root is not app-owned");
        int uid = context.getApplicationInfo().uid;
        requireDirectory(root, uid);
        // An interrupted extraction is never published or used as installation evidence.
        try (DirectoryStream<Path> children = Files.newDirectoryStream(files, TEMP_PREFIX + "*")) {
            for (Path child : children) { requireDirectory(child, uid); removeTree(child); }
        }
        File bin = root.resolve(ENGINE).toFile(), share = root.resolve("usr/local/share/codex").toFile();
        boolean needsEngine = false, needsDesktop = false;
        try { GnuEngineInstaller.install(context, bin, share); }
        catch (PayloadRequiredException update) { needsEngine = true; }
        try { DesktopClientInstaller.install(context, root.toFile(), () -> { }); }
        catch (PayloadRequiredException update) { needsDesktop = true; }
        if (!needsEngine && !needsDesktop) return;

        JSONObject value = release.getJSONObject("spec");
        RootfsExtractor.Spec spec = new RootfsExtractor.Spec(value.getString("sha256"),
                value.getLong("compressedBytes"), value.getLong("payloadBytes"),
                value.getLong("maxTarBytes"), value.getInt("members"));
        Set<String> selected = new HashSet<>();
        long extractedBytes = 0;
        if (needsDesktop) { selected.add(DESKTOP); extractedBytes += desktop.getLong("payloadBytes"); }
        if (needsEngine) {
            selected.add(ENGINE);
            JSONArray binaries = engine.getJSONArray("files");
            for (int i = 0; i < binaries.length(); i++) extractedBytes += binaries.getJSONObject(i).getLong("bytes");
        }
        if (files.toFile().getUsableSpace() < spec.compressedBytes + extractedBytes + 512L * 1024 * 1024)
            throw new IOException("内部存储空间不足，请释放空间后重试 Codex 更新。");
        PowerManager.WakeLock wake = context.getSystemService(PowerManager.class)
                .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Codex:payload-update");
        wake.acquire();
        Path temporary = null;
        try {
            progress.accept("正在从完整环境中更新 Codex 前后端，首次更新需要几分钟…");
            temporary = Files.createTempDirectory(files, TEMP_PREFIX,
                    PosixFilePermissions.asFileAttribute(PosixFilePermissions.fromString("rwx------")));
            Path payload;
            try (InputStream input = assets.open("phone-runtime/codex-phone-rootfs.tgz", AssetManager.ACCESS_STREAMING)) {
                payload = RootfsExtractor.prepareSubset(input, temporary, spec,
                        new AndroidRootfsTransaction.Posix(), selected).root;
            }
            if (needsDesktop) DesktopClientInstaller.install(context, root.toFile(), () -> { }, payload.resolve(DESKTOP));
            if (needsEngine) GnuEngineInstaller.install(context, bin, share, payload.resolve(ENGINE).toFile());
            progress.accept("Codex 前后端更新完成，正在启动…");
        } finally {
            try { if (temporary != null) removeTree(temporary); }
            finally { wake.release(); }
        }
    }

    private static JSONObject metadata(AssetManager assets, String name) throws Exception {
        try (InputStream input = assets.open(name)) {
            byte[] bytes = InputStreams.readNBytes(input, 65537);
            if (bytes.length > 65536) throw new IOException("Image payload metadata exceeds its bound");
            return new JSONObject(new String(bytes, StandardCharsets.UTF_8));
        }
    }

    private static void requireBinding(JSONObject release, JSONObject desktop, JSONObject engine) throws Exception {
        if (!"codex.phone-image.v1".equals(release.getString("format"))
                || !"codex-phone-rootfs.tar.gz".equals(release.getString("archive"))
                || release.getBoolean("accountIncluded") || release.getBoolean("keyringIncluded"))
            throw new IOException("Unsupported embedded image payloads");
        JSONObject client = release.getJSONObject("clientPayload"), backend = release.getJSONObject("enginePayload");
        for (String key : new String[]{"schema", "version", "architecture", "sha256", "payloadBytes"})
            if (!desktop.get(key).toString().equals(client.get(key).toString()))
                throw new IOException("Embedded desktop descriptor differs from image");
        for (String key : new String[]{"schema", "version", "target", "sourceBase"})
            if (!engine.getString(key).equals(backend.getString(key)))
                throw new IOException("Embedded GNU descriptor differs from image");
        JSONArray binaries = engine.getJSONArray("files"), expected = backend.getJSONArray("files");
        if (binaries.length() != 2 || expected.length() != 2) throw new IOException("Incomplete embedded GNU pair");
        for (int i = 0; i < 2; i++) for (String key : new String[]{"name", "bytes", "sha256"})
            if (!binaries.getJSONObject(i).get(key).toString().equals(expected.getJSONObject(i).get(key).toString()))
                throw new IOException("Embedded GNU file differs from image");
    }

    private static void requireDirectory(Path path, int uid) throws Exception {
        StructStat state = Os.lstat(path.toString());
        if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid || (state.st_mode & 0022) != 0
                || !path.equals(path.toRealPath())) throw new IOException("Image update directory is not app-owned");
    }

    private static void removeTree(Path path) throws Exception {
        if (Files.isDirectory(path, LinkOption.NOFOLLOW_LINKS)) {
            Os.chmod(path.toString(), 0700);
            try (DirectoryStream<Path> children = Files.newDirectoryStream(path)) {
                for (Path child : children) removeTree(child);
            }
        }
        Files.delete(path);
    }
}
