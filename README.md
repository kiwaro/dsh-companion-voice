# 桌宠语音

本项目是独立 DSH 插件，给蓝汐桌宠提供后台语音入口。开启后说“嗨大肥鱼”，听到“我在”后即可提问或要求宠物操作电脑。可以直接连说“嗨大肥鱼，跑到右边去”，后续操作由已接入的模型和统一工具执行。

语音配置位于原有宠物设置中的“宠物语音”卡片，不新增聊天面板。首次启用需要准备 DSH 官方 SenseVoice 模型。Windows 原生后台收音不依赖网页一直打开；DSH 和宠物需保持运行。播报改为 CosyVoice 3 本地神经语音，设置中可以直接试听。

识别与播报均在本机完成，不需要语音 API Key。问答继续使用宠物已配置的模型，其费用按原接入方式计算。默认不保存录音及转写。

## 运行环境

- Windows 10/11、Node.js 24.9 以上、Python 3.13。
- DSH 0.2.2 系列，启用官方本地语音输入组件。
- 宠物插件提供 `companionLanxi` 桥接服务。
- CosyVoice 独立 Python 3.10 环境；本机使用 RTX 5080 GPU、PyTorch 2.8.0 CUDA 12.8。

执行 `powershell -ExecutionPolicy Bypass -File scripts/setup.ps1` 准备独立 Python 环境，然后执行 `node scripts/install-local.mjs` 注册到本机 desktop profile。部署脚本会备份原配置，再按需添加官方识别服务和本插件。首次部署还需执行 `powershell -ExecutionPolicy Bypass -File scripts/setup-cosy.ps1`，下载官方 CosyVoice 运行代码、模型和 GPU 依赖。插件负责管理后台 worker 和常驻合成进程。关闭“启用语音”或关闭宠物会释放麦克风，并卸载合成模型。普通停止播报保留模型，避免每句话重新加载。CosyVoice 加载失败时会报告错误，不退回 Windows 系统声音。

## 验证与边界

执行 `powershell -ExecutionPolicy Bypass -File scripts/test.ps1` 运行宿主和语音状态测试。运行记录保存在 `qa`，不发布录音和令牌。

首版使用语音识别结果实现打断；外放回声采用文本过滤，尚不具备硬件 AEC。推荐先使用耳机验证，真人唤醒和外放环境效果须分别实测。不能将合成 WAV 的识别测试当作真人麦克风验收。

完整模块设计、生命周期和验收条件见 [整体设计](docs/整体设计.md)。

后台语音日志保存在当前用户的 `~/.dsh-companion/logs/voice.jsonl`。日志记录进程和工作线程异常、麦克风故障、识别故障、合成故障、指令耗时、连接变化和运行心跳。每个文件上限为 2 MiB，并保留三个轮转文件。连续相同故障每 30 秒最多记录一次。收音或宿主心跳循环超过 10 秒未更新时，独立监测线程会记录线程的代码堆栈。日志只记录诊断状态，不保存语音原文、回答、音频、令牌、异常消息和局部变量。

2026-11-16 的本机交付状态和验证范围见 [验证记录](docs/验证记录.md)。
