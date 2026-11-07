package com.ai.codex;

import android.content.Context;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import android.util.AtomicFile;
import com.ai.codex.install.GuestIdentity;
import org.json.JSONObject;
import java.io.File;
import java.io.ByteArrayOutputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.util.Arrays;
import java.util.UUID;

/** Installs only Codex-owned tools/context, retaining the native runtime contract. */
public final class CodexLocalTools {
    private CodexLocalTools() {}

    public static File install(Context context, GuestIdentity identity, File shellHome) throws Exception {
        File files = context.getFilesDir().getCanonicalFile();
        int uid = context.getApplicationInfo().uid;
        // Fresh transactions publish files/debian as an atomic, app-private
        // symlink. Resolve that one installation pointer, then keep all tool
        // directory walks on the real owned root without following guest links.
        File guestRoot = new File(files, "debian").getCanonicalFile();
        StructStat guestState = Os.lstat(guestRoot.getPath());
        if (!guestRoot.toPath().startsWith(files.toPath()) || guestRoot.equals(files)
                || !OsConstants.S_ISDIR(guestState.st_mode) || guestState.st_uid != uid)
            throw new IOException("Codex guest root is outside the owned application files");
        File tools = directory(files, "codex-tools", uid);
        File bin = directory(files, "codex-tools/bin", uid);
        writeAsset(context, tools, "codex_tools.py", "codex-tools/codex_tools.py", uid);
        writeAsset(context, tools, "phone_relay.py", "codex-android/scripts/phone_relay.py", uid);
        JSONObject config = new JSONObject();
        config.put("schema", "codex.local-tools.v1");
        config.put("uid", uid);
        config.put("filesDir", files.getPath());
        config.put("nativeLibraryDir", context.getApplicationInfo().nativeLibraryDir);
        config.put("guestHome", identity.home);
        config.put("guestUser", identity.user);
        config.put("guestIds", identity.prootIds());
        config.put("versionCode", context.getPackageManager().getPackageInfo(context.getPackageName(), 0).getLongVersionCode());
        write(new File(tools, "installation.json"), (config.toString(2) + "\n").getBytes(StandardCharsets.UTF_8), uid);
        String target = context.getApplicationInfo().nativeLibraryDir + "/libcodex_tools_launcher.so";
        if (!new File(target).isFile()) throw new IOException("Codex tool launcher is absent from the APK");
        for (String name : new String[]{"codex-tools", "git", "make", "node", "npm", "npx", "gcc", "g++", "diff", "tar", "gzip", "xz",
                "workspace-node", "workspace-python3", "pnpm", "pdftoppm", "pdftotext", "pdfinfo", "libreoffice",
                "soffice", "heif-convert", "JxrDecApp"}) {
            File link = new File(bin, name);
            try {
                StructStat state = Os.lstat(link.getPath());
                if (!OsConstants.S_ISLNK(state.st_mode) || state.st_uid != uid)
                    throw new IOException("Tool alias is not an app-owned link: " + name);
                if (Os.readlink(link.getPath()).equals(target)) continue;
            } catch (ErrnoException absent) {
                if (absent.errno != OsConstants.ENOENT) throw absent;
            }
            File temporary = new File(bin, "." + name + "." + UUID.randomUUID());
            Os.symlink(target, temporary.getPath());
            Os.rename(temporary.getPath(), link.getPath());
        }
        File contextDir = directory(guestRoot, "usr/local/lib/codex", uid);
        File share = directory(guestRoot, "usr/local/share/codex", uid);
        GnuEngineInstaller.install(context, directory(guestRoot, "usr/local/libexec/codex", uid), share);
        writeAsset(context, contextDir, "codex_agent_context.py", "codex-tools/codex_agent_context.py", uid);
        writeAsset(context, contextDir, "codex-workspace-provider.cjs", "codex-tools/codex-workspace-provider.cjs", uid);
        writeAsset(context, contextDir, "install-workspace-provider.py", "codex-tools/install-workspace-provider.py", uid);
        writeAsset(context, contextDir, "codex_phone_profile.py", "codex-tools/codex_phone_profile.py", uid);
        writeAsset(context, contextDir, "install_phone_mcp.py", "codex-tools/install_phone_mcp.py", uid);
        writeAsset(context, contextDir, "codex_native_dialogs.py", "codex-tools/codex_native_dialogs.py", uid);
        writeAsset(context, contextDir, "codex-phone-dialogs.css", "codex-tools/codex-phone-dialogs.css", uid);
        // Ship the admission-before-context ordering together with its adapter.
        // Updating Python alone would leave the previous guest launch order.
        File guestBin = directory(guestRoot, "usr/local/bin", uid);
        writeAsset(context, guestBin, "codex-session", "codex-tools/codex-session.sh", uid);
        // dbus-run-session re-executes this script, so it must be executable.
        Os.chmod(new File(guestBin, "codex-session").getPath(), 0700);
        for (String name : new String[]{"workspace-node-check.cjs", "workspace-python-check.py", "workspace-render-check.py"})
            writeAsset(context, contextDir, name, "codex-tools/" + name, uid);
        // The source manifest describes the upstream reference device. Bind
        // this installation's facts for diagnostic metadata; global AGENTS injection is disabled.
        JSONObject environment;
        try (InputStream input = context.getAssets().open("codex-tools/agent-environment.v1.json")) {
            environment = new JSONObject(new String(input.readAllBytes(), StandardCharsets.UTF_8));
        }
        JSONObject host = environment.getJSONObject("clientHost");
        String device = android.os.Build.MANUFACTURER + " " + android.os.Build.MODEL;
        if ("OnePlus".equalsIgnoreCase(android.os.Build.MANUFACTURER) && "PJZ110".equals(android.os.Build.MODEL))
            device += " (OnePlus 13)";
        host.put("referenceDevice", device);
        host.put("androidRoot", CodexDeviceFeatures.enabled(context, "root"));
        host.put("rootObservation", "Root channel enabled only after an observed UID 0 probe; not a project execution identity");
        host.put("referenceApi", android.os.Build.VERSION.SDK_INT);
        host.put("architecture", android.os.Build.SUPPORTED_ABIS[0]);
        host.put("applicationName", context.getApplicationInfo().loadLabel(context.getPackageManager()).toString());
        host.put("androidVersion", android.os.Build.VERSION.RELEASE);
        host.put("socModel", android.os.Build.SOC_MODEL);
        host.put("kernelVersion", System.getProperty("os.version", "unknown"));
        host.put("timezone", java.util.TimeZone.getDefault().getID());
        JSONObject storage = SharedProjectStorage.inspect(context);
        host.put("sharedStorage", storage);
        host.put("evidence", "Current Android Build fields, package label and system time zone");
        environment.put("revision", environment.getString("revision") + ".android-runtime-facts.1");
        environment.getJSONObject("guest").put("codex", "/usr/local/bin/codex-native (native task controller); /usr/lib/chatgpt/resources/codex (official startup/configuration helper)");
        write(new File(share, "agent-environment.v1.json"), (environment.toString(2) + "\n").getBytes(StandardCharsets.UTF_8), uid);
        JSONObject bridge = new JSONObject().put("schema", "codex.android.bridge.v1").put("androidUid", uid)
            .put("httpUrl", "http://127.0.0.1:3090").put("httpToken", CodexDeviceHttp.token(context));
        write(new File(share, "android-bridge.json"), (bridge.toString() + "\n").getBytes(StandardCharsets.UTF_8), uid);
        // Plugin source is APK-owned and isolated from official plugin caches.
        File androidPlugin = directory(guestRoot, "usr/local/share/codex/plugins/codex-android", uid);
        installPluginAssets(context, guestRoot, "codex-android", "usr/local/share/codex/plugins/codex-android", uid);
        if (!shellHome.getCanonicalFile().toPath().startsWith(files.toPath()))
            throw new IOException("Native shell home is outside Codex files");
        installShellPath(new File(shellHome, ".profile"), bin, uid);
        installShellPath(new File(shellHome, ".bashrc"), bin, uid);
        return tools;
    }

