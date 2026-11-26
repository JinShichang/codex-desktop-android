/* Separate Android application transport. Between fork and exec, use only
 * async-signal-safe operations; never inherit Binder/JVM descriptors. */
#define _GNU_SOURCE
#include <jni.h>
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <linux/capability.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

/* COM_AI_CODEX_ALLOW_UNFILTERED_SECCOMP
 *
 * Upstream requires PR_GET_SECCOMP == 2 here, i.e. the process still runs inside
 * the zygote seccomp filter. On a device where this application is authorised by
 * KernelSU, the manager deliberately strips that filter from its processes so that
 * privilege escalation can work, and PR_GET_SECCOMP reports 0.
 *
 * Measured on the target device (OnePlus 13, Android 15):
 *   com.tencent.mm       (not KernelSU-authorised)  Seccomp 2 / filters 1
 *   com.android.settings (not KernelSU-authorised)  Seccomp 2
 *   com.ai.codex.dev     (KernelSU-authorised)      Seccomp 0 / filters 0
 *   app.operit           (KernelSU-authorised)      Seccomp 0
 *
 * The two requirements are mutually exclusive: the guest runtime needs root (which
 * this build obtains through the same KernelSU authorisation), and the executor
 * demands a filter that authorisation removes.
 *
 * This build therefore accepts 0 *or* 2, and nothing else. Every other admission
 * condition is still enforced unchanged: real == effective == saved uid and gid
 * must equal the application uid, PR_GET_NO_NEW_PRIVS must be 0, and all
 * capability sets must be empty. That keeps the guarantee that the transport runs
 * as the application itself and cannot gain privileges through capabilities, while
 * accepting that the filter may have been removed by the root manager.
 *
 * This is a deliberate, documented weakening of the upstream sandbox for local
 * builds only; it must not be presented as equivalent to the upstream check.
 */
static int tolerated_seccomp(void) {
    int mode = prctl(PR_GET_SECCOMP, 0, 0, 0, 0);
    return mode == 2 || mode == 0;
}

/* COM_AI_CODEX_ALLOW_SIBLING_PROC_POPULATION
 *
 * Android mounts /proc with hidepid=invisible on this device. With that mount,
 * proc_pid_permission() calls ptrace_may_access(target, PTRACE_MODE_READ_FSCREDS)
 * for a sibling process, and ptrace_may_access rejects the read when the *target*
 * is not dumpable. Zygote clears dumpable (PR_SET_DUMPABLE 0) for ordinary
 * application processes, so the two processes sharing this application UID cannot
 * read each other's /proc/<pid>/stat even though their uids, gids and SELinux
 * domain are identical.
 *
 * Measured on the target device (OnePlus 13, Android 15, hidepid=invisible):
 *   root, or a process left in the u:r:ksu:s0 domain -> reads the sibling stat
 *   uid 10415 from the app's own untrusted_app domain -> /proc/<pid>/stat ENOENT
 *   the same uid leaking its *own* /proc/self/stat, or its own children -> fine
 * A control experiment in the KSU domain was readable regardless of its dumpable
 * value, which confirms the SELinux domain, not dumpable alone, decides this; the
 * application processes are the ones stuck in untrusted_app.
 *
 * AndroidProcessPopulation.capture() therefore could not pin the main process's
 * kernel start time, and every launch failed with
 *   java.nio.file.NoSuchFileException: /proc/<pid>/stat
 * -> qualified_native_deployment_unavailable.
 *
 * This entry point restores ONLY that visibility, by making the calling process
 * dumpable again from inside its own process (dumpable is a property of the
 * target, so the :runtime process cannot do this for the main process). Both
 * application processes call it for themselves before the population is captured.
 *
 * Deliberate, documented weakening: a same-UID process can now ptrace this one,
 * and the kernel may write a core image. It does not grant privileges: the
 * transport admission still requires the exact application uid/gid triple,
 * untouched no-new-privs, empty capability sets, and the captured identities are
 * still read from the kernel. It must not be presented as equivalent to the
 * upstream sandbox.
 */
