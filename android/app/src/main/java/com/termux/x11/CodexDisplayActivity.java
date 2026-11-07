package com.termux.x11;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.os.Bundle;
import android.os.SystemClock;
import android.view.View;
import android.view.ViewGroup;
import android.widget.TextView;
import androidx.appcompat.app.AlertDialog;
import androidx.core.content.ContextCompat;

/** Automatic ChatGPT launch; the display connection screen is never a menu. */
public abstract class CodexDisplayActivity extends MainActivity {
    private static final String STATE_PHASE = "codex.runtime.phase";
    private static final String STATE_DETAIL = "codex.runtime.detail";
    private static final String STATE_LAUNCH = "codex.runtime.launchPending";
    private static final String STATE_LAUNCH_TIME = "codex.runtime.launchRequestedAt";
    private String phase = "stopped";
    private String failure = "";
    private View startup;
    private RuntimeLaunchGate launchGate;
    /** A display callback may deliver a pending user request, but cannot create one. */
    public static final class RuntimeLaunchGate {
        private boolean pending;
        private long requestedAt;
        public RuntimeLaunchGate(boolean restored, boolean fromHistory, boolean savedPending, long requestedAt) {
            pending = !fromHistory && (!restored || savedPending);
            this.requestedAt = requestedAt;
        }
        public void request(long requestedAt) { pending = true; this.requestedAt = requestedAt; }
        public boolean pending() { return pending; }
        public long requestedAt() { return requestedAt; }
        public void dispatched() { pending = false; }
        public void phaseChanged(String phase, long phaseAt) {
            // A delayed status for an earlier stop must not cancel a newer user
            // request. Monotonic timestamps cross the two application processes.
            if (phaseAt >= requestedAt && ("stopping".equals(phase) || "stopped".equals(phase)
                    || "error".equals(phase))) pending = false;
        }
    }
    private final BroadcastReceiver status = new BroadcastReceiver() {
        @Override public void onReceive(Context context, Intent intent) {
            phase = intent.getStringExtra("phase");
            failure = intent.getStringExtra("detail");
            launchGate.phaseChanged(phase, intent.getLongExtra(CodexRuntimeService.EXTRA_PHASE_TIME, Long.MAX_VALUE));
            if (launchGate.pending() && ("stopped".equals(phase) || "error".equals(phase))) phase = "starting";
            renderStartup();
            if ("stopped".equals(phase)) onRuntimeStopped();
        }
    };
    @Override protected boolean showsDisplayNotification() { return false; }
    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        boolean fromHistory = (getIntent().getFlags() & Intent.FLAG_ACTIVITY_LAUNCHED_FROM_HISTORY) != 0;
        launchGate = new RuntimeLaunchGate(state != null, fromHistory,
                state != null && state.getBoolean(STATE_LAUNCH, false),
                state == null ? SystemClock.elapsedRealtimeNanos() : state.getLong(STATE_LAUNCH_TIME, 0));
        if (state != null) {
            phase = state.getString(STATE_PHASE, "stopped");
            failure = state.getString(STATE_DETAIL, "");
        }
        if (launchGate.pending()) phase = "starting";
        else if ("ready".equals(phase) || "starting".equals(phase) || "stopping".equals(phase)
                || "recovering".equals(phase)) phase = "stopped";
        ViewGroup container = findViewById(R.id.stub);
        container.removeAllViews();
        startup = getLayoutInflater().inflate(com.ai.codex.R.layout.codex_startup, container, false);
        container.addView(startup);
        startup.findViewById(com.ai.codex.R.id.retry_chatgpt).setOnClickListener(view -> {
            requestRuntimeLaunch();
            onRuntimeRetryRequested();
        });
        startup.findViewById(com.ai.codex.R.id.startup_details).setOnClickListener(view ->
            new AlertDialog.Builder(this).setTitle("启动诊断")
                .setMessage(failure == null || failure.isEmpty() ? "尚未连接到 Codex。" : failure)
                .setPositiveButton(android.R.string.ok, null).show());
        ContextCompat.registerReceiver(this, status, new IntentFilter(CodexRuntimeService.ACTION_STATUS), ContextCompat.RECEIVER_NOT_EXPORTED);
        renderStartup();
    }
    @Override public void onResume() {
        super.onResume();
        // A recreated display must be able to reconnect without starting Linux.
        sendBroadcast(new Intent(CodexRuntimeService.ACTION_QUERY_STATUS).setPackage(getPackageName()));
    }
    protected final void requestRuntimeLaunch() {
        launchGate.request(SystemClock.elapsedRealtimeNanos());
        if ("stopped".equals(phase) || "error".equals(phase)) { phase = "starting"; failure = ""; }
        renderStartup();
    }
    protected final boolean hasPendingRuntimeLaunch() { return launchGate.pending(); }
    protected final void runtimeLaunchDispatched() { launchGate.dispatched(); }
    protected abstract void onRuntimeRetryRequested();
    protected void onRuntimeStopped() { }
    @Override protected void onSaveInstanceState(Bundle state) {
        state.putString(STATE_PHASE, phase);
        state.putString(STATE_DETAIL, failure);
        state.putBoolean(STATE_LAUNCH, launchGate.pending());
        state.putLong(STATE_LAUNCH_TIME, launchGate.requestedAt());
        super.onSaveInstanceState(state);
    }
    @Override void clientConnectedStateChanged() {
        super.clientConnectedStateChanged();
        runOnUiThread(this::renderStartup);
    }
    private void renderStartup() {
        if (startup == null) return;
        boolean ready = "ready".equals(phase) && getLorieView().connected();
        boolean failed = "error".equals(phase) || "stopped".equals(phase);
        findViewById(R.id.stub).setVisibility(ready ? View.INVISIBLE : View.VISIBLE);
        getLorieView().setVisibility(ready ? View.VISIBLE : View.INVISIBLE);
        ((TextView)startup.findViewById(com.ai.codex.R.id.startup_title)).setText(
            "error".equals(phase) ? "Codex 启动失败" : "stopped".equals(phase) ? "Codex 已停止" :
            "recovering".equals(phase) ? "正在恢复 Codex…" :
            "stopping".equals(phase) ? "正在关闭 Codex…" : "正在启动 Codex…");
        startup.findViewById(com.ai.codex.R.id.startup_progress).setVisibility(failed ? View.GONE : View.VISIBLE);
        startup.findViewById(com.ai.codex.R.id.retry_chatgpt).setVisibility(failed ? View.VISIBLE : View.GONE);
        startup.findViewById(com.ai.codex.R.id.startup_details).setVisibility(failed ? View.VISIBLE : View.GONE);
    }
    @Override protected void onDestroy() {
        unregisterReceiver(status);
        super.onDestroy();
    }
}
