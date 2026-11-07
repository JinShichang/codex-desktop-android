package com.ai.codex;
import java.net.*;import java.io.*;import java.nio.charset.StandardCharsets;import org.json.JSONObject;
public final class DeviceHttpCheck {
    private static int calls;
    private static String send(String request)throws Exception{
        try(ServerSocket server=new ServerSocket(0,1,InetAddress.getLoopbackAddress())){
            java.lang.reflect.Method method=CodexDeviceHttp.class.getDeclaredMethod("serve",Socket.class,String.class,CodexDeviceHttp.Handler.class);method.setAccessible(true);
            CodexDeviceHttp.Handler handler=(op,args)->{calls++;return new JSONObject().put("ok",true).put("op",op);};
            Thread thread=new Thread(()->{try{method.invoke(null,server.accept(),"test-secret",handler);}catch(Exception error){throw new RuntimeException(error);}});thread.start();
            String reply;
            try(Socket client=new Socket(InetAddress.getLoopbackAddress(),server.getLocalPort())){
                client.setSoTimeout(3000);client.getOutputStream().write(request.getBytes(StandardCharsets.UTF_8));client.shutdownOutput();reply=new String(client.getInputStream().readAllBytes(),StandardCharsets.UTF_8);
            }
            thread.join(3000);if(thread.isAlive())throw new AssertionError("HTTP did not close");return reply;
        }
    }
    private static void noDispatch(String request)throws Exception{int before=calls;send(request);if(calls!=before)throw new AssertionError("Unauthorized dispatch");}
    public static void main(String[] unused)throws Exception{
        String auth="Authorization: Bearer test-secret\r\n";
        if(!send("GET /app/status HTTP/1.1\r\n\r\n").startsWith("HTTP/1.1 401"))throw new AssertionError();
        noDispatch("GET /app/status HTTP/1.1\r\nAuthorization: Bearer wrong\r\n\r\n");
        noDispatch("GET /app/status HTTP/1.1\r\n"+auth+auth+"\r\n");
        noDispatch("POST /app/call HTTP/1.1\r\n"+auth+"Transfer-Encoding: chunked\r\n\r\n0\r\n\r\n");
        noDispatch("POST /app/call HTTP/1.1\r\n"+auth+"Content-Length: 32769\r\n\r\n");
        noDispatch("POST /app/call HTTP/1.1\r\n"+auth+"Content-Length: 100\r\n\r\n{}");
        if(!send("GET /app/help HTTP/1.1\r\n"+auth+"\r\n").contains("loopback-http-v1"))throw new AssertionError();
        if(calls!=0)throw new AssertionError();
        if(!send("GET /app/status HTTP/1.1\r\n"+auth+"\r\n").contains("\"op\":\"status\""))throw new AssertionError();
        String body="{\"op\":\"device_command\",\"args\":{\"argv\":[\"id\"]}}";
        if(!send("POST /app/call HTTP/1.1\r\n"+auth+"Content-Length: "+body.getBytes(StandardCharsets.UTF_8).length+"\r\n\r\n"+body).contains("device_command"))throw new AssertionError();
        if(calls!=2)throw new AssertionError();
        System.out.println("HTTP boundary checks passed: missing/wrong/duplicate token, chunked input, size/truncation, help/status/call");
    }
}
