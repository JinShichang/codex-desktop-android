package com.ai.codex.phoneprobe;

import android.app.Activity;
import android.os.Bundle;
import android.os.Process;
import android.widget.ScrollView;
import android.widget.TextView;
import java.io.BufferedReader;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStreamReader;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import org.json.JSONObject;

/** Fixed offline diagnostic, accepting no command or path from its Intent. */
public final class ProbeActivity extends Activity {
    private TextView output;

    @Override public void onCreate(Bundle state) {
        super.onCreate(state);
        ScrollView scroll = new ScrollView(this);
        output = new TextView(this);
        output.setTextSize(13);
        output.setPadding(24, 24, 24, 24);
        output.setText("Codex: fixed application-UID diagnostic\n");
        scroll.addView(output);
        setContentView(scroll);
        if (state == null) new Thread(this::runProbe, "Codex-phone-probe").start();
    }

    private void display(String line) {
        runOnUiThread(() -> output.append(line + "\n"));
    }

    private void runProbe() {
        File run = new File(getFilesDir(), "run-" + System.currentTimeMillis());
        try {
            if (!run.mkdir()) throw new IllegalStateException("Cannot create a fresh probe directory");
            Files.writeString(new File(getFilesDir(), "latest-run.txt").toPath(), run.getName() + "\n");
            try (FileOutputStream log = new FileOutputStream(new File(run, "results.jsonl"))) {
                String header = new JSONObject().put("type", "android-context")
                        .put("uid", Process.myUid()).put("pid", Process.myPid())
                        .put("package", getPackageName()).put("sdk", android.os.Build.VERSION.SDK_INT)
                        .put("scope", "Activity-origin ProcessBuilder; no root or shell owner").toString();
                append(log, header);
                String nativeDir = getApplicationInfo().nativeLibraryDir;
                ProcessBuilder builder = new ProcessBuilder(
                        nativeDir + "/libcodex_phone_probe.so",
                        nativeDir + "/libcodex_direct_runner.so",
                        nativeDir + "/libcodex_probe_worker.so",
                        nativeDir + "/libcodex_tty_runner.so", run.getAbsolutePath());
                builder.directory(run);
                builder.environment().clear();
                builder.environment().put("PATH", "/system/bin");
                builder.environment().put("LANG", "C.UTF-8");
                builder.environment().put("HOME", run.getAbsolutePath());
                builder.environment().put("TMPDIR", getCacheDir().getAbsolutePath());
                builder.redirectErrorStream(true);
                java.lang.Process child = builder.start();
                boolean summaryPassed = false;
                try (BufferedReader reader = new BufferedReader(new InputStreamReader(child.getInputStream(), StandardCharsets.UTF_8))) {
                    String line;
                    while ((line = reader.readLine()) != null) {
                        append(log, line);
                        try {
                            JSONObject event = new JSONObject(line);
                            if ("summary".equals(event.optString("type"))) summaryPassed = event.getBoolean("passed");
                        } catch (org.json.JSONException ignored) {
                            // Keep real native diagnostics verbatim; they cannot count as a result.
                        }
                    }
                }
                int exit = child.waitFor();
                append(log, new JSONObject().put("type", "android-result").put("ownerExit", exit)
                        .put("passed", summaryPassed && exit == 0).toString());
            }
        } catch (Exception error) {
            display("Probe failed: " + error);
            try {
                Files.writeString(new File(run, "java-error.txt").toPath(), error.toString() + "\n");
            } catch (Exception writeError) {
                display("Cannot retain diagnostic: " + writeError);
            }
        }
    }

    private void append(FileOutputStream log, String line) throws java.io.IOException {
        log.write((line + "\n").getBytes(StandardCharsets.UTF_8));
        log.flush();
        display(line);
    }
}
