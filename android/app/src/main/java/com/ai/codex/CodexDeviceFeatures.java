package com.ai.codex;

import android.Manifest;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.content.ClipData;
import android.content.ClipboardManager;
import android.content.ContentValues;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.hardware.Sensor;
import android.hardware.SensorEvent;
import android.hardware.SensorEventListener;
import android.hardware.SensorManager;
import android.hardware.camera2.CameraCharacteristics;
import android.hardware.camera2.CameraManager;
import android.location.Location;
import android.location.LocationManager;
import android.net.Uri;
import android.os.CancellationSignal;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.MediaStore;
import android.widget.Toast;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.nio.charset.StandardCharsets;
import java.util.Map;
import java.util.LinkedHashMap;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.FutureTask;

/** Typed Android features. Sensitive capabilities default off and are rechecked for each result. */
public final class CodexDeviceFeatures {
    private static final Handler MAIN = new Handler(Looper.getMainLooper());
    public static final Map<String,Integer> SENSORS = new LinkedHashMap<>();
    static {
        SENSORS.put("light", Sensor.TYPE_LIGHT); SENSORS.put("accelerometer", Sensor.TYPE_ACCELEROMETER);
        SENSORS.put("gyroscope", Sensor.TYPE_GYROSCOPE); SENSORS.put("magnetic", Sensor.TYPE_MAGNETIC_FIELD);
        SENSORS.put("pressure", Sensor.TYPE_PRESSURE); SENSORS.put("steps", Sensor.TYPE_STEP_COUNTER);
    }
    public static final String PREFS = "device-capabilities-v1";
    private CodexDeviceFeatures() {}
    public static boolean enabled(Context c, String key) { return c.getSharedPreferences(PREFS, 0).getBoolean(key, false); }
    public static void require(Context c, String key) {
        if (!enabled(c, key)) throw new DeviceCommandPolicy.Blocked("capability_disabled_" + key);
    }
    private static boolean permission(Context c, String p) { return c.checkSelfPermission(p) == PackageManager.PERMISSION_GRANTED; }
    private static void requireForeground() {
        if (!CodexActivity.isVisible() && !AndroidToolsActivity.isVisible())
            throw new DeviceCommandPolicy.Blocked("foreground_required");
    }
    private static String text(JSONObject args, String key, int limit) throws Exception {
        Object value = args.opt(key);
        if (!(value instanceof String) || ((String)value).length() > limit || ((String)value).indexOf(0) >= 0)
            throw new IllegalArgumentException("invalid_arguments");
        return (String)value;
    }
    private static <T> T onMain(java.util.concurrent.Callable<T> action) throws Exception {
        FutureTask<T> task = new FutureTask<>(action);
        if (Looper.myLooper() == Looper.getMainLooper()) task.run(); else MAIN.post(task);
        try { return task.get(2, TimeUnit.SECONDS); }
        finally { task.cancel(false); MAIN.removeCallbacks(task); }
    }
    public static JSONObject status(Context c) throws Exception {
        JSONObject enabled = new JSONObject();
        for (String key : new String[]{"root", "adb", "shizuku", "virtual_screen", "location", "flashlight", "clipboard", "files", "interactions", "sms_read",
                "sensor_light", "sensor_accelerometer", "sensor_gyroscope", "sensor_magnetic", "sensor_pressure", "sensor_steps"})
            enabled.put(key, enabled(c,key));
        return new JSONObject().put("enabled", enabled).put("installationScoped", true).put("permissions",new JSONObject()
            .put("locationFine",permission(c,Manifest.permission.ACCESS_FINE_LOCATION)).put("locationCoarse",permission(c,Manifest.permission.ACCESS_COARSE_LOCATION))
            .put("camera",permission(c,Manifest.permission.CAMERA)).put("steps",permission(c,Manifest.permission.ACTIVITY_RECOGNITION))
            .put("notifications",permission(c,Manifest.permission.POST_NOTIFICATIONS)).put("smsRead",permission(c,Manifest.permission.READ_SMS)))
            .put("foreground", CodexActivity.isVisible() || AndroidToolsActivity.isVisible());
    }
    public static void turnOffTorch(Context c){
        try{CameraManager manager=c.getSystemService(CameraManager.class);for(String id:manager.getCameraIdList())if(Boolean.TRUE.equals(manager.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE)))manager.setTorchMode(id,false);}catch(Exception ignored){}
    }
    public static JSONObject smsStatus(Context c) throws Exception {
        return new JSONObject().put("readOnly",true).put("enabled",enabled(c,"sms_read"))
            .put("readPermission",permission(c,Manifest.permission.READ_SMS)).put("rcsAvailable",false);
    }
    public static JSONObject exportPng(Context c,byte[] bytes) throws Exception {
        require(c,"files");
        if(bytes.length>8*1024*1024)throw new IllegalArgumentException("screenshot_too_large");
        return exportBytes(c,"Screenshot_"+System.currentTimeMillis()+".png","image/png",bytes);
    }
    private static JSONObject exportBytes(Context c,String name,String mime,byte[] bytes)throws Exception{
        ContentValues values=new ContentValues();values.put(MediaStore.MediaColumns.DISPLAY_NAME,name);values.put(MediaStore.MediaColumns.MIME_TYPE,mime);
        values.put(MediaStore.MediaColumns.RELATIVE_PATH,"Download/codex");values.put(MediaStore.MediaColumns.IS_PENDING,1);
        Uri uri=c.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);
        if(uri==null)throw new IllegalStateException("export_unavailable");
        try{
            try(java.io.OutputStream output=c.getContentResolver().openOutputStream(uri,"w")){output.write(bytes);}
            require(c,"files");values.clear();values.put(MediaStore.MediaColumns.IS_PENDING,0);c.getContentResolver().update(uri,values,null,null);
            return new JSONObject().put("ok",true).put("uri",uri.toString()).put("directory","Download/codex").put("bytes",bytes.length);
        }catch(Exception error){c.getContentResolver().delete(uri,null,null);throw error;}
    }
    public static boolean handles(String op) {
        return op.startsWith("sensor_") || op.equals("location") || op.equals("flashlight")
            || op.startsWith("clipboard_") || op.startsWith("file_") || op.startsWith("interaction_");
    }
    public static JSONObject execute(Context c, String op, JSONObject a) throws Exception {
        switch (op) {
            case "sensor_list": {
                SensorManager sm = c.getSystemService(SensorManager.class); JSONArray list = new JSONArray();
                for (Map.Entry<String,Integer> entry : SENSORS.entrySet()) {
                    Sensor sensor = sm == null ? null : sm.getDefaultSensor(entry.getValue());
                    list.put(new JSONObject().put("name", entry.getKey()).put("available", sensor != null)
                        .put("enabled", enabled(c,"sensor_" + entry.getKey())));
                }
                return new JSONObject().put("sensors", list);
            }
            case "sensor_read": return sensor(c, text(a,"name",32));
            case "location": return location(c);
            case "flashlight": {
                require(c,"flashlight"); requireForeground();
                if (!(a.opt("enabled") instanceof Boolean)) throw new IllegalArgumentException("invalid_arguments");
                if (!permission(c,Manifest.permission.CAMERA)) throw new SecurityException();
                CameraManager cm = c.getSystemService(CameraManager.class);
                for (String id : cm.getCameraIdList()) {
                    if (Boolean.TRUE.equals(cm.getCameraCharacteristics(id).get(CameraCharacteristics.FLASH_INFO_AVAILABLE))) {
                        cm.setTorchMode(id, a.getBoolean("enabled"));
                        return new JSONObject().put("requestAccepted",true).put("enabled",a.getBoolean("enabled"));
                    }
                }
                throw new IllegalStateException("flashlight_unavailable");
            }
            case "clipboard_read": case "clipboard_write": {
                require(c,"clipboard"); requireForeground();
                return onMain(() -> {
                    require(c,"clipboard"); requireForeground();
                    ClipboardManager manager = c.getSystemService(ClipboardManager.class);
                    if (op.equals("clipboard_write")) {
                        manager.setPrimaryClip(ClipData.newPlainText("Codex",text(a,"text",16384)));
                        return new JSONObject().put("written",true);
                    }
                    ClipData clip = manager.getPrimaryClip();
                    CharSequence value = clip == null || clip.getItemCount() == 0 ? null : clip.getItemAt(0).getText();
                    if (value != null && value.length() > 16384) throw new IllegalArgumentException("clipboard_too_large");
                    return new JSONObject().put("text",value == null ? JSONObject.NULL : value.toString())
                        .put("available",value != null);
                });
            }
            case "file_list": case "file_read": {
                require(c,"files");
                File candidate = new File(text(a,"path",4096));
                File path = DeviceFilePolicy.readable(candidate, new File(c.getFilesDir(),"projects"), android.os.Environment.getExternalStorageDirectory());
                if (op.equals("file_list")) {
                    byte[][] children = CodexDeviceFileRead.list(path.getPath(),257);
                    JSONArray files = new JSONArray();
                    for (int index=0;index<Math.min(256,children.length);index++) {
                        String name = new String(children[index],StandardCharsets.UTF_8);
                        try { DeviceFilePolicy.checkComponents(path.getPath()+"/"+name); }
                        catch (DeviceCommandPolicy.Blocked ignored) { continue; }
                        files.put(new JSONObject().put("name",name));
                    }
                    require(c,"files");
                    return new JSONObject().put("entries",files).put("truncated",children.length > 256);
                }
                byte[] data = CodexDeviceFileRead.read(path.getPath(), 1024 * 1024);
                require(c,"files");
                String value = StandardCharsets.UTF_8.newDecoder().onMalformedInput(java.nio.charset.CodingErrorAction.REPORT)
                    .decode(java.nio.ByteBuffer.wrap(data)).toString();
                return new JSONObject().put("text",value).put("bytes",data.length);
            }
            case "file_export": {
                require(c,"files");
                String name = text(a,"name",128);
                if (!name.matches("[A-Za-z0-9\\u4e00-\\u9fff][A-Za-z0-9\\u4e00-\\u9fff ._-]{0,127}"))throw new IllegalArgumentException("invalid_export_name");
                if(a.has("path")==a.has("text"))throw new IllegalArgumentException("provide_text_or_path");
                if(a.has("text"))return exportBytes(c,name,"text/plain",text(a,"text",16384).getBytes(StandardCharsets.UTF_8));
                File source=DeviceFilePolicy.readable(new File(text(a,"path",4096)),new File(c.getFilesDir(),"projects"),android.os.Environment.getExternalStorageDirectory());
                ContentValues values=new ContentValues();values.put(MediaStore.MediaColumns.DISPLAY_NAME,name);values.put(MediaStore.MediaColumns.MIME_TYPE,"application/octet-stream");
                values.put(MediaStore.MediaColumns.RELATIVE_PATH,"Download/codex");values.put(MediaStore.MediaColumns.IS_PENDING,1);
                Uri uri=c.getContentResolver().insert(MediaStore.Downloads.EXTERNAL_CONTENT_URI,values);
                if(uri==null)throw new IllegalStateException("export_unavailable");
                try{
                    long copied;
                    try(android.os.ParcelFileDescriptor output=c.getContentResolver().openFileDescriptor(uri,"w")){
                        if(output==null)throw new IllegalStateException("export_unavailable");
                        copied=CodexDeviceFileRead.copy(source.getPath(),output.getFd(),128L*1024*1024);
                    }
                    require(c,"files");values.clear();values.put(MediaStore.MediaColumns.IS_PENDING,0);c.getContentResolver().update(uri,values,null,null);
                    return new JSONObject().put("ok",true).put("uri",uri.toString()).put("bytes",copied).put("directory","Download/codex");
                }catch(Exception failure){c.getContentResolver().delete(uri,null,null);throw failure;}
            }
            default:
                if (op.startsWith("interaction_")) return interaction(c,op,a);
                throw new IllegalArgumentException("unknown_operation");
        }
    }
    private static JSONObject sensor(Context c, String name) throws Exception {
        if (!SENSORS.containsKey(name)) throw new IllegalArgumentException("unknown_sensor");
        require(c,"sensor_" + name); requireForeground();
        if (name.equals("steps") && !permission(c,Manifest.permission.ACTIVITY_RECOGNITION)) throw new SecurityException();
        SensorManager sm = c.getSystemService(SensorManager.class); Sensor sensor = sm.getDefaultSensor(SENSORS.get(name));
        if (sensor == null) throw new IllegalStateException("sensor_unavailable");
        CountDownLatch latch = new CountDownLatch(1); float[][] values = {null}; long[] timestamp = {0};
        SensorEventListener listener = new SensorEventListener() {
            public void onAccuracyChanged(Sensor s,int accuracy) {}
            public void onSensorChanged(SensorEvent event) {
                if (values[0] == null) { values[0] = event.values.clone(); timestamp[0] = event.timestamp; latch.countDown(); }
            }
        };
        try {
            if (!sm.registerListener(listener,sensor,SensorManager.SENSOR_DELAY_NORMAL,MAIN)) throw new IllegalStateException("sensor_unavailable");
            if (!latch.await(2,TimeUnit.SECONDS)) throw new IllegalStateException("sensor_timeout");
            require(c,"sensor_" + name); requireForeground();
            if(name.equals("steps")&&!permission(c,Manifest.permission.ACTIVITY_RECOGNITION))throw new SecurityException();
            JSONArray result = new JSONArray(); for (float value : values[0]) result.put((double)value);
            return new JSONObject().put("name",name).put("values",result).put("elapsedRealtimeNanos",timestamp[0]);
        } finally { sm.unregisterListener(listener); }
    }
    private static JSONObject location(Context c) throws Exception {
        require(c,"location"); requireForeground();
        boolean fine = permission(c,Manifest.permission.ACCESS_FINE_LOCATION);
        if (!fine && !permission(c,Manifest.permission.ACCESS_COARSE_LOCATION)) throw new SecurityException();
        LocationManager lm = c.getSystemService(LocationManager.class); String provider = fine && lm.isProviderEnabled(LocationManager.GPS_PROVIDER)
            ? LocationManager.GPS_PROVIDER : LocationManager.NETWORK_PROVIDER;
        CountDownLatch latch = new CountDownLatch(1); Location[] result = {null}; CancellationSignal cancellation = new CancellationSignal();
        try {
            lm.getCurrentLocation(provider,cancellation,c.getMainExecutor(), location -> { result[0] = location; latch.countDown(); });
            if (!latch.await(8,TimeUnit.SECONDS) || result[0] == null) throw new IllegalStateException("location_unavailable");
            require(c,"location"); requireForeground();
            if (!permission(c,Manifest.permission.ACCESS_FINE_LOCATION) && !permission(c,Manifest.permission.ACCESS_COARSE_LOCATION)) throw new SecurityException();
            if(fine&&!permission(c,Manifest.permission.ACCESS_FINE_LOCATION))throw new SecurityException();
            Location loc = result[0];
            return new JSONObject().put("latitude",loc.getLatitude()).put("longitude",loc.getLongitude())
                .put("accuracyMeters",loc.getAccuracy()).put("ageMs",Math.max(0,(SystemClock.elapsedRealtimeNanos()-loc.getElapsedRealtimeNanos())/1000000))
                .put("approximate",!fine).put("provider",loc.getProvider());
        } finally { cancellation.cancel(); }
    }
    private static JSONObject interaction(Context c,String op,JSONObject a) throws Exception {
        require(c,"interactions");
        if (op.equals("interaction_vibrate")) {
            int duration = a.optInt("durationMs",200);
            if (duration < 1 || duration > 3000) throw new IllegalArgumentException("invalid_arguments");
            c.getSystemService(Vibrator.class).vibrate(VibrationEffect.createOneShot(duration,VibrationEffect.DEFAULT_AMPLITUDE));
            return new JSONObject().put("requestAccepted",true);
        }
        if (op.equals("interaction_notify")) {
            if (!permission(c,Manifest.permission.POST_NOTIFICATIONS)) throw new SecurityException();
            NotificationManager nm = c.getSystemService(NotificationManager.class);
            if (!nm.areNotificationsEnabled()) throw new IllegalStateException("notifications_disabled");
            nm.createNotificationChannel(new NotificationChannel("device-tasks","Codex 任务提醒",NotificationManager.IMPORTANCE_DEFAULT));
            nm.notify(6102,new android.app.Notification.Builder(c,"device-tasks").setSmallIcon(R.drawable.codex_notification_icon)
                .setContentTitle(text(a,"title",100)).setContentText(text(a,"text",2000)).setAutoCancel(true).build());
            return new JSONObject().put("posted",true);
        }
        if (op.equals("interaction_answer")) return CodexDeviceQuestionActivity.result(text(a,"questionId",40));
        requireForeground();
        if (op.equals("interaction_ask")) return CodexDeviceQuestionActivity.request(c,a);
        return onMain(() -> {
            require(c,"interactions"); requireForeground();
            if (op.equals("interaction_toast")) Toast.makeText(c,text(a,"text",500),Toast.LENGTH_LONG).show();
            else if (op.equals("interaction_open")) {
                Uri uri = Uri.parse(text(a,"url",2048));
                if (!"https".equals(uri.getScheme()) && !"http".equals(uri.getScheme())) throw new DeviceCommandPolicy.Blocked("url_scheme_denied");
                c.startActivity(new Intent(Intent.ACTION_VIEW,uri).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } else if (op.equals("interaction_share")) {
                Intent share = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT,text(a,"text",16384));
                c.startActivity(Intent.createChooser(share,"分享内容").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
            } else throw new IllegalArgumentException("unknown_operation");
            return new JSONObject().put("requestAccepted",true);
        });
    }
}
