# 使用 Agent 部署 Codex Android

在电脑上打开本仓库，让能读取源码、运行终端的编程 Agent 协助构建。告诉它你的电脑系统、手机型号、Android 版本，以及是全新安装还是覆盖升级。本项目只在一加 13 上做过真机测试，公开源码的完整首次安装流程仍待验证。[兼容性与验证](compatibility.md)

## 发给 Agent 的提示词

> 请以当前 Codex Android 仓库为工作目录，按 `docs/build.md`、`docs/build-candidate.md` 和 `recovery/engine/manifest.json` 从源码部署。先运行源码检查，报告缺少的工具和构建输入，再准备匹配版本的原生库、Android 执行器、GNU Codex 后端与桌面客户端。区分候选 APK 和首次安装需要的 Debian 运行环境。覆盖安装前核对签名并保留已有账号和项目数据。安装后分别验证桌面启动、后端响应和本地命令执行，列出实际结果和仍缺少的验证。

## 核对部署结果

1. 在仓库根目录运行 `python -B tools/ci/check-source-integrity.py`。检查电脑是否具备 [构建指南](build.md#android-toolchain) 里的工具链。Linux 原生构建使用 Linux 或 WSL 的 Linux 文件系统。
2. 根据 [后端清单](../recovery/engine/manifest.json) 准备成对的 GNU ARM64 后端和 Code Mode host。从 OpenAI 单独获取当前适配的 Linux ARM64 桌面客户端 `26.1103.31037`。其余原生输入按 [候选包指南](build-candidate.md) 准备。
3. 区分设备已有的运行环境与 [首次启动镜像](build.md#prepare-the-phone-image-for-first-launch)。真机检查按 [兼容性与验证](compatibility.md#设备验收) 记录结果。需要共享项目或手机操控时，在手机系统设置中授权对应功能。

签名密钥、登录资料、运行镜像和生成的 APK 放在本地构建目录。提交仓库时按 [授权说明](../LEGAL.md) 保留源码和第三方声明。
