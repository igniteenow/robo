<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/robo-lockup-dark.svg">
  <img src="assets/brand/robo-lockup-light.svg" alt="Robo by Ignitee Now" width="420">
</picture>

# 真正替你把活干完的 AI。

在电脑前把任务交给 Robo，用手机随时查看进度。<br>
它运行在你自己的电脑上，使用真实的工具，遇到有风险的操作会先问你。

![Windows · macOS · Linux](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-0E1437?style=for-the-badge)
![终端 · 桌面 · 浏览器 · 语音 · API](https://img.shields.io/badge/%E7%BB%88%E7%AB%AF%20%C2%B7%20%E6%A1%8C%E9%9D%A2%20%C2%B7%20%E6%B5%8F%E8%A7%88%E5%99%A8%20%C2%B7%20%E8%AF%AD%E9%9F%B3%20%C2%B7%20API-3F3E98?style=for-the-badge)

[安装](#安装) · [运行](#运行) · [随处使用](#随处使用) · [能做什么](#能做什么)

[English](README.md) · [Español](README.es.md) · **中文** · [اردو](README.ur-pk.md)

</div>

---

## 交给它任何事

| 日常 | 技术 |
|---|---|
| "把我的下载文件夹按类型整理好。" | "构建失败了，找出原因并修好。" |
| "把这份会议记录整理成带负责人和截止日期的待办清单。" | "看完这个 2 GB 的服务器日志，告诉我昨晚哪里出了问题。" |
| "每天早上 8 点，通过 Telegram 给我发科技新闻。" | "打开这个 .exe，告诉我它会连接哪些服务器。" |
| "对比这两个表格，列出新表里少了谁。" | "调研 X 的三个最佳方案，做对比并给出来源。" |

Robo 会规划任务，用真实工具（终端、文件、浏览器、代码）完成它，并检查自己的结果；
在任何有风险的操作之前，都会问你 **允许一次 / 本次会话允许 / 拒绝**。
模型由你选择：OpenAI、Anthropic、Gemini、DeepSeek、Kimi、OpenRouter，
或通过 Ollama、任意 OpenAI 兼容服务器运行的本地模型。

## 安装

**Windows（PowerShell）**

```powershell
git clone https://github.com/igniteenow/robo
cd robo
Set-ExecutionPolicy -Scope Process Bypass -Force
.\install-robo.ps1
```

**macOS · Linux · WSL**

```bash
git clone https://github.com/igniteenow/robo
cd robo
bash install-robo.sh
```

然后**打开一个新的终端**，选择你的模型。在 Windows 上安装程序会把 `robo` 加入 PATH；
在 macOS 和 Linux 上，如果 `~/.local/bin` 还不在 PATH 中，安装程序会给出需要添加的那一行。

```bash
robo model        # 选择服务商并粘贴 API 密钥
robo              # 开始对话
```

需要预先安装 `git` 和 Python 3.11、3.12 或 3.13（暂不支持 3.14）。安装程序会自动准备 Node，并且不会覆盖你的配置、记忆或技能。
在 Debian/Ubuntu 上，语音输入还需要 `sudo apt install libportaudio2`。
遇到问题时运行 `robo doctor`。

## 运行

所有使用方式共享同一套会话、记忆和设置。

| 你想要 | 运行 | 得到 |
|---|---|---|
| **终端** | `robo` | 带语音对话的全屏终端应用（经典模式：`robo --cli`） |
| **桌面应用** | `robo desktop` | Windows、macOS、Linux 原生应用。首次运行会构建，之后秒开 |
| **浏览器** | `robo dashboard` | 在 `http://localhost:9119` 使用 Robo：对话、设置、会话、技能、MCP |
| **快速问一句** | `robo chat -q "总结 README.md"` | 一问一答，无界面 |
| **你自己的应用** | `robo gateway` | 兼容 OpenAI 的 API：`http://localhost:8642/v1`（[详情](#http-api)） |

### 语音

在终端和桌面应用里都可以直接和 Robo 说话。语音转文字在你的电脑本地完成。

| 命令 | 作用 |
|---|---|
| `/voice on` | 免手动语音对话。回复会朗读出来，同时在屏幕上显示完整的链接和细节 |
| `/wake on` | 说 **"Hey Roh Boh"** 即可开始说话，无需碰键盘 |

### 桌面应用

- **在 设置 → MCP 中管理 MCP 服务器。** 无需编辑文件即可添加、搜索和切换 Model Context Protocol 服务器。
- **自动更新。** 有新版本时点击 **Update now**：Robo 会关闭、显示进度，完成后自动重新打开。
- **连接另一台机器上的 Robo：** 设置 → 网关 → 远程网关。

## 随处使用

在你的电脑或服务器上运行 Robo，然后在任何浏览器（手机、平板、笔记本）里使用**同一个 Robo 终端**。

```bash
robo dashboard --host 0.0.0.0 --no-open
```

第一次运行时，Robo 会让你创建**用户名和密码**。没有登录，它绝不会在网络地址上提供服务。
然后在另一台设备上打开 `http://<这台电脑的IP>:9119`。

- **Windows：** 用*管理员身份*打开 PowerShell，放行端口一次：
  `New-NetFirewallRule -DisplayName "Robo 9119" -Direction Inbound -Protocol TCP -LocalPort 9119 -Action Allow -Profile Private`
- **在家庭网络之外访问：** 使用 Tailscale 等 VPN，不要在路由器上做端口转发。
- **停止：** `robo dashboard --stop`

你也可以通过 **Telegram、WhatsApp、Discord、Slack** 等给 Robo 发消息：运行 `robo gateway setup`。

## 能做什么

- **基于你的文档工作。** 附加任意大小的日志、笔记、代码、CSV、JSON、HTML 或 PowerPoint 文件（`/attach <文件>`）。Robo 在本地建立索引，并引用原文段落回答。
- **做真正的工作。** 编程、调试、调研、写作、数据处理、文件整理和系统管理——使用真实的终端、文件编辑、真实的浏览器和代码执行。
- **安全地查看软件内部。** 已安装 Ghidra、radare2 或 rizin 时用它们做静态分析，否则使用内置解析器。文件永远不会被运行。
- **越用越聪明。** 把有效的做法保存为可复用的技能，拥有长期记忆，可搜索过去的对话，并学习你喜欢的做事方式。
- **在你休息时工作。** 定时任务（"每天早上 8 点……"）和并行的子代理。
- **保持你的电脑干净。** 繁重或有风险的任务可以在 Docker、SSH 或云沙箱（Modal、Daytona）中运行。

## 常用命令

| 命令 | 作用 |
|---|---|
| `robo model` | 切换模型或服务商 |
| `robo update` | 更新 Robo（或在桌面应用中点击 **Update now**） |
| `robo doctor` | 检查安装情况 |
| `/help` | 对话中的全部命令 |
| `/edit` | 撤回上一条消息并重写 |

Robo 工作时，直接输入即可：你的消息会调整正在进行的任务。

## 按你的方式定制

所有内容都是 `~/.robo`（Windows：`%USERPROFILE%\.robo`）里的普通文件，方便编辑、备份或迁移：

| 文件 | 内容 |
|---|---|
| `SOUL.md` | Robo 的性格和规则：语气、谨慎程度、风格 |
| `memories/USER.md` | 关于你的信息，免得你反复说明 |
| `memories/MEMORY.md` | Robo 学到的东西。会自动更新；你也可以说"记住……" |
| `skills/` | 可复用的操作流程。说"把这个存成技能"即可 |
| `.env` | 你的 API 密钥 |

<details>
<summary><b>HTTP API</b></summary>

<a id="http-api"></a>
在你自己的应用或 Open WebUI 等聊天前端中使用 Robo。在 `~/.robo/.env`（Windows：`%USERPROFILE%\.robo\.env`）
中添加一个至少 16 个字符的密钥：

```bash
API_SERVER_KEY=your-secret-key-16-plus-chars
```

```bash
robo gateway
curl http://localhost:8642/v1/chat/completions \
  -H "Authorization: Bearer your-secret-key-16-plus-chars" \
  -H "Content-Type: application/json" \
  -d '{"model": "robo-engineer", "messages": [{"role": "user", "content": "Hello!"}]}'
```

</details>

<details>
<summary><b>Docker（Linux 和 macOS）</b></summary>

```bash
ROBO_UID=$(id -u) ROBO_GID=$(id -g) docker compose up -d
```

在 `http://localhost:9119` 运行网关和控制台，数据保存在 `~/.robo`。

</details>

## 抢先体验

Robo 3.0.1 正处于抢先体验阶段。欢迎试用并告诉我们你的想法：
[提交 issue](https://github.com/igniteenow/robo/issues) 或发邮件至
[support@igniteenow.com](mailto:support@igniteenow.com)。语音和 GPU 功能取决于你的硬件；
`robo doctor` 会显示可用的功能。

## 许可证

[MIT](LICENSE) · 由 [Ignitee Now](https://igniteenow.com) 打造。

<sub>基于 Nous Research 的 MIT 许可项目 [Hermes Agent](https://github.com/NousResearch/hermes-agent)。详见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)。</sub>
