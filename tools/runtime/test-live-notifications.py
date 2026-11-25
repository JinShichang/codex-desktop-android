"""Host regression checks for optional Android Live Update APIs.

The controlled framework deliberately omits Builder.setRequestPromotedOngoing.
This compiles and executes the production helper, not an Android device. An
actual SDK build and device validation remain separate checks.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
SOURCES = {
    'android/os/Build.java': '''package android.os; public class Build {
        public static class VERSION { public static int SDK_INT = 36; }
    }''',
    'android/os/Bundle.java': '''package android.os; import java.util.HashMap;
        public class Bundle { private final HashMap<String,Object> data = new HashMap<>();
        public void putBoolean(String k, boolean v) { data.put(k,v); }
        public boolean getBoolean(String k) { return Boolean.TRUE.equals(data.get(k)); }
        public void remove(String k) { data.remove(k); }
        public void putString(String k,String v) { data.put(k,v); }
        public String getString(String k) { return (String)data.get(k); }
    }''',
    'android/app/Notification.java': '''package android.app; import android.os.Bundle;
        public class Notification {
        public static final String CATEGORY_PROGRESS = "progress";
        public static final int FLAG_ONGOING_EVENT = 2;
        public int flags; public long getTimeoutAfter() { return 0; }
        public static boolean missingChip, missingStyle, missingProgress;
        public static class BigTextStyle { public String text;
            public BigTextStyle bigText(String v) { text=v; return this; } }
        public static class ProgressStyle {
            public boolean indeterminate;
            public ProgressStyle() { if(missingStyle) throw new NoClassDefFoundError("ProgressStyle"); }
            public ProgressStyle setProgressIndeterminate(boolean v) {
                if(missingProgress) throw new NoSuchMethodError("setProgressIndeterminate");
                indeterminate=v; return this;
            }
        }
        public static class Builder {
            public final Bundle extras=new Bundle(); public Object style;
            public int chipCalls; public String chip; public boolean ongoing, indeterminate;
            public Builder setOnlyAlertOnce(boolean v) { return this; }
            public Builder setAutoCancel(boolean v) { return this; }
            public Builder setLocalOnly(boolean v) { return this; }
            public Builder setOngoing(boolean v) { ongoing=v; return this; }
            public Builder setCategory(String v) { return this; }
            public Builder setStyle(Object v) { style=v; return this; }
            public Builder setProgress(int max,int progress,boolean v) { indeterminate=v; return this; }
            public Builder setShortCriticalText(String v) {
                chipCalls++; if(missingChip) throw new NoSuchMethodError("setShortCriticalText");
                chip=v; return this;
            }
            public Bundle getExtras() { return extras; }
        }
    }''',
    'android/app/NotificationManager.java': '''package android.app;
        import android.service.notification.StatusBarNotification;
        public class NotificationManager {
            public boolean enabled=true, allowed=true; public int queries;
            public Throwable failure, enabledFailure;
            private void fail(Throwable t) {
                if(t instanceof Error) throw (Error)t;
                if(t instanceof RuntimeException) throw (RuntimeException)t;
            }
            public boolean areNotificationsEnabled() { fail(enabledFailure); return enabled; }
            public boolean canPostPromotedNotifications() { queries++; fail(failure); return allowed; }
            public StatusBarNotification[] getActiveNotifications() { return new StatusBarNotification[0]; }
        }
    ''',
    'android/content/Context.java': '''package android.content;
        import android.app.NotificationManager;
        public class Context { public NotificationManager manager=new NotificationManager();
            public <T>T getSystemService(Class<T> kind) { return kind.cast(manager); }
            public String getPackageName() { return "com.ai.codex"; }
            public Object getPackageManager() { return null; }
            public void sendBroadcast(Intent i) { }
        }
    ''',
    'android/content/Intent.java': '''package android.content;
        public class Intent { public Intent(String action) { }
            public Intent putExtra(String key,String value) { return this; }
            public Intent setPackage(String value) { return this; }
            public Object resolveActivity(Object manager) { return null; }
        }
    ''',
    'android/provider/Settings.java': '''package android.provider;
        public class Settings {
            public static final String ACTION_APP_NOTIFICATION_PROMOTION_SETTINGS="promotion";
            public static final String ACTION_APP_NOTIFICATION_SETTINGS="notifications";
            public static final String EXTRA_APP_PACKAGE="package";
        }
    ''',
    'android/service/notification/StatusBarNotification.java': '''package android.service.notification;
        import android.app.Notification;
        public class StatusBarNotification {
            public int getId() { return 0; } public String getTag() { return null; }
            public String getPackageName() { return "com.ai.codex"; }
            public Notification getNotification() { return new Notification(); }
            public long getPostTime() { return 0; }
        }
    ''',
    'com/ai/codex/LiveNotificationsCompatibilityCheck.java': '''package com.ai.codex;
        import android.app.*; import android.content.Context; import android.os.Build;
        import java.util.ArrayList; import java.util.List;
        public class LiveNotificationsCompatibilityCheck {
            private static final String KEY="android.requestPromotedOngoing";
            private static final List<String> passed=new ArrayList<>();
            private static void check(boolean value,String message) { if(!value) throw new AssertionError(message); }
            private static Context context(int sdk) {
                Build.VERSION.SDK_INT=sdk;
                Notification.missingChip=false; Notification.missingStyle=false; Notification.missingProgress=false;
                return new Context();
            }
            private static Notification.Builder apply(Context c,boolean active) {
                Notification.Builder b=new Notification.Builder();
                check(b==LiveNotifications.apply(c,b,active,"Codex 正在思考",0),"Caller builder was replaced");
                return b;
            }
            private static void ordinary(Notification.Builder b) {
                check(!b.getExtras().getBoolean(KEY),"Ordinary notification requests promotion");
                check(b.style instanceof Notification.BigTextStyle,"Ordinary progress style lost");
                check(b.ongoing&&b.indeterminate,"Foreground progress notification lost");
            }
            private static void pass(String name) { passed.add(name); System.out.println("PASS "+name); }
            public static void main(String[] args) {
                for(int sdk:new int[]{30,35}) {
                    Context c=context(sdk); c.manager.failure=new NoSuchMethodError("unavailable below API 36");
                    ordinary(apply(c,true)); check(c.manager.queries==0,"Queried new API on older Android");
                    pass("API "+sdk+" uses ordinary foreground notification without new API calls");
                }
                for(int sdk:new int[]{36,37}) {
                    Context c=context(sdk); Notification.Builder b=apply(c,true);
                    check(b.getExtras().getBoolean(KEY),"Promotion extra missing");
                    check(b.style instanceof Notification.ProgressStyle&&((Notification.ProgressStyle)b.style).indeterminate,"Live progress missing");
                    check("正在思考".equals(b.chip),"Live status chip changed");
                    pass("API "+sdk+" requests Live Update through extras without the absent Builder setter");
                }
                Context c=context(36); c.manager.allowed=false; Notification.Builder b=apply(c,true);
                ordinary(b); check(b.chipCalls==0,"Optional chip API called without promotion permission");
                pass("API 36 without promotion permission keeps ordinary notification");
                c=context(36); c.manager.enabled=false; ordinary(apply(c,true));
                check(c.manager.queries==0,"Queried promotion when notifications are disabled");
                pass("disabled notifications do not invoke promotion APIs");
                c=context(36); b=apply(c,false); check(c.manager.queries==0&&b.chipCalls==0&&!b.getExtras().getBoolean(KEY),"Inactive state invoked optional APIs");
                pass("inactive runtime notification does not link optional APIs");
                for(Throwable failure:new Throwable[]{new NoSuchMethodError("canPostPromotedNotifications"),new NoClassDefFoundError("optional notification API"),new SecurityException("denied")}) {
                    c=context(36); c.manager.failure=failure; ordinary(apply(c,true));
                    pass("promotion query "+failure.getClass().getSimpleName()+" falls back without crashing");
                }
                c=context(36); c.manager.enabledFailure=new IllegalStateException("notification service unavailable");
                ordinary(apply(c,true)); pass("notification permission query failure falls back safely");
                c=context(36); Notification.missingChip=true; ordinary(apply(c,true));
                pass("missing short critical text API keeps ordinary foreground notification");
                c=context(36); Notification.missingStyle=true; ordinary(apply(c,true));
                pass("missing ProgressStyle keeps ordinary foreground notification");
                c=context(36); Notification.missingProgress=true; ordinary(apply(c,true));
                pass("missing progress style method keeps ordinary foreground notification");
                c=context(36); b=apply(c,true); b.getExtras().putString("caller-extra","keep"); c.manager.allowed=false;
                LiveNotifications.apply(c,b,true,"正在执行命令",1); ordinary(b);
                check("keep".equals(b.getExtras().getString("caller-extra")),"Caller extras lost");
                pass("permission revocation removes stale promotion while preserving caller extras");
                c=context(36); c.manager=null; ordinary(apply(c,true));
                pass("absent notification service falls back safely");
                System.out.println("RESULT_TEST_COUNT="+passed.size());
            }
        }
    ''',
    'com/ai/codex/MissingProgressClassCheck.java': '''package com.ai.codex;
        import android.app.Notification; import android.content.Context; import android.os.Build;
        public class MissingProgressClassCheck {
            public static void main(String[] args) {
                Build.VERSION.SDK_INT=Integer.parseInt(args[0]);
                Notification.Builder b=LiveNotifications.apply(new Context(),new Notification.Builder(),true,"正在启动 Codex",0);
                if(!(b.style instanceof Notification.BigTextStyle)||b.getExtras().getBoolean("android.requestPromotedOngoing"))
                    throw new AssertionError("Missing framework class did not preserve the ordinary notification");
                System.out.println("PASS API "+args[0]+" works with the optional ProgressStyle class physically absent");
            }
        }
    ''',
}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    out.mkdir(parents=True,exist_ok=False)
    source_dir=out/'sources';classes=out/'classes';classes.mkdir()
    for name,value in SOURCES.items():
        path=source_dir/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_text(value,encoding='utf-8')
    sources=list(source_dir.rglob('*.java'))+[ROOT/'android/app/src/main/java/com/ai/codex'/name
        for name in ('LiveNotifications.java','LiveNotificationText.java')]
    commands=[('compile',[shutil.which('javac'),'--release','17','-encoding','UTF-8','-d',str(classes),*map(str,sources)]),
              ('test',[shutil.which('java'),'-cp',str(classes),'com.ai.codex.LiveNotificationsCompatibilityCheck'])]
    for name,command in commands:
        if command[0] is None:raise RuntimeError('Full host JDK required')
        result=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=90)
        text=result.stdout+result.stderr
        (out/(name+'.log')).write_text(text,encoding='utf-8')
        print(text,end='',flush=True);result.check_returncode()
    for path in (classes/'com/ai/codex').glob('LiveNotifications*.class'):
        assert b'setRequestPromotedOngoing' not in path.read_bytes()
    assert b'android.requestPromotedOngoing' in (classes/'com/ai/codex/LiveNotifications.class').read_bytes()
    count=int(next(line.split('=')[1] for line in text.splitlines() if line.startswith('RESULT_TEST_COUNT=')))
    progress_class=classes/'android/app/Notification$ProgressStyle.class'
    saved=progress_class.with_suffix('.class.disabled')
    progress_class.rename(saved)
    try:
        for sdk in (30,35,36):
            result=subprocess.run([shutil.which('java'),'-cp',str(classes),'com.ai.codex.MissingProgressClassCheck',str(sdk)],
                cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=30)
            (out/('missing-class-'+str(sdk)+'.log')).write_text(result.stdout+result.stderr,encoding='utf-8')
            print(result.stdout+result.stderr,end='',flush=True);result.check_returncode();count+=1
    finally: saved.rename(progress_class)
    report={'success':True,'cases':count,'androidExecuted':False,'builderPromotionSetterAbsent':True,
            'optionalFrameworkClassPhysicallyAbsentTested':True,
            'productionBytecodeHasNoPromotionSetterReference':True,
            'scope':'Controlled framework with missing optional APIs; production notification helper compiled and executed on host JVM'}
    (out/'report.json').write_text(json.dumps(report,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(report),flush=True)


if __name__=='__main__':main()
