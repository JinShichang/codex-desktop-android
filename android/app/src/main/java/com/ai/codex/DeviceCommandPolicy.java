package com.ai.codex;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.HashSet;
import java.util.List;
import java.util.Set;

/** Device bridge policy, not a sandbox for ordinary app-UID project processes.
 * Design reference: DSHA DeviceShellPolicy/DeviceShellExecutor (MIT), see
 * docs/device-command-policy.md. No shell program or transport override is accepted.
 */
public final class DeviceCommandPolicy {
    public static final String REVISION = "device-argv-v5";
    static final int FILE_COMMAND_TIMEOUT_SECONDS = 120;
    private DeviceCommandPolicy() {}
    public static final class Blocked extends IllegalArgumentException {
        Blocked(String reason) { super("[POLICY_BLOCKED] " + reason); }
    }
    public static final class Plan {
        public final List<String> argv;
        public final String stopPackage;
        private Plan(List<String> argv, String stopPackage) {
            this.argv = Collections.unmodifiableList(new ArrayList<>(argv));
            this.stopPackage = stopPackage;
        }

        boolean copiesFile() { return argv.get(0).equals("/system/bin/cp"); }
        boolean installsApp() { return argv.get(0).equals("/system/bin/pm") && argv.get(1).equals("install"); }
        boolean fileCommand() { return copiesFile() || installsApp(); }
    }
    private static Set<String> words(String input) {
        return new HashSet<>(Arrays.asList(input.split(" ")));
    }
    private static boolean oneOf(String value, String choices) { return words(choices).contains(value); }
    private static void require(boolean condition, String reason) {
        if (!condition) throw new Blocked(reason);
    }
    public static boolean packageName(String value) {
        return value != null && value.length() <= 255
                && value.matches("[A-Za-z][A-Za-z0-9_]*(\\.[A-Za-z][A-Za-z0-9_]*)+");
    }
    public static Plan inspect(List<String> input) {
        require(input != null && !input.isEmpty() && input.size() <= 32, "invalid_argv");
        int length = 0;
        for (String value : input) {
            require(value != null && value.length() <= 1024, "invalid_argument");
            length += value.length();
            require(length <= 4096, "argv_too_large");
            // Operators, substitutions, escapes and quoting belong to shells, not this API.
            for (int i = 0; i < value.length(); i++) {
                char c = value.charAt(i);
                require(c >= 32 && c != 127 && ";|&<>`$\\\"'".indexOf(c) < 0,
                        "shell_syntax_not_allowed");
            }
        }
        List<String> args = new ArrayList<>(input);
        String name = args.get(0);
        if (name.startsWith("/system/bin/")) name = name.substring(12);
        require(name.matches("[a-z][a-z0-9_-]*"), "executable_not_allowed");
        List<String> tail = args.subList(1, args.size());
        boolean allowed = false;
        String stop = null;
        switch (name) {
            case "id": allowed = tail.isEmpty() || tail.size() == 1 && oneOf(tail.get(0), "-u -g -G"); break;
            case "whoami": case "getenforce": case "uptime": allowed = tail.isEmpty(); break;
            case "uname": allowed = tail.isEmpty() || tail.size() == 1 && oneOf(tail.get(0), "-a -s -r -m -v -n"); break;
            case "getprop": allowed = tail.isEmpty() || tail.size() == 1 && tail.get(0).matches("[A-Za-z][A-Za-z0-9_.-]{0,127}"); break;
            case "free": allowed = tail.isEmpty() || tail.size() == 1 && oneOf(tail.get(0), "-h -k -m -g -b"); break;
            case "df": allowed = tail.isEmpty() || tail.size() == 1 && oneOf(tail.get(0), "-h -k"); break;
            case "ps": allowed = tail.isEmpty() || tail.equals(Arrays.asList("-A")); break;
            case "pm":
                if ((tail.size() == 2 || tail.size() == 3 && oneOf(tail.get(1), "-r -R"))
                        && tail.get(0).equals("install")) {
                    String apk = tail.get(tail.size() - 1);
                    DeviceFilePolicy.requireSharedApk(apk);
                    allowed = true;
                    break;
                }
                allowed = tail.size() == 2 && ((oneOf(tail.get(0), "path dump") && packageName(tail.get(1)))
                    || tail.get(0).equals("list") && oneOf(tail.get(1), "packages features libraries users permissions"));
                if ((tail.size() == 3 || tail.size() == 4)
                        && tail.subList(0, 3).equals(List.of("list", "packages", "--show-versioncode"))) {
                    allowed = tail.size() == 3 || packageName(tail.get(3));
                }
                break;
            case "cp":
                if (tail.size() == 2 || tail.size() == 3 && tail.get(0).equals("-f")) {
                    String[] source = DeviceFilePolicy.sharedComponents(tail.get(tail.size() - 2));
                    DeviceFilePolicy.sharedComponents(tail.get(tail.size() - 1));
                    allowed = source.length > 0;
                }
                break;
            case "settings":
                allowed = tail.size() == 2 && tail.get(0).equals("list") && oneOf(tail.get(1), "system secure global")
                    || tail.size() == 3 && tail.get(0).equals("get") && oneOf(tail.get(1), "system secure global")
                    && tail.get(2).matches("[A-Za-z][A-Za-z0-9_.-]{0,127}");
                break;
            case "dumpsys":
                allowed = tail.size() == 1 && oneOf(tail.get(0), "-l battery power display connectivity wifi cpuinfo meminfo package window activity input sensorservice diskstats thermalservice")
                    || tail.size() == 2 && (tail.get(0).equals("activity") && oneOf(tail.get(1), "activities processes top recents")
                    || tail.get(0).equals("window") && oneOf(tail.get(1), "windows displays")
                    || oneOf(tail.get(0), "package meminfo") && packageName(tail.get(1)));
                break;
            case "am":
                allowed = tail.equals(Arrays.asList("get-current-user"));
                if (tail.size() == 2 && tail.get(0).equals("force-stop") && packageName(tail.get(1))) {
                    allowed = true; stop = tail.get(1);
                }
                break;
            default: throw new Blocked("unknown_or_dangerous_command");
        }
        require(allowed, "arguments_not_allowlisted");
        args.set(0, "/system/bin/" + name);
        return new Plan(args, stop);
    }

