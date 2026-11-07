package com.ai.codex;

import android.content.Context;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.concurrent.*;

/** Loopback-only bridge. All device actions share the Unix/MCP execution boundary. */
public final class CodexDeviceHttp {
    public interface Handler { JSONObject call(String op,JSONObject args) throws Exception; }
    private static final String OPERATIONS="device_command install_apk package_info sensor_list sensor_read location flashlight clipboard_read clipboard_write file_list file_read file_export interaction_notify interaction_toast interaction_vibrate interaction_ask interaction_answer interaction_share interaction_open status request_access sms_status sms_search sms_read";
    private static String token;
    private static boolean started;
    private CodexDeviceHttp(){}
    public static synchronized String token(Context c)throws Exception {
        if(token!=null)return token;
        File path=new File(c.getNoBackupFilesDir(),"device-bridge-token");
        if(path.exists()){
            if(java.nio.file.Files.isSymbolicLink(path.toPath())||path.length()!=64)throw new IOException("invalid_device_bridge_token");
            token=java.nio.file.Files.readString(path.toPath(),StandardCharsets.US_ASCII);
            if(!token.matches("[0-9a-f]{64}"))throw new IOException("invalid_device_bridge_token");
        }else{
            byte[] random=new byte[32];new java.security.SecureRandom().nextBytes(random);StringBuilder hex=new StringBuilder();
            for(byte value:random)hex.append(String.format(java.util.Locale.ROOT,"%02x",value&255));
            android.util.AtomicFile file=new android.util.AtomicFile(path);FileOutputStream output=file.startWrite();
            try{output.write(hex.toString().getBytes(StandardCharsets.US_ASCII));file.finishWrite(output);}catch(Exception error){file.failWrite(output);throw error;}
            android.system.Os.chmod(path.getPath(),0600);token=hex.toString();
        }return token;
    }
    public static synchronized void start(Context c,Handler handler)throws Exception{
        if(started)return;
        String secret=token(c);
        ServerSocket server=new ServerSocket();server.setReuseAddress(false);server.bind(new InetSocketAddress(InetAddress.getByName("127.0.0.1"),3090),8);
        ThreadPoolExecutor workers=new ThreadPoolExecutor(2,2,0,TimeUnit.SECONDS,new ArrayBlockingQueue<>(8),r->{Thread t=new Thread(r,"Codex-device-http");t.setDaemon(true);return t;});
        Thread accept=new Thread(()->{
            while(!server.isClosed())try{
                Socket client=server.accept();client.setSoTimeout(5000);
                try{workers.execute(()->serve(client,secret,handler));}catch(RejectedExecutionException busy){client.close();}
            }catch(IOException stopped){break;}
        },"Codex-device-bridge");accept.setDaemon(true);accept.start();started=true;
    }
    private static String line(InputStream input,int limit)throws Exception{
        ByteArrayOutputStream data=new ByteArrayOutputStream();
        for(int i=0;i<limit;i++){int value=input.read();if(value<0)throw new IOException();if(value==10){String text=data.toString(StandardCharsets.US_ASCII.name());if(!text.endsWith("\r"))throw new IOException();return text.substring(0,text.length()-1);}data.write(value);}
        throw new IOException();
    }
    private static void serve(Socket socket,String secret,Handler handler){
        try(Socket client=socket){
            InputStream input=new BufferedInputStream(client.getInputStream());String[] request=line(input,2048).split(" ");
            if(request.length!=3||!request[2].equals("HTTP/1.1")){reply(client,400,new JSONObject().put("ok",false));return;}
            String auth=null;int length=0,headers=0;boolean duplicate=false;
            for(int count=0;count<40;count++){
                String header=line(input,2048);headers+=header.length();if(headers>8192)throw new IOException();if(header.isEmpty())break;
                int colon=header.indexOf(':');if(colon<=0)throw new IOException();String key=header.substring(0,colon).toLowerCase(java.util.Locale.ROOT),value=header.substring(colon+1).trim();
                if(key.equals("authorization")){if(auth!=null)duplicate=true;auth=value;}
                if(key.equals("transfer-encoding"))throw new IOException();
                if(key.equals("content-length")){if(length!=0)throw new IOException();length=Integer.parseInt(value);if(length<0||length>32768)throw new IOException();}
                if(count==39)throw new IOException();
            }
            if(duplicate||auth==null||!MessageDigest.isEqual(auth.getBytes(StandardCharsets.US_ASCII),("Bearer "+secret).getBytes(StandardCharsets.US_ASCII))){reply(client,401,new JSONObject().put("ok",false).put("error","authentication_required"));return;}
            JSONObject result;
            if(request[0].equals("GET")&&request[1].equals("/app/help")){
                result=new JSONObject().put("ok",true).put("transport","loopback-http-v1").put("status","GET /app/status")
                    .put("call","POST /app/call {op,args}").put("authorization","Bearer token from android-bridge.json")
                    .put("operations",new JSONArray(java.util.Arrays.asList(OPERATIONS.split(" "))));
            }else if(request[0].equals("GET")&&request[1].equals("/app/status"))result=handler.call("status",new JSONObject());
            else if(request[0].equals("POST")&&request[1].equals("/app/call")&&length>0){
                byte[] data=input.readNBytes(length);if(data.length!=length)throw new IOException();JSONObject payload=new JSONObject(new String(data,StandardCharsets.UTF_8));
                if(payload.length()>2||!payload.has("op")||payload.has("args")&&!(payload.opt("args") instanceof JSONObject))throw new IOException();
                result=handler.call(payload.getString("op"),payload.optJSONObject("args"));
            }else{reply(client,404,new JSONObject().put("ok",false).put("error","unknown_endpoint"));return;}
            reply(client,200,result);
        }catch(Exception failure){/* Never log request bodies or tokens. */}
    }
    private static void reply(Socket client,int status,JSONObject result)throws IOException{
        byte[] body=result.toString().getBytes(StandardCharsets.UTF_8);
        String header="HTTP/1.1 "+status+" "+(status==200?"OK":"Error")+"\r\nContent-Type: application/json; charset=utf-8\r\nCache-Control: no-store\r\nConnection: close\r\nContent-Length: "+body.length+"\r\n\r\n";
        client.getOutputStream().write(header.getBytes(StandardCharsets.US_ASCII));client.getOutputStream().write(body);client.getOutputStream().flush();
    }
}
