# Codex Credit Limit for Pock

[English](README.md) | [简体中文](README.zh-CN.md)

在 MacBook Touch Bar 上显示 Codex 的 5 小时与每周用量额度、重置时间，以及当前运行中的 Codex 任务数量。

![小组件预览](en/Codex%20Credit%20Limit.pock/Contents/Resources/widget-preview.png)

## 功能

- 显示 5 小时和每周用量窗口
- 显示剩余额度或已用额度
- 显示额度重置时间
- 显示当前运行中的 Codex 任务数量
- 提供简体中文和英文两个 Pock 小组件
- 数据只从本机已登录的 Codex App 或 CLI 读取，不包含 API 密钥

## 系统要求

- macOS 10.15 或更高版本
- Apple Silicon Mac（仓库内的预编译组件为 `arm64`）
- 已安装并登录 Codex App 或 Codex CLI
- Pock

## 安装

1. 下载或克隆本仓库。
2. 选择需要的语言版本：
   - `简中/Codex 额度.pock`
   - `en/Codex Credit Limit.pock`
3. 双击 `.pock` 文件，并在 Pock 中完成安装。

## 工作方式

小组件通过本机 Codex App Server 读取账户的用量窗口，并将最近一次成功结果缓存在：

```text
~/Library/Caches/CodexTouchBar/
```

它还会读取本机 `~/.codex/sessions` 中的任务生命周期记录，以计算正在运行的顶层任务数量。所有处理均在本机完成。

## 仓库结构

```text
.
├── 简中/
│   └── Codex 额度.pock/
└── en/
    └── Codex Credit Limit.pock/
```

每个小组件包内包含 Python 后端、预编译的 `arm64` 渲染器和 Pock bundle，以及图标和预览图。

## 作者

[jtan289](https://github.com/jtan289)

## 许可证

本项目采用 MIT 许可证，详情请参阅 [LICENSE](LICENSE)。

Codex 和 OpenAI 是 OpenAI 的商标。本社区项目与 OpenAI 无关联，也未获得 OpenAI 的认可或背书。
