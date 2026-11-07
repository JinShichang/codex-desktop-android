package com.ai.codex;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.ParcelFileDescriptor;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicBoolean;

/** Policy is checked here at the native Android endpoint, not in model/plugin text. */
public final class CodexDeviceCommands {
    private CodexDeviceCommands() {}
    public static JSONObject status() throws Exception {
        return new JSONObject().put("policy", DeviceCommandPolicy.REVISION)
            .put("alwaysEnabled", true).put("channels", new JSONArray().put("app").put("root").put("shizuku").put("adb"))
            .put("privilegedChannelsRequireAuthorization", true).put("shellPrograms", false);
    }
    public static JSONObject execute(Context context, JSONObject args) throws Exception {
        try {
            DeviceCommandPolicy.Plan plan=parse(args);
            String channel=args.optString("channel","app");
            DeviceCommandPolicy.requireChannel(plan, channel);
            if ("root".equals(channel)) return CodexRootChannel.execute(context,args,plan.fileCommand());
            if ("shizuku".equals(channel)) return CodexShizukuChannel.execute(context,args);
            if ("adb".equals(channel)) return CodexAdbChannel.execute(context,plan);
            return executeLocal(context,args,"app");
        } catch(DeviceCommandPolicy.Blocked blocked) { return blocked(blocked.getMessage()); }
    }
    private static JSONObject blocked(String error) throws Exception {
        return new JSONObject().put("ok",false).put("error",error).put("exitCode",126);
    }
    static DeviceCommandPolicy.Plan parse(JSONObject args) throws Exception {
            if (args == null || args.length() < 1 || args.length() > 2
                    || !args.has("argv") || args.has("channel") && !(args.opt("channel") instanceof String))
                throw new DeviceCommandPolicy.Blocked("invalid_request");
            java.util.Iterator<String> keys = args.keys();
            while (keys.hasNext()) {
                String key = keys.next();
                if (!key.equals("argv") && !key.equals("channel"))
                    throw new DeviceCommandPolicy.Blocked("unknown_request_field");
            }
            JSONArray values = args.optJSONArray("argv");
            if (values == null || values.length() > 32) throw new DeviceCommandPolicy.Blocked("invalid_argv");
            List<String> argv = new ArrayList<>();
            for (int i = 0; i < values.length(); i++) {
                if (!(values.opt(i) instanceof String)) throw new DeviceCommandPolicy.Blocked("invalid_argument");
                argv.add(values.getString(i));
            }
            DeviceCommandPolicy.Plan plan = DeviceCommandPolicy.inspect(argv);
            return plan;
    }
    static JSONObject executeLocal(Context context, JSONObject args, String channel) throws Exception {
        try {
            DeviceCommandPolicy.Plan plan = parse(args);
            if ("root".equals(channel)) {
                if (android.os.Process.myUid()!=0 || !"root".equals(args.optString("channel")))
                    throw new DeviceCommandPolicy.Blocked("privileged_uid_required");
                CodexPrivilegedContext.requireInteractive(context);
            } else if ("shizuku".equals(channel)) {
                int uid=android.os.Process.myUid();
                if((uid!=0&&uid!=2000)||!"shizuku".equals(args.optString("channel")))throw new DeviceCommandPolicy.Blocked("privileged_uid_required");
            } else DeviceCommandPolicy.requireAppChannel(args.optString("channel", "app"));
            if (!"root".equals(channel)) requireInteractive(context);
            DeviceCommandPolicy.requireChannel(plan, channel);
            if (plan.copiesFile()) {
                if ("app".equals(channel)) CodexDeviceFeatures.require(context, "files");
                int end = plan.argv.size();
                long bytes = CodexDeviceSharedFiles.copy(plan.argv.get(end - 2), plan.argv.get(end - 1));
                return new JSONObject().put("ok", true).put("exitCode", 0).put("bytes", bytes).put("channel", channel);
            }
            if (plan.installsApp()) {
                return installApp(plan, channel);
            }
            validateStop(context,plan);
            return run(plan.argv, channel, null, 0);
        } catch (DeviceCommandPolicy.Blocked blocked) {
            return new JSONObject().put("ok", false).put("error", blocked.getMessage()).put("exitCode", 126);
        } catch (PackageManager.NameNotFoundException missing) {
            return new JSONObject().put("ok", false).put("error", "[POLICY_BLOCKED] package_identity_unavailable").put("exitCode", 126);
        }
    }
    private static JSONObject installApp(DeviceCommandPolicy.Plan plan, String channel) throws Exception {
        ParcelFileDescriptor source;
        try {
            source = CodexDeviceSharedFiles.openApk(plan.argv.get(plan.argv.size() - 1));
        } catch (IllegalArgumentException failure) {
            if (failure instanceof DeviceCommandPolicy.Blocked) throw failure;
            return new JSONObject().put("ok", false).put("error", failure.getMessage()).put("channel", channel);
        }
        try (InputStream input = new ParcelFileDescriptor.AutoCloseInputStream(source)) {
            long size = CodexDeviceSharedFiles.size(source);
            if (size == 0) throw new DeviceCommandPolicy.Blocked("empty_apk");
            List<String> install = new ArrayList<>(List.of("/system/bin/cmd", "package", "install"));
            if (plan.argv.size() == 4) install.add(plan.argv.get(2));
            install.addAll(List.of("--user", "current", "--restrict-permissions", "-S", Long.toString(size), "-"));
            return run(install, channel, input, size);
        }
    }
    static void requireInteractive(Context context){
        android.app.KeyguardManager guard=context.getSystemService(android.app.KeyguardManager.class);
        android.os.PowerManager power=context.getSystemService(android.os.PowerManager.class);
        if(guard==null||power==null||guard.isDeviceLocked()||guard.isKeyguardLocked()||!power.isInteractive())
            throw new DeviceCommandPolicy.Blocked("device_locked_or_asleep");
    }
    static void validateStop(Context context,DeviceCommandPolicy.Plan plan)throws Exception {
        if (plan.stopPackage != null) {
                PackageManager pm = context.getPackageManager();
                ApplicationInfo info = pm.getApplicationInfo(plan.stopPackage, 0);
                DeviceCommandPolicy.requireStoppable(plan.stopPackage, context.getPackageName(),
                    info.uid, context.getApplicationInfo().uid, info.flags);
                String[] owners = pm.getPackagesForUid(info.uid);
                if (owners == null || owners.length != 1 || !owners[0].equals(plan.stopPackage))
                    throw new DeviceCommandPolicy.Blocked("shared_uid_app_stop_denied");
                // Resolve again immediately before package-based stop; never issue a PID signal.
                ApplicationInfo current = pm.getApplicationInfo(plan.stopPackage, 0);
                if (current.uid != info.uid || current.flags != info.flags
                        || !java.util.Objects.equals(current.sourceDir, info.sourceDir))
                    throw new DeviceCommandPolicy.Blocked("app_identity_changed");
            }
    }
    private static JSONObject run(List<String> argv, String channel, InputStream apk, long apkSize) throws Exception {
        ProcessBuilder builder = new ProcessBuilder(argv).redirectErrorStream(true);
        builder.environment().clear();
        builder.environment().put("PATH", "/system/bin");
        builder.environment().put("LANG", "C.UTF-8");
        builder.directory(new java.io.File("/"));
        Process process = builder.start();
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        AtomicBoolean truncated = new AtomicBoolean(), readFailed = new AtomicBoolean();
        Thread reader = new Thread(() -> {
            try (InputStream input = process.getInputStream()) {
                byte[] buffer = new byte[4096]; int size;
                while ((size = input.read(buffer)) != -1) {
                    int remaining = 65536 - output.size();
                    output.write(buffer, 0, Math.min(size, remaining));
                    if (size > remaining) { truncated.set(true); process.destroyForcibly(); break; }
                }
            } catch (IOException error) { readFailed.set(true); }
        }, "Codex-device-output");
        reader.setDaemon(true);
        AtomicBoolean writeFailed = new AtomicBoolean();
        Thread writer = apk == null ? null : new Thread(() -> {
            // Give Package Manager a pipe. It never needs to open the shared-storage file.
            try (OutputStream stdin = process.getOutputStream()) {
                byte[] buffer = new byte[65536];
                long remaining = apkSize;
                while (remaining > 0) {
                    int count = apk.read(buffer, 0, (int) Math.min(remaining, buffer.length));
                    if (count < 0) throw new IOException("apk_truncated");
                    stdin.write(buffer, 0, count);
                    remaining -= count;
                }
            } catch (IOException failure) { writeFailed.set(true); }
        }, "Codex-apk-input");
        try {
            reader.start();
            if (writer == null) {
                process.getOutputStream().close();
            } else {
                writer.setDaemon(true);
                writer.start();
            }
            boolean finished = process.waitFor(apk == null ? 5 : DeviceCommandPolicy.FILE_COMMAND_TIMEOUT_SECONDS,
                    TimeUnit.SECONDS);
            if (!finished) process.destroyForcibly();
            reader.join(1000);
            if (reader.isAlive()) { process.getInputStream().close(); reader.join(1000); }
            if (writer != null) writer.join(1000);
            boolean incomplete = reader.isAlive() || truncated.get() || readFailed.get();
            int code = finished ? process.exitValue() : 124;
            boolean streamFailed = writer != null && (writer.isAlive() || writeFailed.get());
            String commandOutput = reader.isAlive() ? "" : output.toString(StandardCharsets.UTF_8.name());
            boolean dumpDenied = (argv.get(0).equals("/system/bin/dumpsys")
                || argv.get(0).equals("/system/bin/pm") && argv.get(1).equals("dump"))
                && commandOutput.contains("due to missing android.permission.DUMP permission");
            JSONObject result = new JSONObject().put("ok", finished && code == 0 && !incomplete && !streamFailed && !dumpDenied)
                .put("exitCode", code).put("timedOut", !finished).put("truncated", incomplete)
                .put("output", commandOutput)
                .put("channel", channel).put("androidUid", android.os.Process.myUid());
            if (apk != null && (!finished || incomplete || code == 0 && streamFailed))
                result.put("error", "apk_install_result_unknown").put("retrySafe", false);
            else if (streamFailed) result.put("error", "apk_install_stream_failed");
            else if (dumpDenied) result.put("error", "android_dump_permission_required");
            return result;
        } finally {
            process.destroyForcibly();
            process.getInputStream().close(); process.getErrorStream().close();
        }
    }
}
