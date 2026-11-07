package com.ai.codex;
public final class RootEntryCheck {
    private static android.content.Context context(String path,int uid){return new android.content.Context(){public android.content.pm.ApplicationInfo getApplicationInfo(){android.content.pm.ApplicationInfo info=new android.content.pm.ApplicationInfo();info.uid=uid;info.sourceDir=path;return info;}};}
    private static void blocked(String path,int uid,String name)throws Exception{try{CodexRootChannel.entry(context(path,uid),name);throw new AssertionError();}catch(DeviceCommandPolicy.Blocked expected){}}
    public static void main(String[] unused)throws Exception{
        String path="/data/app/~~current/com.ai.codex-abcd==/base.apk",main="com.ai.codex.CodexRootCommandMain";
        String entry=CodexRootChannel.entry(context(path,10265),main);
        if(!entry.equals("CLASSPATH='"+path+"' /system/bin/app_process /system/bin "+main+" 10265"))throw new AssertionError();
        blocked("/sdcard/base.apk",10265,main);blocked("/data/com/ai/codex/../base.apk",10265,main);blocked("/data/app/a' ; reboot/base.apk",10265,main);
        blocked(path,0,main);blocked(path,2000,main);blocked(path,110265,main);blocked(path,10265,"arbitrary.Main");blocked(path,10265,main+" ; reboot");
        CodexRootChannel.beginAuthorization();CodexRootChannel.beginAuthorization();CodexRootChannel.endAuthorization();if(!CodexRootChannel.isAuthorizationPending())throw new AssertionError();CodexRootChannel.endAuthorization();if(CodexRootChannel.isAuthorizationPending())throw new AssertionError();
        System.out.println("Root entry checks passed: fixed APK/class/owner, injection/path rejection, concurrent authorization guard");
    }
}
