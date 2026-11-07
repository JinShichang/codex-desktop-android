# Android 设备命令与权限

设备命令由 Android 原生设备桥检查。普通项目命令通过 Codex 执行器运行，前台点击和输入通过 [phone MCP](phone-mcp-dshgo-port.md) 处理。

## 设备命令白名单

- 设备桥接收 argv 数组。App UID、Root、Shizuku 和无线 ADB 使用同一策略，执行前还会复核请求和适用的目标身份。
- 允许有限的 `id`、`whoami`、`uname`、`getprop`、`getenforce`、`uptime`、`free`、`df`、`ps` 及 `pm`、`settings`、`dumpsys` 查询。选项、参数和查询对象以源码为准。
- 按包名停止用户应用时，检查包名、UID、系统应用标记、共享 UID 和安装来源。禁止按 PID 杀进程。
- 未知命令、任意脚本、管道、重定向、系统属性写入、SELinux 变更、分区和格式化等操作返回 `[POLICY_BLOCKED]`。

[白名单实现](../android/app/src/main/java/com/ai/codex/DeviceCommandPolicy.java) · [策略回归检查](../tools/device-policy/run-checks.sh)

### 安装 APK 与复制文件

普通安装使用 `codex_android` 的 `android_install_apk`。Codex 在前台时发送 APK 打开请求，由 Android 按当前默认关联选择安装器。安装和授权提示由选中的安装器处理。工具返回 `installer_opened` 表示已发起打开请求。

安装完成后，`android_package_info` 按准确包名查询当前用户已安装的 `versionCode` 和 `versionName`。该工具通过 Android PackageManager 读取版本，无需 Root。应用声明 `QUERY_ALL_PACKAGES`，以便查询没有启动图标的应用。系统隐藏的包可能仍然查不到。

设备命令也允许 `pm list packages --show-versioncode`，末尾可加包名过滤。现有白名单已允许 `pm path <包名>`、`pm dump <包名>` 和 `dumpsys package <包名>`。后两项仍受 Android 的 `DUMP` 权限约束，普通通道遇到拒绝时会返回 `android_dump_permission_required`。

| argv | 通道 | 范围 |
| --- | --- | --- |
| `["pm", "install", "-r", "/sdcard/Download/app.apk"]` | `root` | 用户明确要求静默安装或 `pm install` 时使用。为当前 Android 用户安装或更新单个 APK，沿用系统签名与版本检查。加 `-R` 时拒绝替换已安装应用。 |
| `["cp", "/sdcard/Download/a.txt", "/sdcard/codex/Projects/"]` | `app` 或 `root` | 复制单个普通文件。目标可以是已有目录或文件路径。写完后替换已有目标文件，也接受 `cp -f`。App 通道需要设备文件授权。 |

两项操作可使用 `/sdcard/` 或 `/storage/emulated/0/` 下的任意子目录，设备桥没有文件大小上限。实际访问由 Android 和已授权的通道决定。路径逐级打开，越界和符号链接会被拒绝。安装或复制结果未知时先查询，再决定是否重试。

## 授权和工具

桌面启动时注册 `codex_android` MCP。先用 `android_status` 查看当前授权状态。需要 Root 通道时，进入「Android 工具 → 其他设备能力 / 文件与传感器」，选择「授权并验证 Root 通道」，并在系统的 Root 管理器授权。Shizuku 和无线 ADB 需手动授权。共享文件访问、传感器、定位、手电筒、剪贴板和只读短信受各自开关及系统权限约束。文件交换限制目录范围并拒绝凭据目录。短信工具提供只读查询。

本机兼容接口绑定 `127.0.0.1:3090`，请求需带 Bearer token。`GET /app/help` 列出接口，`GET /app/status` 返回设备和授权状态，`POST /app/call` 使用相同的原生分发和策略。 [工具定义](../plugins/codex-android/scripts/server.py)

## 权限边界

设备命令白名单约束通过原生设备桥发出的请求。若 Root 管理器授权整个应用 UID，同 UID 的任意代码仍可能直接调用 `su`。一加 13 上的 Root 后台屏、Shizuku 和无线 ADB 尚无完整验收记录。 [系统执行边界](architecture.md#执行边界) · [安全说明](../SECURITY.md)

设备命令策略参考 DSHA 的默认拒绝、参数解析和执行端复核设计。 [DSHA](https://github.com/DSH-APP/DSHA)
