package com.ai.codex;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import com.termux.x11.CodexRuntimeService;

/** ADB-only entry to the real lifecycle; no alternate executor or input paths. */
public final class NativePreparationReceiver extends BroadcastReceiver {
    @Override public void onReceive(Context context, Intent intent) {
        if (intent == null) throw new IllegalArgumentException("Native lifecycle action is required");
        String action = intent.getAction();
        Intent service = new Intent(context, CodexRuntimeService.class);
        if (CodexExecutorRuntime.ACTION_PREPARE.equals(action)) {
            context.startForegroundService(service.setAction(CodexExecutorRuntime.ACTION_PREPARE));
        } else if ("com.ai.codex.action.STOP_NATIVE_EXECUTOR".equals(action)) {
            context.startForegroundService(service.setAction("stop"));
        } else throw new SecurityException("Only native prepare or stop is accepted");
    }
}
