package com.ai.codex;

import android.content.Context;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.InputStream;
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
            if ("root".equals(channel)) return CodexRootChannel.execute(context,args);
            if ("shizuku".equals(channel)) return CodexShizukuChannel.execute(context,args);
            if ("adb".equals(channel)) return CodexAdbChannel.execute(context,plan);
            return executeLocal(context,args,"app");
        } catch(DeviceCommandPolicy.Blocked blocked) { return blocked(blocked.getMessage()); }
    }
    private static JSONObject blocked(String error) throws Exception {
        return new JSONObject().put("ok",false).put("error",error).put("exitCode",126);
    }
    private static DeviceCommandPolicy.Plan parse(JSONObject args) throws Exception {
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
            requireInteractive(context);
            if ("root".equals(channel)) {
                if (android.os.Process.myUid()!=0 || !"root".equals(args.optString("channel")))
                    throw new DeviceCommandPolicy.Blocked("privileged_uid_required");
            } else if ("shizuku".equals(channel)) {
                int uid=android.os.Process.myUid();
                if((uid!=0&&uid!=2000)||!"shizuku".equals(args.optString("channel")))throw new DeviceCommandPolicy.Blocked("privileged_uid_required");
            } else DeviceCommandPolicy.requireAppChannel(args.optString("channel", "app"));
            validateStop(context,plan);
            return run(plan,channel);
        } catch (DeviceCommandPolicy.Blocked blocked) {
            return new JSONObject().put("ok", false).put("error", blocked.getMessage()).put("exitCode", 126);
        } catch (PackageManager.NameNotFoundException missing) {
            return new JSONObject().put("ok", false).put("error", "[POLICY_BLOCKED] package_identity_unavailable").put("exitCode", 126);
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
    private static JSONObject run(DeviceCommandPolicy.Plan plan, String channel) throws Exception {
        ProcessBuilder builder = new ProcessBuilder(plan.argv).redirectErrorStream(true);
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
            } catch (java.io.IOException error) { readFailed.set(true); }
        }, "Codex-device-output");
        reader.setDaemon(true);
        try {
            process.getOutputStream().close(); reader.start();
            boolean finished = process.waitFor(5, TimeUnit.SECONDS);
            if (!finished) process.destroyForcibly();
            reader.join(1000);
            if (reader.isAlive()) { process.getInputStream().close(); reader.join(1000); }
            boolean incomplete = reader.isAlive() || truncated.get() || readFailed.get();
            int code = finished ? process.exitValue() : 124;
            return new JSONObject().put("ok", finished && code == 0 && !incomplete)
                .put("exitCode", code).put("timedOut", !finished).put("truncated", incomplete)
                .put("output", reader.isAlive() ? "" : output.toString(StandardCharsets.UTF_8.name()))
                .put("channel", channel).put("androidUid", android.os.Process.myUid());
        } finally {
            process.destroyForcibly();
            process.getInputStream().close(); process.getErrorStream().close();
        }
    }
}
