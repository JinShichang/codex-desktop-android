package com.ai.codex;
import android.content.Context;
import android.os.IBinder;
import android.os.Looper;
import android.os.PowerManager;
import java.io.File;
import java.lang.reflect.Method;

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

    static void requireInteractive(Context app) {
        PowerManager power = app.getSystemService(PowerManager.class);
        if (power == null || !power.isInteractive())
            throw new DeviceCommandPolicy.Blocked("device_locked_or_asleep");

        boolean locked;
        try {
            // Standalone app_process does not receive the shared memory a normal app gets at bind.
            // Use the same Binder queries as KeyguardManager without initializing WindowManagerGlobal.
            Class<?> window = Class.forName("android.view.IWindowManager");
            locked = (boolean) window.getMethod("isKeyguardLocked").invoke(service("window", window))
                || isDeviceLocked(app.getApplicationInfo().uid / 100000);
        } catch (ReflectiveOperationException | RuntimeException unavailable) {
            throw new DeviceCommandPolicy.Blocked("device_lock_state_unavailable");
        }
        if (locked) throw new DeviceCommandPolicy.Blocked("device_locked_or_asleep");
    }

    private static boolean isDeviceLocked(int userId) throws ReflectiveOperationException {
        Class<?> trust = Class.forName("android.app.trust.ITrustManager");
        Object manager = service("trust", trust);
        Method query;
        try {
            query = trust.getMethod("isDeviceLocked", int.class, int.class);
        } catch (NoSuchMethodException olderAndroid) {
            return (boolean) trust.getMethod("isDeviceLocked", int.class).invoke(manager, userId);
        }
        return (boolean) query.invoke(manager, userId, 0); // Default physical device.
    }

    private static Object service(String name, Class<?> type) throws ReflectiveOperationException {
        IBinder binder = (IBinder) Class.forName("android.os.ServiceManager").getMethod("getService", String.class)
            .invoke(null, name);
        if (binder == null) throw new IllegalStateException("system_service_unavailable");
        return Class.forName(type.getName() + "$Stub").getMethod("asInterface", IBinder.class).invoke(null, binder);
    }
}
