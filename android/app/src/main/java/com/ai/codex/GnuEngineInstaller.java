package com.ai.codex;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.AtomicFile;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.List;
import org.json.JSONArray;
import org.json.JSONObject;

/** Updates only the separate controller and its matching Code Mode host, before launch. */
public final class GnuEngineInstaller {
    private GnuEngineInstaller() { }
    private static final List<String> NAMES = List.of("codex-native", "codex-code-mode-host");

    public static void install(Context context, File bin, File share) throws Exception {
        String[] assets = context.getAssets().list("gnu-engine");
        if (assets == null || !java.util.Arrays.asList(assets).contains("manifest.json")) return;
        int uid = context.getApplicationInfo().uid;
        ownedDirectory(bin, uid);
        ownedDirectory(share, uid);
        byte[] metadata;
        try (InputStream input = context.getAssets().open("gnu-engine/manifest.json")) {
            metadata = input.readNBytes(65537);
        }
        if (metadata.length > 65536) throw new java.io.IOException("GNU engine manifest exceeds limit");
        JSONObject manifest = new JSONObject(new String(metadata, StandardCharsets.UTF_8));
        if (!"codex.gnu-engine.payload.v1".equals(manifest.getString("schema"))
                || !"aarch64-unknown-linux-gnu".equals(manifest.getString("target")))
            throw new java.io.IOException("Unsupported GNU engine payload");
        String identity = EnginePayloadFile.hex(MessageDigest.getInstance("SHA-256").digest(metadata));
        JSONArray files = manifest.getJSONArray("files");
        if (files.length() != NAMES.size()) throw new java.io.IOException("Incomplete GNU engine payload");
        AtomicFile receiptFile = new AtomicFile(new File(share, "gnu-engine-installed.json"));
        JSONObject receipt = new JSONObject();
        try {
            StructStat previousReceipt = ownedFile(receiptFile.getBaseFile(), uid);
            if (previousReceipt.st_size > 4096)
                throw new java.io.IOException("GNU engine receipt exceeds limit");
            byte[] bytes = receiptFile.readFully();
            if (bytes.length <= 4096) receipt = new JSONObject(new String(bytes, StandardCharsets.UTF_8));
        } catch (java.io.FileNotFoundException absent) {
            // First payload upgrade. Other metadata/admission errors remain errors.
        } catch (ErrnoException absent) {
            if (absent.errno != OsConstants.ENOENT) throw absent;
        } catch (org.json.JSONException invalidReceipt) {
            // A bounded but damaged receipt cannot attest the current pair.
            receipt = new JSONObject();
        }
        boolean installed = identity.equals(receipt.optString("manifest"));
        JSONArray admitted = receipt.optJSONArray("files");
        for (int index = 0; index < files.length(); index++) {
            JSONObject item = files.getJSONObject(index);
            if (!NAMES.get(index).equals(item.getString("name")))
                throw new java.io.IOException("Unexpected GNU engine filename");
            File destination = new File(bin, NAMES.get(index));
            try {
                StructStat state = ownedFile(destination, uid);
                JSONObject previous = admitted == null ? null : admitted.optJSONObject(index);
                installed &= previous != null && state.st_size == item.getLong("bytes")
                        && previous.optLong("inode", -1) == state.st_ino
                        && previous.optLong("device", -1) == state.st_dev;
            } catch (ErrnoException absent) {
                if (absent.errno != OsConstants.ENOENT) throw absent;
                installed = false;
            }
        }
        if (installed) return; // No full binary reread on every desktop launch.
        ArrayList<File> staged = new ArrayList<>();
        try {
            for (int index = 0; index < files.length(); index++) {
                JSONObject item = files.getJSONObject(index);
                File temporary = File.createTempFile(".gnu-engine-", ".next", bin);
                staged.add(temporary);
                try (InputStream input = context.getAssets().open("gnu-engine/" + item.getString("name"))) {
                    EnginePayloadFile.stage(input, temporary.toPath(), item.getLong("bytes"), item.getString("sha256"));
                }
                Os.chmod(temporary.getPath(), 0700);
            }
            // Both payloads are complete before either live pathname changes.
            // No desktop/controller is started until this method commits.
            for (int index = 0; index < files.length(); index++)
                Os.rename(staged.get(index).getPath(), new File(bin, NAMES.get(index)).getPath());
            JSONArray installedFiles = new JSONArray();
            for (String name : NAMES) {
                StructStat state = ownedFile(new File(bin, name), uid);
                installedFiles.put(new JSONObject().put("name", name).put("inode", state.st_ino).put("device", state.st_dev));
            }
            byte[] result = (new JSONObject().put("version", manifest.getString("version"))
                    .put("manifest", identity).put("sourceBase", manifest.getString("sourceBase"))
                    .put("files", installedFiles).toString(2) + "\n").getBytes(StandardCharsets.UTF_8);
            FileOutputStream output = null;
            try {
                output = receiptFile.startWrite();
                output.write(result);
                Os.fchmod(output.getFD(), 0600);
                receiptFile.finishWrite(output);
            } catch (Exception error) {
                if (output != null) receiptFile.failWrite(output);
                throw error;
            }
        } finally {
            for (File file : staged) Files.deleteIfExists(file.toPath());
        }
    }

    private static void ownedDirectory(File directory, int uid) throws Exception {
        StructStat state = Os.lstat(directory.getPath());
        if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid || (state.st_mode & 0022) != 0
                || !directory.getCanonicalFile().equals(directory.getAbsoluteFile()))
            throw new java.io.IOException("GNU engine directory is not private application storage");
    }
    private static StructStat ownedFile(File file, int uid) throws Exception {
        StructStat state = Os.lstat(file.getPath());
        if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_nlink != 1 || (state.st_mode & 0022) != 0)
            throw new java.io.IOException("GNU engine destination is not an owned regular file");
        return state;
    }
}
