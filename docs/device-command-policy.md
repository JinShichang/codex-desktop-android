# Android 设备命令与权限

设备命令由 Android 原生设备桥检查。普通项目命令通过 Codex 执行器运行，前台点击和输入通过 [phone MCP](phone-mcp-dshgo-port.md) 处理。

## 设备命令白名单

- 设备桥接收 argv 数组。App UID、Root、Shizuku 和无线 ADB 使用同一策略，执行前还会复核请求和适用的目标身份。
- 允许有限的 `id`、`whoami`、`uname`、`getprop`、`getenforce`、`uptime`、`free`、`df`、`ps` 及 `pm`、`settings`、`dumpsys` 查询。选项、参数和查询对象以源码为准。
- 按包名停止用户应用时，检查包名、UID、系统应用标记、共享 UID 和安装来源。禁止按 PID 杀进程。
- 未知命令、任意脚本、管道、重定向、系统属性写入、SELinux 变更、分区和格式化等操作返回 `[POLICY_BLOCKED]`。

[白名单实现](../android/app/src/main/java/com/ai/codex/DeviceCommandPolicy.java) · [策略回归检查](../tools/device-policy/run-checks.sh)

## 授权和工具

设备操作使用 `android_*` MCP 工具，先用 `android_status` 查看当前授权状态。Root 需由用户在系统的 Root 管理器授予，Shizuku 和无线 ADB 需手动授权。共享文件访问、传感器、定位、手电筒、剪贴板和只读短信受各自开关及系统权限约束。文件交换限制目录范围并拒绝凭据目录。短信工具提供只读查询。

本机兼容接口绑定 `127.0.0.1:3090`，请求需带 Bearer token。`GET /app/help` 列出接口，`GET /app/status` 返回设备和授权状态，`POST /app/call` 使用相同的原生分发和策略。 [工具定义](../plugins/codex-android/scripts/server.py)

## 权限边界

设备命令白名单约束通过原生设备桥发出的请求。若 Root 管理器授权整个应用 UID，同 UID 的任意代码仍可能直接调用 `su`。一加 13 上的 Root 后台屏、Shizuku 和无线 ADB 尚无完整验收记录。 [系统执行边界](architecture.md#执行边界) · [安全说明](../SECURITY.md)

设备命令策略参考 DSHA 的默认拒绝、参数解析和执行端复核设计。 [DSHA](https://github.com/DSH-APP/DSHA)
