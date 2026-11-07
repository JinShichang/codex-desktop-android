package com.ai.codex;
import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Switch;
import org.json.JSONObject;

/** Installation-local capability controls. Only actual native user actions change grants. */
public final class DeviceCapabilitiesActivity extends androidx.appcompat.app.AppCompatActivity {
    private static volatile boolean visible;
    public static boolean isVisible(){return visible;}
    @Override protected void onResume(){super.onResume();visible=true;}
    @Override protected void onPause(){visible=false;super.onPause();}
    private LinearLayout content;
    private String pendingKey;
    @Override public void onCreate(Bundle state){super.onCreate(state);render();}
    private void render(){
        ScrollView scroll=new ScrollView(this);
        scroll.setOnApplyWindowInsetsListener((v,insets)->{android.graphics.Insets bars=insets.getInsets(android.view.WindowInsets.Type.systemBars()|android.view.WindowInsets.Type.displayCutout());v.setPadding(bars.left,bars.top,bars.right,bars.bottom);return insets;});
        content=new LinearLayout(this);content.setOrientation(LinearLayout.VERTICAL);int pad=(int)(20*getResources().getDisplayMetrics().density);content.setPadding(pad,pad,pad,pad);scroll.addView(content);setContentView(scroll);
        text("设备能力授权",25);text("默认关闭，逐项授权。授权仅属于本次安装，可随时撤销。读取的屏幕、位置、文件和短信可能随对话发送给模型。",16);
        text("Root 模式（KernelSU / APatch）",21);
        text("在 KernelSU 或 APatch 授权 Codex 后，点下方按钮验证设备命令。后台屏单独开启。Root 设备命令仍受白名单限制。",16);
        button(CodexDeviceFeatures.enabled(this,"root")?"撤销 Root 通道":"授权并验证 Root 通道",()->{
            if(CodexDeviceFeatures.enabled(this,"root")){set("root",false);render();return;}
            android.widget.Toast.makeText(this,"请在 Root 管理器弹窗中授权 Codex",android.widget.Toast.LENGTH_LONG).show();
            new Thread(()->{String message;
                try{JSONObject result=CodexRootChannel.probe(this);
                    boolean ok=result.optBoolean("ok")&&result.optInt("androidUid",-1)==0&&result.optString("output").trim().equals("0");
                    set("root",ok);
                    String stage=result.optString("stage");
                    String detail=stage.isEmpty()?"":"（"+stage+" / "+result.optString("failureClass","未知异常")+"）";
                    message=ok?"Root 验证成功":"Root 验证失败："+result.optString("error","未取得 UID 0")+detail;
                }catch(Exception failure){message="Root 未授权或入口不可用";}
                String shown=message;runOnUiThread(()->{android.widget.Toast.makeText(this,shown,android.widget.Toast.LENGTH_LONG).show();render();});
            },"Root-user-authorization").start();
        });
        button("手机操控 / Root 后台屏",()->startActivity(new android.content.Intent(this,com.ai.codex.phone.PhoneSettingsActivity.class)));
        text("其他设备能力",21);
        toggle("files","目录 / 文本读取与导出到 Download/codex",null);
        toggle("interactions","通知、提示、振动、询问、分享和打开链接",Manifest.permission.POST_NOTIFICATIONS);
        toggle("clipboard","读写剪贴板（仅 APP 前台）",null);
        toggle("location","定位（仅前台单次定位）",Manifest.permission.ACCESS_FINE_LOCATION);
        for(String name:CodexDeviceFeatures.SENSORS.keySet())toggle("sensor_"+name,"传感器："+name,name.equals("steps")?Manifest.permission.ACTIVITY_RECOGNITION:null);
        toggle("flashlight","手电筒",Manifest.permission.CAMERA);
        toggle("sms_read","只读短信查询（每次检查系统权限）",Manifest.permission.READ_SMS);
        text("备用通道（手动连接，共用设备命令白名单）",21);
        button(CodexDeviceFeatures.enabled(this,"adb")?"撤销本机 ADB 授权与密钥":"配对本机无线 ADB",()->{
            if(CodexDeviceFeatures.enabled(this,"adb")){new Thread(()->{try{CodexAdbChannel.revoke(this);}catch(Exception ignored){}runOnUiThread(this::render);}).start();}
            else pairAdb();
        });
        button(CodexDeviceFeatures.enabled(this,"shizuku")?"撤销 Shizuku 设备通道":"授权 / 连接 Shizuku 设备通道",()->{
            try{if(CodexDeviceFeatures.enabled(this,"shizuku"))CodexShizukuChannel.close(this);else CodexShizukuChannel.authorize(this);render();}
            catch(Exception unavailable){android.widget.Toast.makeText(this,"请先启动 Shizuku；完成授权后再点一次连接",android.widget.Toast.LENGTH_LONG).show();}
        });
        button("返回",this::finish);
    }
    private void text(String value,int size){TextView v=new TextView(this);v.setText(value);v.setTextSize(size);v.setPadding(0,12,0,12);content.addView(v);}
    private void button(String label,Runnable action){Button b=new Button(this);b.setText(label);b.setOnClickListener(v->action.run());content.addView(b);}
    private void set(String key,boolean enabled){getSharedPreferences(CodexDeviceFeatures.PREFS,0).edit().putBoolean(key,enabled).apply();}
    private void toggle(String key,String label,String permission){
        Switch control=new Switch(this);control.setText(label);control.setTextSize(17);control.setPadding(0,18,0,18);control.setChecked(CodexDeviceFeatures.enabled(this,key));content.addView(control);
        control.setOnCheckedChangeListener((v,checked)->{
            if(!checked){set(key,false);if(key.equals("flashlight"))CodexDeviceFeatures.turnOffTorch(this);return;}
            if(permission!=null&&checkSelfPermission(permission)!=PackageManager.PERMISSION_GRANTED){
                pendingKey=key;control.setChecked(false);
                requestPermissions(permission.equals(Manifest.permission.ACCESS_FINE_LOCATION)?new String[]{Manifest.permission.ACCESS_FINE_LOCATION,Manifest.permission.ACCESS_COARSE_LOCATION}:new String[]{permission},74);
            }else set(key,true);
        });
    }
    @Override public void onRequestPermissionsResult(int code,String[] permissions,int[] results){super.onRequestPermissionsResult(code,permissions,results);
        if(code==74&&pendingKey!=null){boolean granted=false;for(int result:results)granted|=result==PackageManager.PERMISSION_GRANTED;set(pendingKey,granted);pendingKey=null;render();}}
    private void pairAdb(){
        LinearLayout form=new LinearLayout(this);form.setOrientation(LinearLayout.VERTICAL);
        android.widget.EditText host=new android.widget.EditText(this);host.setHint("本机 IP，默认 127.0.0.1");host.setText("127.0.0.1");form.addView(host);
        android.widget.EditText pairing=new android.widget.EditText(this);pairing.setHint("无线调试 → 使用配对码配对 → 配对端口");pairing.setInputType(2);form.addView(pairing);
        android.widget.EditText code=new android.widget.EditText(this);code.setHint("六位配对码");code.setInputType(18);form.addView(code);
        android.widget.EditText port=new android.widget.EditText(this);port.setHint("无线调试主页面的连接端口");port.setInputType(2);form.addView(port);
        new android.app.AlertDialog.Builder(this).setTitle("本机无线 ADB 配对").setView(form).setNegativeButton("取消",null).setPositiveButton("配对",(d,w)->{
            String address=host.getText().toString().trim(),secret=code.getText().toString().trim(),pairingValue=pairing.getText().toString().trim(),portValue=port.getText().toString().trim();code.setText("");
            new Thread(()->{String message;try{JSONObject result=CodexAdbChannel.pair(this,address,Integer.parseInt(pairingValue),secret,Integer.parseInt(portValue));
                message=result.optBoolean("ok")?"ADB 已配对并连接":"配对结果："+result.toString();
            }catch(Exception failure){message="配对未完成，请核对配对码、配对端口和连接端口";}
            String shown=message;runOnUiThread(()->{android.widget.Toast.makeText(this,shown,android.widget.Toast.LENGTH_LONG).show();render();});},"ADB-user-pairing").start();
        }).show();
    }
}