    static void requireChannel(Plan plan, String channel) {
        if (plan.installsApp()) require("root".equals(channel), "app_install_requires_root_channel");
        if (plan.copiesFile()) require(oneOf(channel, "app root"), "file_copy_requires_app_or_root_channel");
    }

    /** The unprivileged local entry cannot select a privileged identity. */
    public static void requireAppChannel(String channel) {
        require("app".equals(channel), "device_channel_unavailable");
    }
    public static void requireLaunchable(String target,String self){
        require(packageName(target)&&!target.equals(self)
            && !oneOf(target,"com.android.settings com.android.systemui com.android.managedprovisioning me.weishu.kernelsu com.rifsxd.ksunext me.bmax.apatch com.topjohnwu.magisk io.github.huskydg.magisk")
            && !target.endsWith(".permissioncontroller")&&!target.endsWith(".packageinstaller"),"protected_app_launch_denied");
    }
    /** No numeric PID signals: all stops use freshly verified package identities. */
    public static void requireStoppable(String target, String self, int uid, int selfUid, int flags) {
        require(packageName(target) && !target.equals(self)
                && !oneOf(target,"me.weishu.kernelsu com.rifsxd.ksunext me.bmax.apatch com.topjohnwu.magisk io.github.huskydg.magisk") && uid >= 10000 && uid != selfUid
                && uid / 100000 == selfUid / 100000 && (flags & (1 | 128)) == 0,
                "system_shared_uid_or_self_app_stop_denied");
    }
}
