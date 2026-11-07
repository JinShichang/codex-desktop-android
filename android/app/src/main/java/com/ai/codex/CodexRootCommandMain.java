package com.ai.codex;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;

/** One bounded request per privileged process. No arbitrary shell, class or script selection. */
public final class CodexRootCommandMain {
    public static void main(String[] args) {
        Thread deadline = startDeadline(20);
        String stage="root_uid";
        try {
            if (android.os.Process.myUid()!=0 || args.length!=1) throw new SecurityException();
            stage="installed_context";
            android.content.Context context=CodexPrivilegedContext.installed(Integer.parseInt(args[0]));
            stage="request_framing";
            ByteArrayOutputStream bytes=new ByteArrayOutputStream(); boolean framed=false;
            for (int i=0;i<32768;i++) { int value=System.in.read(); if (value<0) break;
                if (value==10) { framed=true; break; } bytes.write(value); }
            if (!framed) throw new IllegalArgumentException();
            JSONObject request=new JSONObject(bytes.toString(StandardCharsets.UTF_8.name()));
            stage="policy_and_execution";
            if (CodexDeviceCommands.parse(request).fileCommand()) {
                deadline.interrupt();
                startDeadline(DeviceCommandPolicy.FILE_COMMAND_TIMEOUT_SECONDS + 5);
            }
            JSONObject result=CodexDeviceCommands.executeLocal(context,request,"root");
            System.out.println(result.toString());
        } catch (Throwable failure) {
            try{System.out.println(new JSONObject().put("ok",false).put("error","[POLICY_BLOCKED] root_entry_unverified").put("stage",stage).put("failureClass",failure.getClass().getSimpleName()).put("exitCode",126).toString());}catch(Exception ignored){}
        }
        System.exit(0);
    }

    private static Thread startDeadline(int seconds) {
        Thread deadline = new Thread(() -> {
            try { Thread.sleep(seconds * 1000L); } catch (InterruptedException cancelled) { return; }
            System.exit(124);
        }, "Root-command-deadline");
        deadline.setDaemon(true);
        deadline.start();
        return deadline;
    }
}
