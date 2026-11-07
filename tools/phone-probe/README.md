# 一加手机普通权限执行器诊断

这是独立离线 APK `com.ai.codex.phoneprobe`，不是完整 Codex。它不声明网络、存储或设备控制权限，通过 Activity 中的 Java ProcessBuilder 启动 APK 自己携带的原生程序，在真实 Android 应用 UID 下验证执行器。

`direct-runner.c` 与 `tty-runner.c` 直接取自当前 Codex 源码，构建时保存原样快照和 SHA-256。新增的 `probe.c` 负责封装现有私有协议、消费实际输出和状态、等待真实 owner，并通过 pidfd 观察已报告的测试子进程退出。`worker.c` 只访问新建的应用私有测试目录；等待型 fixture 的每个子进程都有六秒 alarm，防止 owner 意外崩溃后无限存活。

## 已验证范围

2026-10-23，在一加 PJZ110、Android 17/API 37、Linux 6.6.118、未启用 Landlock 的内核上，6 项测试全部通过。Java 与原生进程 UID 均为 10234，原生进程的 PPID 对应 Java Activity，继承的 seccomp 模式为 2。独立采集器复读文件、验证安装 APK 的哈希，并确认已记录的测试进程不再存活。

| 测试 | 检查 |
| --- | --- |
| pipe-files-exit | 实际 stdin/stdout/stderr、私有文件创建和读取、退出码 23 |
| missing-exec | 真正不存在的可执行文件返回 ENOENT，不发送成功启动事件 |
| cancel-tree | 取消跨进程组、跨会话的三代进程，并验证 owner 和子进程退出 |
| timeout-tree | 750ms 超时后的同类进程树回收 |
| orphan-cleanup | 初始进程退出后回收 double-fork 后代，保留初始退出码 23 |
| pty-stdio | 三个标准 FD 都是终端、24×80 窗口尺寸及实际 PTY 输入 |

这不证明完整 Codex RPC 分流、项目权限、命令中断信号、动态调整 PTY 尺寸、GNU/PRoot 工具、GPU、桌面客户端或长时间后台运行已通过。没有将请求受保护沙箱的操作改成普通权限执行，也没有修改手机的 seccomp 或系统设置。

## 复现

从 Codex 仓库根目录执行，显式选择本地 SDK、JDK 和 NDK；`--output` 必须是本仓库 `work/` 下尚不存在的目录。本次诊断使用 NDK 27.0.12077973、JDK 21、平台 API 37、Build Tools 36.0.0。诊断构建不替代上游生产包要求的 NDK r29。

```powershell
python tools/phone-probe/build.py --sdk "$env:ANDROID_HOME" --jdk "$env:JAVA_HOME" --ndk "$env:ANDROID_HOME/ndk/27.0.12077973" --output work/phone-probe-v1
```

首次安装和启动本次 APK：

```powershell
$DeviceSerial = Read-Host 'ADB device serial'
adb -s $DeviceSerial install work/phone-probe-v1/codex-phone-probe.apk
adb -s $DeviceSerial shell am start -W -n com.ai.codex.phoneprobe/.ProbeActivity
```

每次构建使用新的诊断签名密钥，保存在输出目录，不用于生产包。默认 `adb install` 不覆盖已有包。已有安装的数据、日志和密钥需要单独保留，不能将安装失败当成删除应用的理由。

测试结束后独立采集，不重复启动测试：

```powershell
python tools/phone-probe/collect.py --adb "$env:ANDROID_HOME/platform-tools/adb.exe" --serial $DeviceSerial --build work/phone-probe-v1 --output work/phone-probe-v1-collection
```

构建保留源文件清单、命令日志、APK 与 ELF 哈希。采集保留原始 JSONL、复读文件和 `device-report.json`。诊断签名私钥与中间目录不应进入源码补丁。应用仍安装在手机上，数据只包含本诊断自己创建的 fixture。
