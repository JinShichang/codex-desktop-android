#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/types.h>
#include <sys/wait.h>
#include <unistd.h>

static void stay(const char *role) {
    alarm(6); /* Each fixture child is bounded even if the runner crashes. */
    dprintf(1, "{\"worker\":\"%s\",\"pid\":%d,\"ppid\":%d}\n", role, getpid(), getppid());
    for (;;) pause();
}

int main(int argc, char **argv) {
    if (argc != 2) return 80;
    alarm(6);
    if (!strcmp(argv[1], "pipe")) {
        char input[64] = {0};
        ssize_t n = read(0, input, sizeof(input) - 1);
        if (n != 12 || memcmp(input, "phone-probe\n", 12)) return 81;
        int fd = open("roundtrip.txt", O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
        if (fd < 0 || write(fd, input, (size_t)n) != n || fsync(fd) || close(fd)) return 82;
        fd = open("roundtrip.txt", O_RDONLY | O_CLOEXEC);
        char actual[64] = {0};
        if (fd < 0 || read(fd, actual, sizeof(actual)) != n || memcmp(input, actual, (size_t)n) || close(fd)) return 83;
        dprintf(1, "OUT:%s", input);
        dprintf(2, "ERR:probe\n");
        return 23;
    }
    if (!strcmp(argv[1], "tree")) {
        if (setsid() < 0) return 84;
        pid_t child = fork();
        if (child < 0) return 85;
        if (!child) {
            alarm(6);
            if (setpgid(0, 0) < 0) _exit(86);
            pid_t grandchild = fork();
            if (grandchild < 0) _exit(87);
            if (!grandchild) {
                if (setsid() < 0) _exit(88);
                stay("grandchild");
            }
            stay("child");
        }
        stay("leader");
    }
    if (!strcmp(argv[1], "orphan")) {
        int ready[2];
        if (pipe(ready)) return 89;
        pid_t child = fork();
        if (child < 0) return 90;
        if (!child) {
            alarm(6);
            close(ready[0]);
            if (setsid() < 0) _exit(91);
            pid_t grandchild = fork();
            if (grandchild < 0) _exit(92);
            if (!grandchild) {
                alarm(6);
                if (write(ready[1], "R", 1) != 1) _exit(93);
                close(ready[1]);
                stay("orphan");
            }
            _exit(0);
        }
        close(ready[1]);
        char byte;
        if (read(ready[0], &byte, 1) != 1) return 94;
        close(ready[0]);
        return 23;
    }
    if (!strcmp(argv[1], "pty")) {
        struct winsize size;
        if (!isatty(0) || !isatty(1) || !isatty(2) || ioctl(0, TIOCGWINSZ, &size)) return 95;
        if (size.ws_row != 24 || size.ws_col != 80) return 96;
        dprintf(1, "TTY:%u:%u\n", size.ws_row, size.ws_col);
        char input[64] = {0};
        ssize_t n = read(0, input, sizeof(input) - 1);
        if (n != 12 || memcmp(input, "phone-probe\n", 12)) return 97;
        dprintf(1, "PTY-INPUT:%s", input);
        return 23;
    }
    return 98;
}
