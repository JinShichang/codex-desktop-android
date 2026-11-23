package com.ai.codex;

import android.Manifest;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.TextView;

/** OS permission status and shortcuts. There is no second application permission switch. */
public final class AndroidToolsActivity extends androidx.appcompat.app.AppCompatActivity {
    private static volatile boolean visible;
    public static boolean isVisible() { return visible; }
    private LinearLayout content;
    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        CodexAndroidBridge.start(this);
    }
    @Override public void onResume() { super.onResume(); visible = true; render(); }
    @Override public void onPause() { visible = false; super.onPause(); }
    private void render() {
        ScrollView scroll = new ScrollView(this);
        scroll.setOnApplyWindowInsetsListener((view, insets) -> {
            android.graphics.Insets bars = insets.getInsets(android.view.WindowInsets.Type.systemBars() | android.view.WindowInsets.Type.displayCutout());
            view.setPadding(bars.left, bars.top, bars.right, bars.bottom);
            return insets;
        });
        content = new LinearLayout(this); content.setOrientation(LinearLayout.VERTICAL);
        content.setId(R.id.android_tools_consent);
        int pad = (int)(24 * getResources().getDisplayMetrics().density); content.setPadding(pad,pad,pad,pad);
        scroll.addView(content); setContentView(scroll);
        text("Android 工具", 25);
        String liveStatus = !LiveNotifications.notificationsEnabled(this) ? "通知未允许"
                : android.os.Build.VERSION.SDK_INT < 36 ? "系统不支持，使用普通通知"
                : LiveNotifications.canPromote(this) ? "已允许" : "未允许，使用普通通知";
        text("原生实时通知：" + liveStatus, 18);
        text("对话任务和手机操控进行时更新通知。支持的系统可显示为灵动岛或超级岛，具体样式由系统决定。", 16);
        button("灵动岛 / 超级岛 / 实时通知设置", () -> startActivity(LiveNotifications.settingsIntent(this)));
        text("图形模式：" + CodexGraphics.LABELS[CodexGraphics.selected(this)], 18);
        button("选择图形模式（下次启动生效）", () -> new androidx.appcompat.app.AlertDialog.Builder(this)
                .setTitle("图形渲染模式")
                .setSingleChoiceItems(CodexGraphics.LABELS, CodexGraphics.selected(this), (dialog, which) -> {
                    try { CodexGraphics.set(this, CodexGraphics.MODES[which]); dialog.dismiss(); render(); }
                    catch (Exception error) { android.widget.Toast.makeText(this, "保存失败：" + error.getMessage(), android.widget.Toast.LENGTH_LONG).show(); }
                }).setNegativeButton("取消", null).show());
        text("自动：探测通过才使用 Adreno 加速，否则回退软件渲染。兼容模式使用 CPU；加速模式失败会给出诊断。", 16);
        button("导出日志到 /sdcard/codex/log", () -> {
            if (!android.os.Environment.isExternalStorageManager()) {
                android.widget.Toast.makeText(this, "请先允许所有文件访问，再点击导出日志", android.widget.Toast.LENGTH_LONG).show();
                startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION).setData(Uri.parse("package:" + getPackageName())));
                return;
            }
            android.widget.Toast.makeText(this, "正在收集并打包日志…", android.widget.Toast.LENGTH_SHORT).show();
            ContextWork.export(this);
        });
        text("CC Switch 配置目录", 18);
        text("在 CC Switch 中选择“连接配置目录”，从系统文件选择器进入“Codex → .codex”并授权。切换前请安全退出桌面客户端，保存后重新启动；目录访问不会启动 Linux 桌面。", 16);
        text("你可以让 Codex 查找消息或操作应用。使用相关功能时，Android 会请求相应权限。", 17);
        text("按你的要求读取的消息和截图会在对话中发送给模型。你可以随时在 Android 设置中撤销权限。", 16);
        button("手机操控（读屏、操作与 Root 后台屏）", () -> startActivity(new Intent(this, com.ai.codex.phone.PhoneSettingsActivity.class)));
        button("其他设备能力 / 文件与传感器", () -> startActivity(new Intent(this, DeviceCapabilitiesActivity.class)));
        boolean storage = android.os.Environment.isExternalStorageManager();
        text("共享存储：" + (storage ? "已允许访问所有文件" : "未授权"), 18);
        text("共享项目目录：/sdcard/codex/Projects。授权后重新打开桌面以连接共享存储。", 16);
        button(storage ? "管理所有文件访问" : "允许所有文件访问", () -> {
            try {
                startActivity(new Intent(Settings.ACTION_MANAGE_APP_ALL_FILES_ACCESS_PERMISSION)
                        .setData(Uri.parse("package:" + getPackageName())));
            } catch (android.content.ActivityNotFoundException unavailable) {
                startActivity(new Intent(Settings.ACTION_MANAGE_ALL_FILES_ACCESS_PERMISSION));
            }
        });
        boolean screen = CodexAndroidPermissionActivity.isGranted(this, "screen_control");
        boolean connected = com.ai.codex.phone.a11y.PhoneA11yService.Companion.isConnected();
        text("屏幕上的应用：" + (screen
                ? "已授权 · 服务" + (connected ? "已连接" : "未连接")
                : "未授权"), 18);
        if (screen && !connected)
            text("Android 已保存授权，但服务尚未连接。请在无障碍设置中检查服务状态。", 16);
        button(screen ? "管理屏幕访问权限" : "允许屏幕访问", () -> {
            if (screen) CodexAndroidPermissionActivity.openAccessibilitySettings(this);
            else showRequest("screen_control");
        });
        text("短信：只读查询 · " + granted(Manifest.permission.READ_SMS), 18);
        if (checkSelfPermission(Manifest.permission.READ_SMS) != PackageManager.PERMISSION_GRANTED)
            button("允许搜索短信", () -> showRequest("sms_read"));
        text("设备桥短信入口只读。归档与 RCS 内容以短信提供者实际返回为准。", 16);
        button("管理 Android 权限", () -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS)
                .setData(Uri.parse("package:" + getPackageName()))));
        button("返回 Codex", () -> { startActivity(new Intent(this, CodexActivity.class)); finish(); });
    }
    private static final class ContextWork {
        private static final java.util.concurrent.ExecutorService WORK = java.util.concurrent.Executors.newSingleThreadExecutor();
        static void export(AndroidToolsActivity activity) {
            android.content.Context context = activity.getApplicationContext();
            WORK.execute(() -> {
                String message;
                try { message = "日志已导出：" + CodexLogExport.export(context).getAbsolutePath(); }
                catch (Exception error) { message = "导出失败：" + error.getMessage(); }
                String result = message;
                new android.os.Handler(android.os.Looper.getMainLooper()).post(() -> android.widget.Toast.makeText(context, result, android.widget.Toast.LENGTH_LONG).show());
            });
        }
    }
    private String granted(String name) {
        String state = Manifest.permission.SEND_SMS.equals(name) ? "授权" : "授权";
        return (checkSelfPermission(name) == PackageManager.PERMISSION_GRANTED ? "" : "未") + state;
    }
    private void text(String value, int size) { TextView view = new TextView(this); view.setText(value); view.setTextSize(size); view.setPadding(0,12,0,12); content.addView(view); }
    private void button(String label, Runnable action) { Button button = new Button(this); button.setText(label); button.setOnClickListener(view -> action.run()); content.addView(button); }
    private void showRequest(String scope) {
        org.json.JSONObject response = CodexAndroidPermissionActivity.requestFromPanel(this, scope);
        if (!response.optBoolean("ok")) {
            String message = "permission_denied".equals(response.optString("error"))
                    ? "访问被拒绝。你可以在 Android 权限设置中修改。"
                    : "无法打开 Android 权限请求，请在此页面重试。";
            android.widget.Toast.makeText(this, message, android.widget.Toast.LENGTH_LONG).show();
        }
    }
}
