#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <limits.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

/* Fixed protocol driver for the UNCHANGED production direct and PTY owners.
 * It never loads user projects or accepts an Intent/remote command. */
static volatile sig_atomic_t stopping;
static int64_t now_ms(void) {
    struct timespec t;
    if (clock_gettime(CLOCK_MONOTONIC, &t)) return -1;
    return (int64_t)t.tv_sec * 1000 + t.tv_nsec / 1000000;
}
static void stop_signal(int signal) { (void)signal; stopping = 1; }
static int write_all(int fd, const void *data, size_t length) {
    const char *cursor = data;
    while (length) {
        ssize_t n = write(fd, cursor, length);
        if (n > 0) { cursor += n; length -= (size_t)n; }
        else if (n < 0 && errno == EINTR) continue;
        else return -1;
    }
    return 0;
}
static int frame(int fd, const char *value) {
    size_t size = strlen(value);
    if (size > 65536) return -1;
    uint32_t n = (uint32_t)size;
    return write_all(fd, &n, 4) || write_all(fd, value, n) ? -1 : 0;
}
static int envelope(const char *cwd, const char *executable, const char *mode, int tty, int wall) {
    int fd = (int)syscall(SYS_memfd_create, "codex-phone-probe", 3U);
    uint64_t limits[8] = {(uint64_t)wall, 0, 0, 65536, 0, 0, 0, 2000};
    uint32_t counts[4] = {2, 4, 24, 80};
    char home[PATH_MAX + 8];
    if (snprintf(home, sizeof(home), "HOME=%s", cwd) >= (int)sizeof(home)) return -1;
    if (fd < 0 || write_all(fd, tty ? "FGBT0001" : "FGBD0001", 8)
            || write_all(fd, limits, sizeof(limits))
            || write_all(fd, counts, tty ? sizeof(counts) : 8)
            || frame(fd, cwd) || frame(fd, executable) || frame(fd, executable) || frame(fd, mode)
            || frame(fd, "PATH=/system/bin") || frame(fd, "LANG=C.UTF-8")
            || frame(fd, home) || frame(fd, "TERM=xterm-256color")
            || fcntl(fd, F_ADD_SEALS, F_SEAL_SEAL | F_SEAL_GROW | F_SEAL_SHRINK | F_SEAL_WRITE) < 0) {
        if (fd >= 0) close(fd);
        return -1;
    }
    return fd;
}
static long number(const char *json, const char *name) {
    char needle[80];
    snprintf(needle, sizeof(needle), "\"%s\":", name);
    const char *found = strstr(json, needle);
    return found ? strtol(found + strlen(needle), NULL, 10) : -1;
}
static void string_json(const char *value) {
    putchar('"');
    for (const unsigned char *p = (const unsigned char *)value; *p; ++p) {
        if (*p == '"' || *p == '\\') printf("\\%c", *p);
        else if (*p < 32 || *p >= 127) printf("\\u%04x", *p);
        else putchar(*p);
    }
    putchar('"');
}
static int nonblock(int fd) {
    int flags = fcntl(fd, F_GETFL);
    return flags < 0 ? -1 : fcntl(fd, F_SETFL, flags | O_NONBLOCK);
}
struct spec {
    const char *name, *mode, *outcome;
    int tty, wall, cancel, missing, exit_code, minimum_reaped;
};

