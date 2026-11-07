# 手机操控

前台操控默认使用手机当前屏幕。Android 无障碍服务负责读屏、点击和输入，本机 `phone` MCP 将这些能力提供给 Codex。

## 开启前台操控

1. 在应用的「Android 工具 → 手机操控」打开总开关。
2. 在 Android 无障碍设置中启用 Codex 的手机操控服务。若从旧版本更新，请核对当前服务的开关。
3. 返回桌面并新建对话，让会话加载最新的 MCP 工具。使用 `phone.status` 检查连接、当前模式和任务 ID。

常见流程为 `status` → `screen` → `tap`、`type` 或 `scroll` → `screen` 验证结果 → `finish`。需要用户接手时调用 `handoff`。输入前使用当前屏幕的元素编号，结束时使用当前任务 ID。

## 确认与后台屏

应用名单、敏感元素和用户确认由 Android 端处理。操控中的圆角光效通过无障碍覆盖层显示，暂停、接管、停止和结束时隐藏。熄屏或服务退出会中止任务。未显式结束的任务由空闲超时回收。

后台虚拟屏是可选功能，需要用户在手机操控设置中主动启用并授权对应通道。Root 会检查 UID 和协议，并探测显示与输入。当前真机验证只确认前台服务连接和工具发现，后台兼容性需按 ROM 另行验证。 [设备权限](device-command-policy.md) · [实机范围](compatibility.md)

## 工具发现与来源

桌面启动时通过 app-server 注册 `mcp_servers.phone`，并部署对应技能。桌面内的 relay 使用来宾 Python。更新后旧对话可能保留旧的工具快照，一加 13 上用新会话确认过 `phone` MCP 的 15 个工具可被发现。

模块移植自 dsh-Go，包含其原生读屏、操作策略和任务控制。 [上游版本](../third-party/dsh-go-phone/UPSTREAM.json) · [第三方声明](../third-party/dsh-go-phone/THIRD_PARTY_NOTICES.md)
