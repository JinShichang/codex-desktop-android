package com.ai.codex.install;

import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkProperties;
import android.os.PowerManager;
import android.system.Os;
import org.json.JSONObject;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;
import java.util.concurrent.TimeUnit;
import java.util.function.Consumer;

/** Explicit complete-image first install. The APK authenticates every input;
 * the external archive is only transport. Existing installations are never replaced.
 * Keyring-only preparation remains evidence for its original scope; activation
 * additionally requires complete immutable inputs and an actual guest smoke test. */
public final class PhoneRuntimeInstaller {
    private PhoneRuntimeInstaller() {}
    public static void ensureInstalled(Context context, Consumer<String> progress) throws Exception {
        Path active = context.getFilesDir().toPath().resolve("debian");
        if (Files.exists(active, LinkOption.NOFOLLOW_LINKS)) return;
        List<String> assets = Arrays.asList(context.getAssets().list("phone-runtime"));
        if (!assets.contains("release.json"))
            throw new IOException("Linux 运行环境尚未部署完成，请等待完整安装包。");
        JSONObject release = new JSONObject(new String(asset(context, "release.json", 65536), StandardCharsets.UTF_8));
        if (!release.getString("format").equals("codex.phone-image.v1")
                || !release.getString("archive").equals("codex-phone-rootfs.tar.gz")
                || release.getBoolean("accountIncluded") || release.getBoolean("keyringIncluded"))
            throw new IOException("完整运行环境的安装描述不受支持。");
        JSONObject specValue = release.getJSONObject("spec");
        RootfsExtractor.Spec spec = new RootfsExtractor.Spec(specValue.getString("sha256"),
            specValue.getLong("compressedBytes"), specValue.getLong("payloadBytes"),
            specValue.getLong("maxTarBytes"), specValue.getInt("members"));
        byte[] inventory = asset(context, "inventory.json", 16 * 1024 * 1024);
        java.security.MessageDigest digest = java.security.MessageDigest.getInstance("SHA-256");
        StringBuilder hex = new StringBuilder();
        for (byte b : digest.digest(inventory)) hex.append(String.format(Locale.ROOT, "%02x", b & 255));
        if (inventory.length != release.getInt("inventoryBytes") || !hex.toString().equals(release.getString("inventorySha256")))
            throw new IOException("完整运行环境的文件清单校验失败。");
        File external = context.getExternalFilesDir(null);
        if (external == null) throw new IOException("无法访问运行环境安装文件。");
        Path archive = external.toPath().resolve("codex-phone-rootfs.tar.gz");
        RootfsTransaction.ArchiveSource source = () -> Files.newInputStream(archive, LinkOption.NOFOLLOW_LINKS);
        PowerManager.WakeLock wake = context.getSystemService(PowerManager.class)
            .newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "Codex:initial-install");
        wake.acquire();
        try {
            progress.accept("正在校验并安装 Linux 运行环境，首次启动需要几分钟…");
            Path root;
            try (RootfsTransaction transaction = AndroidRootfsTransaction.open(context, spec)) {
                // Preparation is resumable and never publishes files/debian.
                root = transaction.prepare(source).root;
                provisionMachineId(root);
                provisionDns(context, root);
            }
            progress.accept("正在创建本机账户和加密密钥环…");
            AndroidInactivePreparation.Result prepared = AndroidInactivePreparation.prepareKeyringOnly(context, spec, source,
                root.resolve("usr/local/lib/codex/install/initialize_keyring.py"), release.getString("initializerSha256"),
                root.resolve("usr/local/lib/codex/install/supervise_keyring.py"), release.getString("supervisorSha256"));
            progress.accept("正在验证本机运行环境…");
            try (RootfsTransaction transaction = AndroidRootfsTransaction.open(context, spec)) {
                transaction.activate(inactive -> {
                    if (!inactive.equals(prepared.root)) throw new IOException("Prepared runtime root changed");
                    GuestIdentity account = GuestIdentity.load(inactive);
                    if (account.uid != android.os.Process.myUid() || account.gid != Os.getgid()
                            || !account.user.equals("codex")) throw new IOException("Prepared runtime account changed");
                    PhoneImageManifest.verify(inactive, inventory, PhoneRuntimeInstaller::mode);
                    smoke(context, inactive, account);
                });
            }
            progress.accept("运行环境安装完成，正在启动 Codex…");
        } finally { wake.release(); }
    }

    private static int mode(Path path) throws IOException {
        try { return Os.lstat(path.toString()).st_mode; }
        catch (android.system.ErrnoException error) { throw new IOException("Cannot inspect installed runtime file", error); }
    }
    private static byte[] asset(Context context, String name, int limit) throws IOException {
        try (InputStream input = context.getAssets().open("phone-runtime/" + name)) {
            byte[] value = input.readNBytes(limit + 1);
            if (value.length > limit) throw new IOException("Phone runtime release metadata exceeds its bound");
            return value;
        }
    }
    private static void provisionDns(Context context, Path root) throws IOException {
        ConnectivityManager manager = context.getSystemService(ConnectivityManager.class);
        LinkProperties properties = manager.getLinkProperties(manager.getActiveNetwork());
        if (properties == null || properties.getDnsServers().isEmpty()) throw new IOException("请连接网络后重试安装。");
        Path file = root.resolve("etc/resolv.conf");
        if (!Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) throw new IOException("Guest resolver must be a regular file");
        StringBuilder text = new StringBuilder("# Current Android network DNS, provisioned by Codex.\n");
        for (java.net.InetAddress address : properties.getDnsServers())
            text.append("nameserver ").append(address.getHostAddress()).append('\n');
        Files.writeString(file, text, StandardCharsets.US_ASCII, StandardOpenOption.TRUNCATE_EXISTING, LinkOption.NOFOLLOW_LINKS);
    }
    private static void provisionMachineId(Path root) throws IOException {
        // Package configuration may generate an ID in the disposable host
        // image. Replace it before the first guest process with one device-local
        // value, and retain that value across interrupted preparation attempts.
        Path marker = root.resolve("etc/codex-machine-id.v1");
        String value;
        if (Files.exists(marker, LinkOption.NOFOLLOW_LINKS)) {
            if (!Files.isRegularFile(marker, LinkOption.NOFOLLOW_LINKS) || Files.size(marker) != 33)
                throw new IOException("Invalid device-local guest machine identity");
            value = Files.readString(marker, StandardCharsets.US_ASCII);
        } else {
            value = UUID.randomUUID().toString().replace("-", "") + "\n";
            Files.writeString(marker, value, StandardCharsets.US_ASCII,
                StandardOpenOption.CREATE_NEW, StandardOpenOption.WRITE, StandardOpenOption.SYNC, LinkOption.NOFOLLOW_LINKS);
        }
        if (!value.matches("[0-9a-f]{32}\\n")) throw new IOException("Invalid device-local guest machine identity");
        Path file = root.resolve("etc/machine-id");
        try {
            android.system.StructStat state = Os.lstat(file.toString());
            if (state.st_uid != android.os.Process.myUid() || !android.system.OsConstants.S_ISREG(state.st_mode))
                throw new IOException("Guest machine identity is not an owned regular file");
            Os.chmod(file.toString(), 0644);
        } catch (android.system.ErrnoException error) { throw new IOException("Cannot provision guest machine identity", error); }
        Files.writeString(file, value, StandardCharsets.US_ASCII, StandardOpenOption.TRUNCATE_EXISTING, LinkOption.NOFOLLOW_LINKS);
    }
    private static void smoke(Context context, Path root, GuestIdentity account) throws IOException {
        Path nativeDir = Path.of(context.getApplicationInfo().nativeLibraryDir);
        Path work = Files.createTempDirectory(context.getCacheDir().toPath(), "phone-smoke-");
        Path aliases = Files.createDirectory(work.resolve("native"));
        Files.createSymbolicLink(aliases.resolve("libtalloc.so.2"), nativeDir.resolve("libtalloc.so"));
        Path output = work.resolve("output.log");
        List<String> command = new ArrayList<>(List.of(nativeDir.resolve("libproot.so").toString(),
            "--kill-on-exit", "--link2symlink", "--sysvipc", "-r", root.toString(), "-i", account.prootIds(),
            "-w", account.home, "-b", "/dev", "-b", "/proc", "-b", "/sys", "-b", "/system", "-b", "/apex",
            "-b", work + ":/tmp", "/usr/bin/env", "-i", "HOME=" + account.home,
            "PATH=/usr/local/bin:/usr/bin:/bin", "LANG=C.UTF-8", "PYTHONDONTWRITEBYTECODE=1",
            "/bin/bash", "-c", "set -eu; python3 -B -c 'import secretstorage, websockets; print(\"CODEX_RUNTIME_SMOKE\")'; /usr/local/libexec/codex/codex-native --version"));
        ProcessBuilder builder = new ProcessBuilder(command).redirectErrorStream(true).redirectOutput(output.toFile());
        builder.environment().clear();
        builder.environment().put("PATH", "/system/bin");
        builder.environment().put("LD_LIBRARY_PATH", aliases + ":" + nativeDir);
        builder.environment().put("PROOT_LOADER", nativeDir.resolve("libproot-loader.so").toString());
        builder.environment().put("PROOT_LOADER_32", nativeDir.resolve("libproot-loader32.so").toString());
        builder.environment().put("PROOT_TMP_DIR", work.toString());
        Process process = builder.start();
        boolean interrupted = false;
        try {
            process.getOutputStream().close();
            if (!process.waitFor(90, TimeUnit.SECONDS)) throw new IOException("本机运行环境验证超时。");
            if (Files.size(output) > 65536) throw new IOException("Runtime smoke output exceeds its bound");
            String text = Files.readString(output);
            if (process.exitValue() != 0 || !text.contains("CODEX_RUNTIME_SMOKE") || !text.contains("codex-cli"))
                throw new IOException("本机运行环境验证失败，诊断记录：" + output.getFileName());
        } catch (InterruptedException stop) {
            interrupted = true;
            throw new java.io.InterruptedIOException("Runtime installation stopped");
        } finally {
            if (process.isAlive()) process.destroyForcibly();
            for (;;) {
                try { process.waitFor(); break; }
                catch (InterruptedException stop) { interrupted = true; process.destroyForcibly(); }
            }
            if (interrupted) Thread.currentThread().interrupt();
        }
    }
}