static int admitted_identity(uid_t application_uid) {
    uid_t real, effective, saved;
    gid_t greal, geffective, gsaved;
    struct __user_cap_header_struct header = {.version = _LINUX_CAPABILITY_VERSION_3};
    struct __user_cap_data_struct capabilities[2] = {{0}, {0}};
    if (application_uid < 10000 ||
            getresuid(&real, &effective, &saved) < 0 || getresgid(&greal, &geffective, &gsaved) < 0 ||
            real != application_uid || effective != real || saved != real ||
            greal != application_uid || geffective != greal || gsaved != greal ||
            !tolerated_seccomp() || prctl(PR_GET_NO_NEW_PRIVS, 0, 0, 0, 0) != 0 ||
            syscall(__NR_capget, &header, capabilities) < 0) return 0;
    for (int i = 0; i < 2; ++i) {
        if (capabilities[i].effective || capabilities[i].permitted || capabilities[i].inheritable) return 0;
    }
    /* Empty permitted/inheritable sets also exclude all ambient capabilities. */
    return 1;
}

/* The application id is a build input, so the private data path cannot be a
 * literal. Accept exactly the two Android spellings of this user's app data
 * directory and require them to name the same directory, then keep every
 * ownership, mode and inode check below unchanged. Java already resolved this
 * path from PackageManager; this only re-verifies it cannot be redirected. */
static int same_private_data(const char *declared, const char *canonical, uid_t uid) {
    char actual[PATH_MAX], user_path[PATH_MAX], data_path[PATH_MAX];
    struct stat named, resolved;
    /* /data/user/0/<pkg> is canonical; /data/data/<pkg> is the compatibility view. */
    if (strncmp(declared, "/data/user/0/", 13) != 0) return 0;
    const char *package = declared + 13;
    if (strchr(package, '/') != NULL || strstr(package, "..") != NULL || *package == '\0') return 0;
    int user_len = snprintf(user_path, sizeof(user_path), "/data/user/0/%s", package);
    int data_len = snprintf(data_path, sizeof(data_path), "/data/data/%s", package);
    if (user_len <= 0 || (size_t)user_len >= sizeof(user_path) ||
            data_len <= 0 || (size_t)data_len >= sizeof(data_path)) return 0;
    if (strcmp(declared, user_path) != 0 ||
            (strcmp(canonical, declared) != 0 && strcmp(canonical, data_path) != 0) ||
            realpath(declared, actual) == NULL || strcmp(actual, canonical) != 0 ||
            lstat(declared, &named) < 0 || lstat(canonical, &resolved) < 0 ||
            !S_ISDIR(named.st_mode) || !S_ISDIR(resolved.st_mode) ||
            named.st_uid != uid || named.st_gid != uid || resolved.st_uid != uid || resolved.st_gid != uid ||
            (named.st_mode & 0077) != 0 || (resolved.st_mode & 0077) != 0 ||
            named.st_dev != resolved.st_dev || named.st_ino != resolved.st_ino) return 0;
    return 1;
}

static int fixed_arguments(const char *entry, char *const argv[], int count, uid_t uid, const char *data) {
    char number[32], expected[PATH_MAX], actual_launch[PATH_MAX];
    const char *base = strrchr(entry, '/');
    if (count != 8 || !base || strcmp(base + 1, "libcodex_app_bootstrap.so") != 0 ||
            strncmp(entry, "/data/app/", 10) != 0 || strcmp(argv[0], entry) != 0 ||
            strcmp(argv[1], "--app-runtime-v1") != 0) return 0;
    snprintf(number, sizeof(number), "%u", (unsigned)uid);
    if (strcmp(argv[2], number) != 0 || !same_private_data(argv[3], data, uid)) return 0;
    snprintf(number, sizeof(number), "%d", (int)getpid());
    if (strcmp(argv[4], number) != 0 || strlen(argv[5]) != 32 ||
            strspn(argv[5], "0123456789abcdef") != 32 || strncmp(argv[6], "/data/app/", 10) != 0) return 0;
    int length = snprintf(expected, sizeof(expected), "%s/com_ai_codex_exec/%s/launch.json", data, argv[5]);
    return length > 0 && (size_t)length < sizeof(expected) && strcmp(argv[7], expected) == 0 &&
            realpath(argv[7], actual_launch) != NULL && strcmp(actual_launch, argv[7]) == 0;
}

static void failure(JNIEnv *env, const char *message) {
    jclass type = (*env)->FindClass(env, "java/io/IOException");
    if (type != NULL) (*env)->ThrowNew(env, type, message);
}

