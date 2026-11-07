package com.ai.codex;
import java.util.Arrays;
public final class DevicePolicyCheck {
    private static int checks;
    private static void allow(String... args){checks++;DeviceCommandPolicy.Plan p=DeviceCommandPolicy.inspect(Arrays.asList(args));if(!p.argv.get(0).startsWith("/system/bin/"))throw new AssertionError();}
    private static void deny(String... args){checks++;try{DeviceCommandPolicy.inspect(Arrays.asList(args));throw new AssertionError(Arrays.toString(args));}catch(DeviceCommandPolicy.Blocked blocked){if(!blocked.getMessage().startsWith("[POLICY_BLOCKED]"))throw new AssertionError();}}
    private static void stopDeny(String target,int uid,int flags){checks++;try{DeviceCommandPolicy.requireStoppable(target,"com.ai.codex",uid,10265,flags);throw new AssertionError();}catch(DeviceCommandPolicy.Blocked expected){}}
    public static void main(String[] unused)throws Exception{
        allow("id");allow("/system/bin/id","-u");allow("getprop","ro.product.model");allow("settings","get","secure","android_id");allow("dumpsys","activity","activities");allow("am","force-stop","org.example.userapp");
        for(String name:new String[]{"su","sh","bash","env","toybox","busybox","python","app_process","dd","mkfs.ext4","parted","setenforce","setprop","mount","reboot","rm","chmod","kill","killall","pkill"})deny(name);
        deny("id;reboot");deny("id",";","reboot");deny("id","$(reboot)");deny("id","`reboot`");deny("id","x\nreboot");deny("/data/local/tmp/id");deny("/system/bin/../bin/id");deny("/system/bin//id");deny("/system/bin/id","--unknown");
        deny("settings","put","global","foo","1");deny("dumpsys","battery","reset");deny("pm","install","/sdcard/test.apk");deny("pm","clear","org.example.userapp");deny("am","force-stop","*");deny("getprop","a b");deny("getprop","ro.foo","extra");deny("id","a\0b");deny("id",null);deny();
        for(String channel:new String[]{"root","adb","shizuku","APP","app ",""}){checks++;try{DeviceCommandPolicy.requireAppChannel(channel);throw new AssertionError();}catch(DeviceCommandPolicy.Blocked expected){}}
        DeviceCommandPolicy.requireAppChannel("app");
        stopDeny("com.ai.codex",10265,0);stopDeny("org.example.system",1000,0);stopDeny("org.example.system",10100,1);stopDeny("org.example.updated",10100,128);stopDeny("org.example.shared",10265,0);stopDeny("org.example.otheruser",110000,0);
        stopDeny("me.weishu.kernelsu",10266,0);stopDeny("me.bmax.apatch",10267,0);
        DeviceCommandPolicy.requireStoppable("org.example.userapp","com.ai.codex",10266,10265,0);
        for(String path:new String[]{"/sdcard/.ssh/id_rsa","/sdcard/a/.android/adbkey","/sdcard/.dsh/auth","/sdcard/.codex/auth.json","/sdcard/a/../secret","/sdcard/.pki/key"}){checks++;try{DeviceFilePolicy.checkComponents(path);throw new AssertionError();}catch(DeviceCommandPolicy.Blocked expected){}}
        DeviceCommandPolicy.requireLaunchable("com.android.chrome","com.ai.codex");
        for(String pkg:new String[]{"com.ai.codex","com.android.settings","me.weishu.kernelsu","me.bmax.apatch","com.google.android.permissioncontroller"}){checks++;try{DeviceCommandPolicy.requireLaunchable(pkg,"com.ai.codex");throw new AssertionError();}catch(DeviceCommandPolicy.Blocked expected){}}
        deny("getprop","--set");
        System.out.println("Device policy checks passed: "+checks);
    }
}
