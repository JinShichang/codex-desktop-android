package com.ai.codex;
import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import org.json.JSONArray;
import org.json.JSONObject;
import java.util.UUID;
import java.util.LinkedHashMap;

/** Answers remain pending until a real click; process loss never synthesizes an answer. */
public final class CodexDeviceQuestionActivity extends Activity {
    private static final LinkedHashMap<String,JSONObject> QUESTIONS = new LinkedHashMap<>();
    private static String active;
    public static synchronized boolean isPending(){return active!=null;}
    private String id;
    private boolean answered;
    public static synchronized JSONObject request(Context context,JSONObject args) throws Exception {
        if (active != null) return new JSONObject().put("ok",false).put("error","question_pending");
        String prompt=args.getString("text"); JSONArray options=args.getJSONArray("options");
        if (prompt.isEmpty() || prompt.length()>2000 || options.length()<2 || options.length()>3)
            throw new IllegalArgumentException("invalid_arguments");
        for (int i=0;i<options.length();i++) if (!(options.get(i) instanceof String) || options.getString(i).length()>80)
            throw new IllegalArgumentException("invalid_arguments");
        String id=UUID.randomUUID().toString();
        if (QUESTIONS.size()>=32) QUESTIONS.remove(QUESTIONS.keySet().iterator().next());
        QUESTIONS.put(id,new JSONObject().put("questionId",id).put("state","pending").put("text",prompt).put("options",new JSONArray(options.toString())));
        active=id;
        try { context.startActivity(new Intent(context,CodexDeviceQuestionActivity.class).putExtra("questionId",id).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)); }
        catch (RuntimeException failure) { QUESTIONS.remove(id); active=null; throw failure; }
        return new JSONObject().put("questionId",id).put("state","pending");
    }
    public static synchronized JSONObject result(String id) throws Exception {
        JSONObject value=QUESTIONS.get(id);
        if (value==null) return new JSONObject().put("state","unknown");
        JSONObject copy=new JSONObject(value.toString()); copy.remove("text"); copy.remove("options"); return copy;
    }
    private static synchronized void answer(String id,int choice) {
        JSONObject question=QUESTIONS.get(id);
        try { if (question!=null && question.getString("state").equals("pending")) {
            question.put("state",choice<0 ? "cancelled" : "answered");
            if (choice>=0) question.put("choice",choice).put("answer",question.getJSONArray("options").getString(choice));
        } } catch (Exception ignored) {}
        if (id!=null && id.equals(active)) active=null;
    }
    @Override public void onCreate(Bundle state) {
        super.onCreate(state); id=getIntent().getStringExtra("questionId");
        try {
            JSONObject question;
            synchronized (CodexDeviceQuestionActivity.class) { question=QUESTIONS.get(id); }
            if (question==null || !CodexDeviceFeatures.enabled(this,"interactions")) { finish(); return; }
            JSONArray values=question.getJSONArray("options"); String[] options=new String[values.length()];
            for (int i=0;i<options.length;i++) options[i]=values.getString(i);
            new android.app.AlertDialog.Builder(this).setTitle("Codex 询问").setMessage(question.getString("text"))
                .setPositiveButton(options[0],(d,w)->choose(0)).setNegativeButton(options[1],(d,w)->choose(1))
                .setNeutralButton(options.length==3 ? options[2] : "取消",(d,w)->choose(options.length==3 ? 2 : -1))
                .setOnCancelListener(d->choose(-1)).show();
        } catch (Exception invalid) { finish(); }
    }
    private void choose(int index) { answered=true; answer(id,CodexDeviceFeatures.enabled(this,"interactions") ? index : -1); finish(); }
    @Override protected void onDestroy() { if (!answered && !isChangingConfigurations()) answer(id,-1); super.onDestroy(); }
}
