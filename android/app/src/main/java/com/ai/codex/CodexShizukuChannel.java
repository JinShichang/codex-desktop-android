package com.ai.codex;
import android.content.ComponentName;
import android.content.Context;
import android.content.ServiceConnection;
import android.content.pm.PackageManager;
import android.os.IBinder;
import rikka.shizuku.Shizuku;
import org.json.JSONObject;

/** Binding is only initiated by the native panel; a model cannot request or enable it. */
public final class CodexShizukuChannel {
    private static volatile IDeviceShell remote;
    private static Shizuku.UserServiceArgs service;
    private static final ServiceConnection CONNECTION=new ServiceConnection(){
        public void onServiceConnected(ComponentName name,IBinder binder){remote=IDeviceShell.Stub.asInterface(binder);}
        public void onServiceDisconnected(ComponentName name){remote=null;}
    };
    private CodexShizukuChannel(){}
    public static boolean connected(){return remote!=null&&remote.asBinder().isBinderAlive();}
    public static void authorize(Context c){
        if(!Shizuku.pingBinder())throw new IllegalStateException("shizuku_not_running");
        if(Shizuku.checkSelfPermission()!=PackageManager.PERMISSION_GRANTED){Shizuku.requestPermission(85);return;}
        service=new Shizuku.UserServiceArgs(new ComponentName(c,DeviceShellService.class)).daemon(false).processNameSuffix("device_shell").tag("codex-device-shell").version(1);
        Shizuku.bindUserService(service,CONNECTION);
        c.getSharedPreferences(CodexDeviceFeatures.PREFS,0).edit().putBoolean("shizuku",true).apply();
    }
    public static void close(Context c){
        c.getSharedPreferences(CodexDeviceFeatures.PREFS,0).edit().putBoolean("shizuku",false).apply();
        if(service!=null)try{Shizuku.unbindUserService(service,CONNECTION,true);}catch(Exception ignored){}
        remote=null;service=null;
    }
    public static JSONObject execute(Context c,JSONObject args)throws Exception{
        CodexDeviceFeatures.require(c,"shizuku");
        IDeviceShell target=remote;
        if(target==null||!Shizuku.pingBinder()||Shizuku.checkSelfPermission()!=PackageManager.PERMISSION_GRANTED)
            throw new DeviceCommandPolicy.Blocked("shizuku_not_authorized_or_connected");
        return new JSONObject(target.execute(args.toString()));
    }
}