    private static void installShellPath(File profile, File bin, int uid) throws Exception {
        String begin = "# codex:local-tools:v1 begin\n";
        String end = "# codex:local-tools:v1 end\n";
        String path = bin.getPath().replace("'", "'\"'\"'");
        String block = begin + "case :${PATH-}: in\n  *:'" + path + "':*) ;;\n"
                + "  *) export PATH='" + path + "'${PATH:+:$PATH} ;;\nesac\n" + end;
        String original = "";
        try {
            StructStat state = Os.lstat(profile.getPath());
            if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_nlink != 1 || state.st_size > 65536)
                throw new IOException("Native shell profile is not an owned bounded regular file");
            byte[] bytes = Files.readAllBytes(profile.toPath());
            original = new String(bytes, StandardCharsets.UTF_8);
            if (!Arrays.equals(bytes, original.getBytes(StandardCharsets.UTF_8)))
                throw new IOException("Native shell profile is not UTF-8");
        } catch (ErrnoException absent) {
            if (absent.errno != OsConstants.ENOENT) throw absent;
        }
        int first = original.indexOf(begin), last = original.indexOf(end);
        if ((first < 0) != (last < 0) || (first >= 0 && (last < first
                || original.indexOf(begin, first + begin.length()) >= 0
                || original.indexOf(end, last + end.length()) >= 0)))
            throw new IOException("Ambiguous Codex shell profile block");
        String merged = first < 0 ? original + (original.isEmpty() || original.endsWith("\n") ? "" : "\n") + block
                : original.substring(0, first) + block + original.substring(last + end.length());
        byte[] bytes = merged.getBytes(StandardCharsets.UTF_8);
        if (bytes.length > 65536) throw new IOException("Native shell profile exceeds its bound");
        write(profile, bytes, uid);
    }

    private static void installPluginAssets(Context context, File files, String asset, String relative, int uid) throws Exception {
        String[] children = context.getAssets().list(asset);
        if (children == null) throw new IOException("Missing Android plugin assets");
        File destination = directory(files, relative, uid);
        for (String child : children) {
            if (!child.matches("[A-Za-z0-9_.-]+")) throw new IOException("Unexpected Android plugin asset name");
            String entry = asset + "/" + child;
            String[] nested = context.getAssets().list(entry);
            if (nested != null && nested.length > 0) installPluginAssets(context, files, entry, relative + "/" + child, uid);
            else writeAsset(context, destination, child, entry, uid);
        }
    }

    private static File directory(File root, String relative, int uid) throws Exception {
        File current = root;
        for (String part : relative.split("/")) {
            current = new File(current, part);
            try { Os.mkdir(current.getPath(), 0700); }
            catch (ErrnoException exists) { if (exists.errno != OsConstants.EEXIST) throw exists; }
            StructStat state = Os.lstat(current.getPath());
            if (!OsConstants.S_ISDIR(state.st_mode) || state.st_uid != uid)
                throw new IOException("Codex tool directory is not app-owned: " + relative);
        }
        return current;
    }

    private static void writeAsset(Context context, File directory, String name, String asset, int uid) throws Exception {
        try (InputStream stream = context.getAssets().open(asset)) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[4096];
            int count;
            while ((count = stream.read(buffer)) != -1) {
                if (bytes.size() + count > 65536) throw new IOException("Codex tool asset is too large");
                bytes.write(buffer, 0, count);
            }
            write(new File(directory, name), bytes.toByteArray(), uid);
        }
    }

    private static void write(File file, byte[] bytes, int uid) throws Exception {
        try {
            StructStat state = Os.lstat(file.getPath());
            if (!OsConstants.S_ISREG(state.st_mode) || state.st_uid != uid || state.st_nlink != 1)
                throw new IOException("Codex tool destination is not an owned regular file: " + file.getName());
            if (Arrays.equals(Files.readAllBytes(file.toPath()), bytes)) return;
        } catch (ErrnoException absent) {
            if (absent.errno != OsConstants.ENOENT) throw absent;
        }
        AtomicFile atomic = new AtomicFile(file);
        FileOutputStream output = null;
        try {
            output = atomic.startWrite();
            output.write(bytes);
            Os.fchmod(output.getFD(), 0600);
            atomic.finishWrite(output);
        } catch (Exception error) {
            if (output != null) atomic.failWrite(output);
            throw error;
        }
    }
}
