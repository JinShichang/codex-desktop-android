# 架构

Codex Android 将 Linux ARM64 桌面客户端、本地命令执行和 Android 手机操控集成在同一个应用中。桌面渲染、文件访问和命令在手机上执行，模型推理由在线服务完成。

| 层 | 职责 | 源码入口 |
| --- | --- | --- |
| Android 宿主 | 管理显示、触摸、输入法和前台运行服务，负责启动、停止与故障恢复 | [Android 应用](../android/app) |
| Linux 桌面 | PRoot 提供 Debian 用户空间，内嵌 Termux:X11 显示桌面，Mesa 提供图形支持 | [来宾启动脚本](../runtime/guest/codex-session.sh) |
| 本地后端 | GNU ARM64 的 Codex app-server 管理会话，Android 原生执行器处理命令、PTY 和项目文件 | [后端补丁](../recovery/engine) · [执行器构建](../tools/executor) |
| 手机操控 | phone MCP 通过 Android 无障碍操控前台。设备命令等 Android 能力使用独立的授权和策略 | [手机操控](phone-mcp-dshgo-port.md) · [设备命令策略](device-command-policy.md) |

## 客户端与运行时

应用 ID 为 `com.ai.codex`。当前适配 Linux ARM64 桌面客户端 `26.1103.31037` 和基于 `rust-v0.167.0` 的 Codex 后端。桌面客户端从上游单独获取，兼容适配与版本绑定。升级时需核对新客户端的启动入口和工作区适配。GNU app-server 与匹配的 Code Mode host 成对构建。 [后端清单](../recovery/engine/manifest.json) · [构建指南](build.md)

一加 13 配置允许直板机直接显示桌面，首次桌面缩放为 150%。客户端可以自行调整缩放，主窗口启动时请求 F11 全屏。关闭显示窗口和停止 Linux 会话是两个操作，显式停止由运行服务负责处理。 [设备配置](../android/app/src/main/res/values/codex_device_profile.xml) · [兼容性](compatibility.md)

PRoot 使用 Android 的内核和应用 UID。应用私有 Debian 环境的 GNOME 密钥环与 Android Keystore 配合。共享存储需由用户授予 Android 的「所有文件访问」权限，默认共享项目目录是 `/sdcard/codex/Projects`。未授权时使用应用私有项目目录。 [Android 权限说明](device-command-policy.md)

## 执行边界

Android 应用 UID 是主要的系统隔离边界。PRoot 和桌面兼容参数不提供等同于桌面 Linux 的命名空间隔离。一加 13 测试机没有 Landlock，普通 UID 配置可运行对应的项目任务，要求不可用沙箱的请求仍应被拒绝。设备 Root 能力是另一条经用户授权的通道。 [安全说明](../SECURITY.md) · [实机范围](compatibility.md)

Android 仍可因系统资源策略回收 Linux 子进程。前台服务与恢复机制可以帮助重启会话，已中断的命令需要检查实际结果。开发和运行测试分别见 [测试指南](../tests/README.md)。

## 源码目录

Android 宿主在 `android/`，来宾启动和输入桥在 `runtime/guest/`，MCP 插件在 `plugins/`。构建与诊断工具在 `tools/`，上游源码和声明在 `vendor/` 与 `third-party/`。本地构建产物、签名材料和用户数据留在仓库之外或 Git 忽略的目录中。
