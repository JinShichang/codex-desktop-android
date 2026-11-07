package com.ai.codex;
import android.content.Context;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/** Root is opt-in. su sees only a fixed installed app_process launcher. */
public final class CodexRootChannel {
    private static final java.util.concurrent.atomic.AtomicInteger authorizing=new java.util.concurrent.atomic.AtomicInteger();
    public static boolean isAuthorizationPending(){return authorizing.get()>0;}
    static void beginAuthorization(){authorizing.incrementAndGet();}
    static void endAuthorization(){authorizing.decrementAndGet();}
    private CodexRootChannel() {}
    static String su() {
        for (String candidate:new String[]{"/system/bin/su","/system/xbin/su","/sbin/su","/debug_ramdisk/su"})
            if (new java.io.File(candidate).canExecute()) return candidate;
        return "su";
    }
    static String entry(Context c,String main) throws Exception {
        if(c.getApplicationInfo().uid<10000||c.getApplicationInfo().uid/100000!=0)throw new DeviceCommandPolicy.Blocked("owner_uid_invalid");
        String apk=c.getApplicationInfo().sourceDir;
        if (!apk.equals(new java.io.File(apk).getCanonicalPath()) || !apk.matches("/data/app/[A-Za-z0-9_./=+~\\-]+\\.apk"))
            throw new DeviceCommandPolicy.Blocked("installed_apk_unverified");
        if (!main.equals("com.ai.codex.CodexRootCommandMain"))
            throw new DeviceCommandPolicy.Blocked("root_entry_not_allowed");
        return "CLASSPATH='"+apk+"' /system/bin/app_process /system/bin "+main+" "+c.getApplicationInfo().uid;
    }
    public static JSONObject execute(Context c,JSONObject request) throws Exception {
        CodexDeviceFeatures.require(c,"root");
        return invoke(c,request);
    }
    /** Only the native panel calls probe; no model method enables Root. */
    public static JSONObject probe(Context c) throws Exception {
        return invoke(c,new JSONObject().put("argv",new org.json.JSONArray().put("id").put("-u")).put("channel","root"));
    }
    private static JSONObject invoke(Context c,JSONObject request) throws Exception {
        beginAuthorization();
        try { return invokeOwned(c,request); } finally { endAuthorization(); }
    }
    private static JSONObject invokeOwned(Context c,JSONObject request) throws Exception {
        Process process=new ProcessBuilder(su(),"-c",entry(c,"com.ai.codex.CodexRootCommandMain")).redirectErrorStream(true).start();
        ByteArrayOutputStream bytes=new ByteArrayOutputStream();
        Thread reader=new Thread(()->{
            try (java.io.InputStream input=process.getInputStream()) {
                byte[] buffer=new byte[4096]; int count;
                while ((count=input.read(buffer))!=-1) {
                    if (bytes.size()+count>262144) { process.destroyForcibly(); break; }
                    bytes.write(buffer,0,count);
                }
            } catch (Exception ignored) {}
        },"Codex-root-result"); reader.setDaemon(true); reader.start();
        try {
            byte[] data=(request.toString()+"\n").getBytes(StandardCharsets.UTF_8);
            if (data.length>32768) throw new DeviceCommandPolicy.Blocked("request_too_large");
            process.getOutputStream().write(data); process.getOutputStream().close();
            if (!process.waitFor(30,TimeUnit.SECONDS))
                return new JSONObject().put("ok",false).put("error","root_result_unknown").put("retrySafe",false);
            reader.join(1000);
            if (reader.isAlive()) throw new IllegalStateException("root_result_unknown");
            String[] lines=bytes.toString(StandardCharsets.UTF_8.name()).trim().split("\\r?\\n");
            if (lines.length==0) throw new IllegalStateException("root_denied_or_unavailable");
            JSONObject result=new JSONObject(lines[lines.length-1]);
            if (!result.has("ok")) throw new IllegalStateException("root_invalid_result");
            return result;
        } finally { process.destroyForcibly(); process.getInputStream().close(); process.getErrorStream().close(); }
    }
}
