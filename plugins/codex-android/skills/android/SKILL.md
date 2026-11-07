---
name: android
description: 使用 Codex 原生设备桥查询 Android 设备、读写共享文件、读取传感器、剪贴板和只读短信。手机屏幕操控由 phone MCP 提供。
---

# Android 设备工具

先调用 `android_status` 查看真实设备、通道和授权状态。设备能力在启动器的「Android 工具 → 设备能力授权 / Root 模式」中由用户逐项开启。

- 屏幕与 Root 后台屏：使用单独注册的 `phone` MCP，参见手机操控说明。
- Root：`android_device_command` 传入 `channel: "root"` 和 argv 数组，例如 `["getprop", "ro.product.model"]`。原生白名单始终开启，拒绝时返回 `[POLICY_BLOCKED]`。ADB/Shizuku 是手动授权的备用通道。
- 文件：file_list / file_read 访问项目和共享存储；file_export 导出文本或已有文件至 `Download/codex`。手机截图使用 phone MCP 的 screen(image:true)。凭据目录在设备文件接口中拒绝访问。
- 交互：interaction_notify / toast / vibrate / ask / answer / share / open。ask 返回 questionId，answer 返回实际用户选择；pending、cancelled、unknown 不代表同意。
- 感知：sensor_list / sensor_read / location / flashlight。定位和传感器单次读取，默认关闭，逐项授权。
- 剪贴板：clipboard_read / clipboard_write 受系统前台限制。
- 短信：sms_status / sms_search / sms_read，只读、分页查询，需要本次安装的授权及系统 READ_SMS 权限；不覆盖 RCS。没有短信发送或删除入口。

普通 npm、Python、编译器和项目文件操作使用通常的执行工具。设备白名单约束设备桥，不能作为同 UID 代码或已获 Root 的任意程序的操作系统隔离保证。

本机 HTTP 兼容入口是 `127.0.0.1:3090`，Bearer token 位于 `/usr/local/share/codex/android-bridge.json`，`GET /app/help` 返回接口说明，`POST /app/call` 接收 `{op,args}`。优先使用已提供的 MCP 工具。
