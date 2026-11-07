package com.ai.codex;
import android.content.Context;
import android.os.Binder;
import org.json.JSONObject;

/** Shizuku's generic device channel has exactly the same argv gate as Root/app/ADB. */
public final class DeviceShellService extends IDeviceShell.Stub {
    private final Context context;
    private final int clientUid;
    public DeviceShellService(Context context){this.context=context;clientUid=context.getApplicationInfo().uid;}
    private void authenticate(){
        if(Binder.getCallingUid()!=clientUid||clientUid<10000||(android.os.Process.myUid()!=0&&android.os.Process.myUid()!=2000))throw new SecurityException();
    }
    @Override public String execute(String request){
        authenticate();
        try{
            if(request==null||request.length()>32768)throw new DeviceCommandPolicy.Blocked("invalid_request");
            return CodexDeviceCommands.executeLocal(context,new JSONObject(request),"shizuku").toString();
        }catch(Exception failure){return "{\"ok\":false,\"error\":\"[POLICY_BLOCKED] shizuku_request_unavailable\"}";}
    }
    @Override public int uid(){authenticate();return android.os.Process.myUid();}
    @Override public void destroy(){int caller=Binder.getCallingUid();if(caller!=clientUid&&caller!=0&&caller!=2000)throw new SecurityException();android.os.Process.killProcess(android.os.Process.myPid());}
}
