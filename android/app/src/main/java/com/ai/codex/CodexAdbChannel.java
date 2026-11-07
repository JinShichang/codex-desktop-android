package com.ai.codex;

import android.content.Context;
import android.os.Build;
import android.security.keystore.KeyGenParameterSpec;
import android.security.keystore.KeyProperties;
import io.github.muntashirakon.adb.AbsAdbConnectionManager;
import io.github.muntashirakon.adb.AdbStream;
import java.io.*;
import java.nio.charset.StandardCharsets;
import java.security.*;
import java.security.cert.Certificate;
import java.security.spec.PKCS8EncodedKeySpec;
import javax.crypto.Cipher;
import javax.crypto.KeyGenerator;
import javax.crypto.SecretKey;
import javax.crypto.spec.GCMParameterSpec;
import org.bouncycastle.asn1.x500.X500Name;
import org.bouncycastle.cert.jcajce.JcaX509v3CertificateBuilder;
import org.bouncycastle.cert.jcajce.JcaX509CertificateConverter;
import org.bouncycastle.operator.jcajce.JcaContentSignerBuilder;
import org.json.JSONObject;
import java.util.concurrent.*;

/** On-phone TLS/SPAKE2 ADB. Private key is encrypted by an installation-local Keystore key. */
public final class CodexAdbChannel extends AbsAdbConnectionManager {
    private static CodexAdbChannel instance;
    private static final String ALIAS="codex.device.adb.wrap.v1";
    private final PrivateKey privateKey;
    private final Certificate certificate;
    private CodexAdbChannel(Context c)throws Exception{
        setApi(Build.VERSION.SDK_INT);setTimeout(5,TimeUnit.SECONDS);setThrowOnUnauthorised(true);
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);
        if(!store.containsAlias(ALIAS)){
            KeyGenerator generator=KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore");
            generator.init(new KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT|KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build());generator.generateKey();
        }
        SecretKey wrapping=(SecretKey)store.getKey(ALIAS,null);
        File key=new File(c.getNoBackupFilesDir(),"device-adb-key.gcm"),cert=new File(c.getNoBackupFilesDir(),"device-adb-cert.der");
        if(key.isFile()&&cert.isFile()){
            byte[] data=java.nio.file.Files.readAllBytes(key.toPath());if(data.length<13||data.length>8192||java.nio.file.Files.isSymbolicLink(key.toPath()))throw new IOException("adb_key_unavailable");
            Cipher decrypt=Cipher.getInstance("AES/GCM/NoPadding");decrypt.init(Cipher.DECRYPT_MODE,wrapping,new GCMParameterSpec(128,data,0,12));
            privateKey=KeyFactory.getInstance("RSA").generatePrivate(new PKCS8EncodedKeySpec(decrypt.doFinal(data,12,data.length-12)));
            try(InputStream input=new FileInputStream(cert)){certificate=java.security.cert.CertificateFactory.getInstance("X.509").generateCertificate(input);}
        }else{
            KeyPairGenerator generator=KeyPairGenerator.getInstance("RSA");generator.initialize(2048);java.security.KeyPair pair=generator.generateKeyPair();privateKey=pair.getPrivate();
            X500Name subject=new X500Name("CN=Codex Android ADB");long now=System.currentTimeMillis();
            certificate=new JcaX509CertificateConverter().getCertificate(new JcaX509v3CertificateBuilder(subject,new java.math.BigInteger(128,new SecureRandom()),new java.util.Date(now-86400000),new java.util.Date(now+315360000000L),subject,pair.getPublic()).build(new JcaContentSignerBuilder("SHA256withRSA").build(privateKey)));
            Cipher encrypt=Cipher.getInstance("AES/GCM/NoPadding");encrypt.init(Cipher.ENCRYPT_MODE,wrapping);ByteArrayOutputStream data=new ByteArrayOutputStream();data.write(encrypt.getIV());data.write(encrypt.doFinal(privateKey.getEncoded()));
            atomic(key,data.toByteArray());atomic(cert,certificate.getEncoded());
        }
    }
    private static void atomic(File path,byte[] bytes)throws Exception{
        android.util.AtomicFile file=new android.util.AtomicFile(path);FileOutputStream output=file.startWrite();
        try{output.write(bytes);file.finishWrite(output);}catch(Exception failure){file.failWrite(output);throw failure;}android.system.Os.chmod(path.getPath(),0600);
    }
    private static void resetTlsCache()throws Exception{
        Class<?> type=Class.forName("io.github.muntashirakon.adb.SslUtils");java.lang.reflect.Field cache=type.getDeclaredField("sslContext");cache.setAccessible(true);cache.set(null,null);
    }
    public static synchronized CodexAdbChannel get(Context c)throws Exception{if(instance==null){resetTlsCache();instance=new CodexAdbChannel(c);}return instance;}
    @Override protected PrivateKey getPrivateKey(){return privateKey;}
    @Override protected Certificate getCertificate(){return certificate;}
    @Override protected String getDeviceName(){return "Codex Android";}
    public static void requireLocal(String host)throws Exception{
        java.net.InetAddress address=java.net.InetAddress.getByName(host);
        if(address.isLoopbackAddress())return;
        java.util.Enumeration<java.net.NetworkInterface> interfaces=java.net.NetworkInterface.getNetworkInterfaces();
        while(interfaces.hasMoreElements()){java.util.Enumeration<java.net.InetAddress> addresses=interfaces.nextElement().getInetAddresses();while(addresses.hasMoreElements())if(addresses.nextElement().equals(address))return;}
        throw new DeviceCommandPolicy.Blocked("adb_same_device_only");
    }
    public static JSONObject pair(Context c,String host,int pairingPort,String code,int connectPort)throws Exception{
        requireLocal(host);if(pairingPort<1||pairingPort>65535||connectPort<1||connectPort>65535||!code.matches("[0-9]{6}"))throw new IllegalArgumentException("invalid_pairing_arguments");
        CodexAdbChannel manager=get(c);manager.disconnect();
        boolean paired=manager.pair(host,pairingPort,code);
        if(!paired)return new JSONObject().put("ok",false).put("error","adb_pairing_failed");
        boolean connected=manager.connect(host,connectPort);
        if(connected){c.getSharedPreferences(CodexDeviceFeatures.PREFS,0).edit().putBoolean("adb",true).putString("adbHost",host).putInt("adbPort",connectPort).apply();}
        return new JSONObject().put("ok",connected).put("paired",true).put("connected",connected);
    }
    public static void reconnect(Context c)throws Exception{
        if(!CodexDeviceFeatures.enabled(c,"adb"))return;
        CodexAdbChannel manager=get(c);if(manager.isConnected())return;
        String host=c.getSharedPreferences(CodexDeviceFeatures.PREFS,0).getString("adbHost","127.0.0.1");int port=c.getSharedPreferences(CodexDeviceFeatures.PREFS,0).getInt("adbPort",0);
        requireLocal(host);if(port>0)manager.connect(host,port);
    }
    public static void revoke(Context c)throws Exception{
        c.getSharedPreferences(CodexDeviceFeatures.PREFS,0).edit().putBoolean("adb",false).remove("adbHost").remove("adbPort").apply();
        synchronized(CodexAdbChannel.class){if(instance!=null)instance.disconnect();instance=null;resetTlsCache();}
        KeyStore store=KeyStore.getInstance("AndroidKeyStore");store.load(null);store.deleteEntry(ALIAS);
        for(String name:new String[]{"device-adb-key.gcm","device-adb-cert.der"})new File(c.getNoBackupFilesDir(),name).delete();
    }
    public static JSONObject execute(Context c,DeviceCommandPolicy.Plan input)throws Exception{
        CodexDeviceFeatures.require(c,"adb");DeviceCommandPolicy.Plan plan=DeviceCommandPolicy.inspect(input.argv);
        reconnect(c);CodexAdbChannel manager=get(c);if(!manager.isConnected())throw new DeviceCommandPolicy.Blocked("adb_not_connected");
        CodexDeviceCommands.requireInteractive(c);CodexDeviceCommands.validateStop(c,plan);
        StringBuilder command=new StringBuilder();for(String arg:plan.argv){if(command.length()>0)command.append(' ');command.append("'").append(arg).append("'");}
        FutureTask<JSONObject> task=new FutureTask<>(()->{
            try(AdbStream stream=manager.openStream("shell,v2,raw:"+command)){
                InputStream source=stream.openInputStream();ByteArrayOutputStream output=new ByteArrayOutputStream();
                while(true){
                    int channel=source.read();if(channel<0)throw new IOException("adb_execution_unknown");
                    byte[] length=source.readNBytes(4);if(length.length!=4)throw new IOException("adb_execution_unknown");
                    int size=java.nio.ByteBuffer.wrap(length).order(java.nio.ByteOrder.LITTLE_ENDIAN).getInt();
                    if(size<0||size>1048576)throw new IOException("adb_frame_invalid");
                    byte[] bytes=source.readNBytes(size);if(bytes.length!=size)throw new IOException("adb_execution_unknown");
                    if(channel==3){if(size!=1)throw new IOException("adb_exit_invalid");int exit=bytes[0]&255;
                        return new JSONObject().put("ok",exit==0).put("exitCode",exit).put("output",output.toString(StandardCharsets.UTF_8.name())).put("channel","adb");}
                    if(channel!=1&&channel!=2)throw new IOException("adb_frame_invalid");
                    if(output.size()+size>65536)throw new IOException("adb_output_limit");output.write(bytes);
                }
            }
        });Thread worker=new Thread(task,"Codex-adb-command");worker.setDaemon(true);worker.start();
        try{return task.get(10,TimeUnit.SECONDS);}catch(Exception unknown){manager.disconnect();task.cancel(true);return new JSONObject().put("ok",false).put("error","adb_execution_unknown").put("retrySafe",false);}
    }
}
