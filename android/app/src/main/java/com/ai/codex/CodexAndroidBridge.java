package com.ai.codex;

import android.app.KeyguardManager;
import android.content.Context;
import android.net.LocalServerSocket;
import android.net.LocalSocket;
import android.os.PowerManager;
import android.system.Os;
import android.system.OsConstants;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/** App-private Android tools. Same UID authentication is not isolation from guest processes. */
public final class CodexAndroidBridge {
    private static CodexAndroidBridge instance;
    private final Context context;
    private LocalServerSocket server;
    private CodexAndroidBridge(Context context) { this.context = context.getApplicationContext(); }
    public static synchronized void start(Context context) {
        if (instance != null) return;
        CodexAndroidBridge created = new CodexAndroidBridge(context);
        try {
            created.server = new LocalServerSocket("codex-android-" + android.os.Process.myUid());
            Os.fcntlInt(created.server.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
            instance = created;
            new Thread(created::serve, "Codex-Android-tools").start();
            try { CodexDeviceHttp.start(context, created::call); }
            catch (Exception unavailable) { android.util.Log.w("Codex-Android", "Loopback device endpoint unavailable"); }
        } catch (Exception error) {
            android.util.Log.e("Codex-Android", "Android tool endpoint unavailable");
        }
    }
    private void serve() {
        while (true) {
            try (LocalSocket socket = server.accept()) {
                Os.fcntlInt(socket.getFileDescriptor(), OsConstants.F_SETFD, OsConstants.FD_CLOEXEC);
                if (socket.getPeerCredentials().getUid() != android.os.Process.myUid()) continue;
                socket.setSoTimeout(15000);
                ByteArrayOutputStream input = new ByteArrayOutputStream();
                boolean complete = false;
                for (int i = 0; i < 32768; i++) {
                    int value = socket.getInputStream().read();
                    if (value == -1) break;
                    if (value == '\n') { complete = true; break; }
                    input.write(value);
                }
                JSONObject reply;
                try {
                    if (!complete) throw new IllegalArgumentException("request_size_or_framing");
                    JSONObject request = new JSONObject(new String(input.toByteArray(), StandardCharsets.UTF_8));
                    if (request.getInt("version") != 1) throw new IllegalArgumentException("unsupported_version");
                    JSONObject result = dispatch(request.getString("op"), request.optJSONObject("args"));
                    reply = new JSONObject().put("ok", result.optBoolean("ok", true)).put("result", result);
                    if (!result.optBoolean("ok",true)) reply.put("error", result.optString("error","android_operation_failed"));
                } catch (DeviceCommandPolicy.Blocked blocked) {
                    reply = new JSONObject().put("ok", false).put("error", blocked.getMessage());
                } catch (SecurityException error) {
                    reply = new JSONObject().put("ok", false).put("error", "permission_required");
                } catch (Exception error) {
                    // Only explicitly bounded error codes, never raw platform exceptions/data.
                    String code = error.getMessage();
                    if (code == null || !code.matches("[a-z][a-z0-9_]{0,79}")) code = "android_operation_failed";
                    reply = new JSONObject().put("ok", false).put("error", code);
                }
                socket.getOutputStream().write((reply.toString() + "\n").getBytes(StandardCharsets.UTF_8));
            } catch (Exception error) {
                android.util.Log.w("Codex-Android", "Android tool connection ended");
            }
        }
    }
    private JSONObject call(String op, JSONObject args) throws Exception {
        try { return dispatch(op,args); }
        catch (DeviceCommandPolicy.Blocked blocked) { return new JSONObject().put("ok",false).put("error",blocked.getMessage()); }
        catch (SecurityException permission) { return new JSONObject().put("ok",false).put("error","permission_required"); }
        catch (Exception failure) { return new JSONObject().put("ok",false).put("error","android_operation_failed"); }
    }
    private JSONObject dispatch(String op, JSONObject args) throws Exception {
        if (args == null) args = new JSONObject();
        if ("status".equals(op)) return new JSONObject()
            .put("schema", "codex.android.v1").put("androidUid", android.os.Process.myUid())
            .put("globalControlEnabled", com.ai.codex.phone.a11y.PhoneA11yService.Companion.isConnected())
            .put("computer", new JSONObject(com.ai.codex.phone.PhoneControl.get(context).status())).put("sms", CodexDeviceFeatures.smsStatus(context))
            .put("permissionRequests", CodexAndroidPermissionActivity.status())
            .put("deviceCommands", CodexDeviceCommands.status()).put("capabilities", CodexDeviceFeatures.status(context))
            .put("device", new JSONObject().put("manufacturer", android.os.Build.MANUFACTURER)
                .put("model", android.os.Build.MODEL).put("soc", android.os.Build.SOC_MODEL)
                .put("android", android.os.Build.VERSION.RELEASE).put("api", android.os.Build.VERSION.SDK_INT));
        KeyguardManager keyguard = context.getSystemService(KeyguardManager.class);
        PowerManager power = context.getSystemService(PowerManager.class);
        if (keyguard == null || keyguard.isDeviceLocked() || keyguard.isKeyguardLocked()
                || power == null || !power.isInteractive()) throw new IllegalStateException("device_locked_or_asleep");
        if (CodexDeviceFeatures.handles(op)) return CodexDeviceFeatures.execute(context,op,args);
        if ("device_command".equals(op)) return CodexDeviceCommands.execute(context, args);
        if ("request_access".equals(op)) {
            if (args.length() != 1 || !(args.opt("scope") instanceof String))
                throw new IllegalArgumentException("invalid_arguments");
            if ("sms_send".equals(args.getString("scope"))) throw new DeviceCommandPolicy.Blocked("sms_read_only");
            return CodexAndroidPermissionActivity.request(context, args.getString("scope"));
        }
        if (op.startsWith("sms_")) {
            if ("sms_status".equals(op)) return CodexDeviceFeatures.smsStatus(context);
            if (!"sms_search".equals(op) && !"sms_read".equals(op))
                throw new DeviceCommandPolicy.Blocked("sms_read_only");
            CodexDeviceFeatures.require(context,"sms_read");
            JSONObject messages = CodexSmsTools.execute(context, op, args);
            CodexDeviceFeatures.require(context,"sms_read");
            if(context.checkSelfPermission(android.Manifest.permission.READ_SMS)!=android.content.pm.PackageManager.PERMISSION_GRANTED)throw new SecurityException();
            return messages;
        }
        if ("apps".equals(op)) {
            android.content.Intent intent = new android.content.Intent(android.content.Intent.ACTION_MAIN)
                    .addCategory(android.content.Intent.CATEGORY_LAUNCHER);
            org.json.JSONArray apps = new org.json.JSONArray();
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (android.content.pm.ResolveInfo info : context.getPackageManager().queryIntentActivities(intent, 0)) {
                if (info.activityInfo != null && seen.add(info.activityInfo.packageName))
                    apps.put(new JSONObject().put("packageName", info.activityInfo.packageName)
                        .put("label", info.loadLabel(context.getPackageManager()).toString()));
            }
            return new JSONObject().put("apps", apps);
        }
        throw new IllegalArgumentException("Use the phone MCP for screen operations");
    }
}