/* Restore this process's own dumpable flag so its siblings become visible on
 * Android's hidepid=invisible /proc mount. See the comment above. Returns the
 * flag the kernel reports afterwards (1 on success), or -1 with an IOException. */
JNIEXPORT jint JNICALL Java_com_ai_codex_shizukuexec_AppNativeSpawn_makeSiblingVisible(
        JNIEnv *env, jclass cls) {
    (void)cls;
    if (prctl(PR_SET_DUMPABLE, 1, 0, 0, 0) != 0) {
        failure(env, "Could not make this application process dumpable");
        return -1;
    }
    /* Report what the kernel actually recorded, so a build can prove the change
     * took effect instead of assuming it. */
    return prctl(PR_GET_DUMPABLE, 0, 0, 0, 0);
}

JNIEXPORT jint JNICALL Java_com_ai_codex_shizukuexec_AppNativeSpawn_launch(
        JNIEnv *env, jclass cls, jstring executable, jobjectArray arguments,
        jint application_uid, jstring canonical_data, jint input, jint output, jint report, jint control) {
    (void)cls;
    if (application_uid < 10000 || !admitted_identity((uid_t)application_uid)) {
        failure(env, "Application transport requires the exact non-root app identity and a filtered or manager-unfiltered sandbox");
        return -1;
    }
    if (!executable || !arguments || !canonical_data) {
        failure(env, "Missing fixed application bootstrap input"); return -1;
    }
    jsize count = (*env)->GetArrayLength(env, arguments);
    if (count != 8) { failure(env, "Invalid fixed application bootstrap argv"); return -1; }
    char *argv[9] = {0};
    int sources[4] = {input, output, report, control};
    int fds[4] = {-1, -1, -1, -1};
    const char *entry = (*env)->GetStringUTFChars(env, executable, NULL);
    if (entry == NULL) return -1;
    const char *data = (*env)->GetStringUTFChars(env, canonical_data, NULL);
    if (data == NULL) { (*env)->ReleaseStringUTFChars(env, executable, entry); return -1; }
    pid_t pid = -1;
    for (jsize i = 0; i < count; ++i) {
        jstring argument = (jstring)(*env)->GetObjectArrayElement(env, arguments, i);
        if (argument == NULL) goto done;
        const char *bytes = (*env)->GetStringUTFChars(env, argument, NULL);
        if (bytes == NULL) { (*env)->DeleteLocalRef(env, argument); goto done; }
        argv[i] = strdup(bytes);
        (*env)->ReleaseStringUTFChars(env, argument, bytes);
        (*env)->DeleteLocalRef(env, argument);
        if (argv[i] == NULL) goto done;
    }
    if (!fixed_arguments(entry, argv, count, (uid_t)application_uid, data)) goto done;
    for (int i = 0; i < 4; ++i) {
        fds[i] = fcntl(sources[i], F_DUPFD_CLOEXEC, 10);
        if (fds[i] < 0) goto done;
    }
    pid = fork();
    if (pid == 0) {
        static char *const empty_environment[] = {NULL};
        for (int i = 0; i < 4; ++i) if (dup2(fds[i], i) < 0) _exit(126);
        if (syscall(__NR_close_range, 4U, UINT_MAX, 0U) < 0) _exit(126);
        if (chdir(data) < 0) _exit(126);
        execve(entry, argv, empty_environment);
        _exit(126);
    }
done:
    for (int i = 0; i < 4; ++i) if (fds[i] >= 0) close(fds[i]);
    for (jsize i = 0; i < count; ++i) free(argv[i]);
    (*env)->ReleaseStringUTFChars(env, canonical_data, data);
    (*env)->ReleaseStringUTFChars(env, executable, entry);
    if (pid < 0 && !(*env)->ExceptionCheck(env)) failure(env, "Application bootstrap fork/admission failed");
    return pid;
}

JNIEXPORT jint JNICALL Java_com_ai_codex_shizukuexec_AppNativeSpawn_waitChild(
        JNIEnv *env, jclass cls, jint pid) {
    (void)cls;
    if (pid <= 0) { failure(env, "No owned application bootstrap child"); return -1; }
    int status;
    pid_t found;
    do { found = waitpid(pid, &status, 0); } while (found < 0 && errno == EINTR);
    if (found != pid) { failure(env, "Application bootstrap ownership could not be reaped"); return -1; }
    return status;
}