static int run_case(const struct spec *spec, const char *runner, const char *worker, const char *base) {
    char cwd[PATH_MAX], absent[PATH_MAX];
    if (snprintf(cwd, sizeof(cwd), "%s/%s", base, spec->name) >= (int)sizeof(cwd)
            || mkdir(cwd, 0700)) return -1;
    if (snprintf(absent, sizeof(absent), "%s/does-not-exist", cwd) >= (int)sizeof(absent)) return -1;
    int config = envelope(cwd, spec->missing ? absent : worker, spec->mode, spec->tty, spec->wall);
    int control[2] = {-1, -1}, command[2] = {-1, -1}, input[2] = {-1, -1};
    int out[2] = {-1, -1}, err[2] = {-1, -1};
    if (config < 0 || socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, control)
            || socketpair(AF_UNIX, SOCK_SEQPACKET | SOCK_CLOEXEC, 0, command)
            || pipe2(input, O_CLOEXEC) || pipe2(out, O_CLOEXEC) || pipe2(err, O_CLOEXEC)) return -1;
    if (write_all(input[1], "phone-probe\n", 12)) return -1;
    close(input[1]); input[1] = -1;
    pid_t owner = fork();
    if (owner < 0) return -1;
    if (!owner) {
        if (dup2(out[1], 1) < 0 || dup2(err[1], 2) < 0) _exit(121);
        int keep[4] = {config, input[0], control[1], command[1]};
        char args[4][24];
        for (unsigned i = 0; i < 4; ++i) {
            if (fcntl(keep[i], F_SETFD, 0)) _exit(122);
            snprintf(args[i], sizeof(args[i]), "%d", keep[i]);
        }
        for (int fd = 3; fd < 1024; ++fd) {
            int retain = 0;
            for (unsigned i = 0; i < 4; ++i) retain |= keep[i] == fd;
            if (!retain) close(fd);
        }
        char *argv[] = {(char *)runner, args[0], args[1], args[2], args[3], NULL};
        char *env[] = {NULL};
        execve(runner, argv, env);
        dprintf(2, "runner execve failed: errno=%d\n", errno);
        _exit(123);
    }
    close(config); close(input[0]); close(control[1]); close(command[1]); close(out[1]); close(err[1]);
    int fds[3] = {control[0], out[0], err[0]};
    for (unsigned i = 0; i < 3; ++i) if (nonblock(fds[i])) return -1;
    char stdout_data[32768] = {0}, stderr_data[32768] = {0}, result[8192] = {0};
    size_t used[2] = {0, 0};
    size_t scanned = 0;
    int workers[8], worker_fds[8], worker_count = 0;
    int ready = 0, started = 0, cancelled = 0, status = 0, waited = 0, io_error = 0;
    int64_t began = now_ms();
    while (now_ms() - began < 14000) {
        struct pollfd pollfds[3];
        for (unsigned i = 0; i < 3; ++i) pollfds[i] = (struct pollfd){fds[i], POLLIN, 0};
        if (poll(pollfds, 3, 20) < 0 && errno != EINTR) { io_error = 1; break; }
        for (unsigned i = 0; i < 3; ++i) {
            if (fds[i] < 0 || !(pollfds[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
            char data[8192];
            ssize_t n = i == 0 ? recv(fds[i], data, sizeof(data) - 1, MSG_DONTWAIT)
                               : read(fds[i], data, sizeof(data) - 1);
            if (!n) { close(fds[i]); fds[i] = -1; continue; }
            if (n < 0) {
                if (errno != EINTR && errno != EAGAIN && errno != EWOULDBLOCK) {
                    io_error = 1; close(fds[i]); fds[i] = -1;
                }
                continue;
            }
            data[n] = 0;
            if (i == 0) {
                printf("{\"type\":\"runner-event\",\"case\":\"%s\",\"event\":%s}\n", spec->name, data);
                fflush(stdout);
                if (strstr(data, "\"type\":\"ready\"")) {
                    if (ready++ || send(control[0], "P", 1, MSG_NOSIGNAL) != 1) io_error = 1;
                }
                if (strstr(data, "\"type\":\"started\"")) ++started;
                if (strstr(data, "\"type\":\"result\"")) {
                    if (result[0]) io_error = 1;
                    memcpy(result, data, (size_t)n + 1);
                }
            } else {
                char *dest = i == 1 ? stdout_data : stderr_data;
                size_t *count = &used[i - 1];
                if (*count + (size_t)n >= sizeof(stdout_data)) io_error = 1;
                else { memcpy(dest + *count, data, (size_t)n); *count += (size_t)n; dest[*count] = 0; }
            }
        }
        while (scanned < used[0]) {
            char *end = memchr(stdout_data + scanned, '\n', used[0] - scanned);
            if (!end) break;
            if (!strncmp(stdout_data + scanned, "{\"worker\":", 10)) {
                int pid = (int)number(stdout_data + scanned, "pid");
                int known = 0;
                for (int i = 0; i < worker_count; ++i) known |= workers[i] == pid;
                if (pid > 0 && !known && worker_count < 8) {
                    workers[worker_count] = pid;
                    worker_fds[worker_count] = (int)syscall(SYS_pidfd_open, pid, 0);
                    ++worker_count;
                }
            }
            scanned = (size_t)(end - stdout_data) + 1;
        }
        if (!cancelled && ((spec->cancel && worker_count >= 3) || stopping || now_ms() - began > 10000)) {
            if (send(command[0], "T", 1, MSG_NOSIGNAL) != 1) io_error = 1;
            cancelled = 1;
        }
        if (!waited) {
            pid_t actual = waitpid(owner, &status, WNOHANG);
            if (actual == owner) waited = 1;
            else if (actual < 0) { io_error = 1; break; }
        }
        if (waited && fds[0] < 0 && fds[1] < 0 && fds[2] < 0) break;
    }
    int complete = waited && fds[0] < 0 && fds[1] < 0 && fds[2] < 0;
    int gone = 1;
    for (int i = 0; i < worker_count; ++i) {
        struct pollfd p = {worker_fds[i], POLLIN, 0};
        if (p.fd < 0 || poll(&p, 1, 0) != 1 || !(p.revents & POLLIN)) gone = 0;
        if (p.fd >= 0) close(p.fd);
    }
    int owner_exit = waited && WIFEXITED(status) ? WEXITSTATUS(status) : -1;
    int owner_signal = waited && WIFSIGNALED(status) ? WTERMSIG(status) : 0;
    char expected[96];
    snprintf(expected, sizeof(expected), "\"outcome\":\"%s\"", spec->outcome);
    int passed = !io_error && complete && result[0] && gone && strstr(result, expected)
            && strstr(result, "\"cleanupComplete\":true")
            && number(result, "stdoutBytes") == (long)used[0]
            && number(result, "stderrBytes") == (long)used[1]
            && number(result, "reaped") >= spec->minimum_reaped;
    if (spec->missing) passed = passed && owner_exit == 70 && !started
            && strstr(result, "\"started\":false") && number(result, "errno") == ENOENT;
    else passed = passed && owner_exit == 0 && ready == 1 && started == 1
            && strstr(result, "\"started\":true");
    if (spec->exit_code >= 0) passed = passed && number(result, "exitCode") == spec->exit_code;
    if (spec->cancel) passed = passed && cancelled && worker_count == 3;
    if (!strcmp(spec->mode, "pipe") && !spec->missing) {
        char path[PATH_MAX], data[64] = {0};
        snprintf(path, sizeof(path), "%s/roundtrip.txt", cwd);
        int fd = open(path, O_RDONLY | O_CLOEXEC);
        struct stat st;
        passed = passed && fd >= 0 && !fstat(fd, &st) && st.st_uid == getuid()
                && read(fd, data, sizeof(data)) == 12 && !memcmp(data, "phone-probe\n", 12)
                && !strcmp(stdout_data, "OUT:phone-probe\n") && !strcmp(stderr_data, "ERR:probe\n");
        if (fd >= 0) close(fd);
    }
    if (spec->tty) passed = passed && strstr(stdout_data, "TTY:24:80") && strstr(stdout_data, "PTY-INPUT:phone-probe");
    printf("{\"type\":\"case\",\"name\":\"%s\",\"passed\":%s,\"ownerPid\":%d,"
           "\"ownerExit\":%d,\"ownerSignal\":%d,\"actualOwnerWait\":%s,\"allPipesEof\":%s,"
           "\"observedWorkers\":%d,\"observedWorkersExited\":%s,\"elapsedMs\":%lld,\"stdout\":",
           spec->name, passed ? "true" : "false", owner, owner_exit, owner_signal,
           waited ? "true" : "false", complete ? "true" : "false", worker_count,
           gone ? "true" : "false", (long long)(now_ms() - began));
    string_json(stdout_data); printf(",\"stderr\":"); string_json(stderr_data); puts("}"); fflush(stdout);
    /* EOF requests normal cleanup. Unknown cleanup is reported, never forged. */
    close(command[0]);
    for (unsigned i = 0; i < 3; ++i) if (fds[i] >= 0) close(fds[i]);
    return complete ? passed : -1;
}

int main(int argc, char **argv) {
    if (argc != 5 || getuid() == 0) return 90;
    setvbuf(stdout, NULL, _IOLBF, 0);
    signal(SIGPIPE, SIG_IGN);
    struct sigaction action = {.sa_handler = stop_signal};
    sigemptyset(&action.sa_mask);
    if (sigaction(SIGTERM, &action, NULL) || sigaction(SIGINT, &action, NULL)) return 91;
    int seccomp = prctl(PR_GET_SECCOMP, 0, 0, 0, 0);
    printf("{\"type\":\"native-context\",\"uid\":%u,\"pid\":%d,\"ppid\":%d,\"seccomp\":%d}\n",
           getuid(), getpid(), getppid(), seccomp);
    struct spec cases[] = {
        {"pipe-files-exit", "pipe", "exited", 0, 4000, 0, 0, 23, 1},
        {"missing-exec", "pipe", "setup_error", 0, 4000, 0, 1, -1, 0},
        {"cancel-tree", "tree", "cancelled", 0, 4000, 1, 0, -1, 3},
        {"timeout-tree", "tree", "timeout", 0, 750, 0, 0, -1, 3},
        {"orphan-cleanup", "orphan", "exited", 0, 4000, 0, 0, 23, 3},
        {"pty-stdio", "pty", "exited", 1, 4000, 0, 0, 23, 1},
    };
    int successes = 0;
    for (unsigned i = 0; i < sizeof(cases) / sizeof(cases[0]); ++i) {
        int passed = run_case(&cases[i], cases[i].tty ? argv[3] : argv[1], argv[2], argv[4]);
        successes += passed == 1;
        if (passed < 0 || stopping) {
            printf("{\"type\":\"summary\",\"passed\":false,\"reason\":\"setup-or-cleanup-unknown\",\"errno\":%d}\n", errno);
            return 92;
        }
    }
    int passed = successes == 6 && seccomp == 2;
    printf("{\"type\":\"summary\",\"passed\":%s,\"cases\":6,\"successes\":%d,\"appSeccompObserved\":%s}\n",
           passed ? "true" : "false", successes, seccomp == 2 ? "true" : "false");
    return passed ? 0 : 1;
}
