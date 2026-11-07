package com.ai.codex;
import android.content.Context;
import android.os.Looper;
import java.io.File;

/** Fixed installed-APK identity for app_process. Inspired by DSHA PrivilegedPackageContext. */
public final class CodexPrivilegedContext {
    private CodexPrivilegedContext() {}
    public static Context installed(int expectedUid) throws Exception {
        int uid=android.os.Process.myUid();
        if (uid!=0 && uid!=2000) throw new SecurityException("privileged_uid_required");
        if (expectedUid<10000 || expectedUid/100000!=0) throw new SecurityException("owner_uid_invalid");
        if (Looper.getMainLooper()==null) Looper.prepareMainLooper();
        Class<?> thread=Class.forName("android.app.ActivityThread");
        Object current=thread.getMethod("currentActivityThread").invoke(null);
        if (current==null) current=thread.getMethod("systemMain").invoke(null);
        Context system=(Context)thread.getMethod("getSystemContext").invoke(current);
        Context app=system.createPackageContext("com.ai.codex",Context.CONTEXT_IGNORE_SECURITY);
        android.content.pm.ApplicationInfo info=app.getPackageManager().getApplicationInfo("com.ai.codex",0);
        String source=new File(info.sourceDir).getCanonicalPath();
        if (info.uid!=expectedUid || !source.equals(info.sourceDir) || !source.startsWith("/data/app/")
                || !source.equals(System.getProperty("java.class.path")))
            throw new SecurityException("installed_apk_identity_mismatch");
        return app;
    }
}
