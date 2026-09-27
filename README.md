<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/robo-lockup-dark.svg">
  <img src="assets/brand/robo-lockup-light.svg" alt="Robo by Ignitee Now" width="420">
</picture>

# Your AI that actually does the work.

Give Robo a job at your desk, check on it from your phone.<br>
It runs on your own computer, uses real tools, and asks before anything risky.

![Windows · macOS · Linux](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-0E1437?style=for-the-badge)
![Terminal · Desktop · Browser · Voice · API](https://img.shields.io/badge/Terminal%20%C2%B7%20Desktop%20%C2%B7%20Browser%20%C2%B7%20Voice%20%C2%B7%20API-3F3E98?style=for-the-badge)

[Install](#install) · [Run it](#run-it) · [Use it from anywhere](#use-it-from-anywhere) · [What it can do](#what-it-can-do)

**English** · [Español](README.es.md) · [中文](README.zh-CN.md) · [اردو](README.ur-pk.md)

<!-- Demo GIF goes here: start a task on the PC, open the same session on a phone, watch it finish.
<img src="assets/brand/demo.gif" alt="Robo demo" width="720"> -->

</div>

---

## Hand it anything

| Everyday | Technical |
|---|---|
| "Sort my Downloads folder by type." | "Our build is failing. Find out why and fix it." |
| "Turn these meeting notes into a to-do list with owners and dates." | "Go through this 2 GB server log and tell me what broke last night." |
| "Every morning at 8, send me the top tech news on Telegram." | "Open this .exe and tell me which servers it talks to." |
| "Compare these two spreadsheets and list who is missing from the new one." | "Research the three best options for X, compare them, and give me the sources." |

Robo plans the job, does it with real tools (terminal, files, browser, code), checks its own work,
and asks **Allow once / Allow for this session / Deny** before anything risky.
It works with the model you choose: OpenAI, Anthropic, Gemini, DeepSeek, Kimi, OpenRouter,
or a local model through Ollama or any OpenAI-compatible server.

## Install

**Windows (PowerShell)**

```powershell
git clone https://github.com/igniteenow/robo
cd robo
Set-ExecutionPolicy -Scope Process Bypass
.\install-robo.ps1
```

**macOS · Linux · WSL**

```bash
git clone https://github.com/igniteenow/robo
cd robo
bash install-robo.sh
```

Then **open a new terminal** (the installer adds `robo` to your PATH) and pick your model:

```bash
robo model        # choose a provider and paste its API key
robo              # start chatting
```

You need `git`. The installer sets up Python and Node itself and never overwrites your
config, memory, or skills. On Debian/Ubuntu, voice input also needs `sudo apt install libportaudio2`.
If anything looks off, run `robo doctor`. For scripted installs, call
`scripts/install.sh` or `scripts/install.ps1` directly.

## Run it

Every way of running Robo shares the same sessions, memory, and settings.

| You want | Run | You get |
|---|---|---|
| **Terminal** | `robo` | Full-screen terminal app with voice chat (`robo --cli` for the classic prompt) |
| **Desktop app** | `robo desktop` | Native app for Windows, macOS, Linux. The first run builds it, then it opens instantly |
| **Browser** | `robo dashboard` | Robo at `http://localhost:9119`: chat, settings, sessions, skills, MCP |
| **One quick answer** | `robo chat -q "Summarize README.md"` | One question, one answer, no UI |
| **Your own apps** | `robo gateway` | OpenAI-compatible API at `http://localhost:8642/v1` ([details](#http-api)) |

### Voice

Talk to Robo in the terminal and the desktop app. Transcription runs on your machine.

| Command | What it does |
|---|---|
| `/voice on` | Hands-free voice chat. Replies are spoken and shown on screen, with full links and details |
| `/wake on` | Say **"Hey Roh Boh"** to start talking without touching the keyboard |

### Desktop app

- **MCP servers in Settings → MCP.** Add, search, and switch Model Context Protocol servers without editing files.
- **Updates itself.** When a new version is ready, click **Update now**. Robo closes, shows its progress, and reopens when done.
- **Connect to a Robo on another machine:** Settings → Gateway → Remote gateway.

## Use it from anywhere

Run Robo on your PC or a server, then use the **same Robo terminal** from any browser: phone, tablet, or laptop.

```bash
robo dashboard --host 0.0.0.0 --no-open
```

The first time, Robo asks you to create a **username and password**. It never serves a
network address without a login. Then open `http://<this-computer's-IP>:9119` on your other device.

- **Windows:** allow the port once, in PowerShell *as Administrator*:
  `New-NetFirewallRule -DisplayName "Robo 9119" -Direction Inbound -Protocol TCP -LocalPort 9119 -Action Allow -Profile Private`
- **Outside your home network:** use a VPN such as Tailscale. Don't forward the port on your router.
- **Stop it:** `robo dashboard --stop`

You can also message Robo from **Telegram, WhatsApp, Discord, Slack**, and more: run `robo gateway setup`.

## What it can do

- **Works from your documents.** Attach logs, notes, code, CSV, JSON, HTML, or PowerPoint files of any size (`/attach <file>`). Robo indexes them on your machine and answers with the exact passages.
- **Gets real work done.** Coding, debugging, research, writing, data work, file cleanup, and system admin, with a real terminal, file editing, a real browser, and code execution.
- **Looks inside software safely.** Static analysis of programs with Ghidra, radare2, or rizin when installed, or a built-in parser when not. The file is never run.
- **Gets sharper with use.** Saves what works as reusable skills, keeps long-term memory, searches past conversations, and learns how you like things done.
- **Works while you don't.** Scheduled jobs ("every morning at 8…") and parallel sub-agents.
- **Keeps your machine clean.** Heavy or risky jobs can run in Docker, over SSH, or in a cloud sandbox (Modal, Daytona).

## Everyday commands

| Command | What it does |
|---|---|
| `robo model` | Switch model or provider |
| `robo update` | Update Robo (or **Update now** in the desktop app) |
| `robo doctor` | Check your setup |
| `/help` | All commands inside a chat |
| `/edit` | Take back your last message and rewrite it |

While Robo is working, just type: your message steers the task that's already running.

## Make it yours

Everything is plain files in `~/.robo` (Windows: `%USERPROFILE%\.robo`), easy to edit, back up, or move:

| File | What it holds |
|---|---|
| `SOUL.md` | Robo's personality and rules: tone, how careful it is, house style |
| `memories/USER.md` | Facts about you, so you don't repeat yourself |
| `memories/MEMORY.md` | What Robo has learned. Updates itself; you can also say "remember that…" |
| `skills/` | Reusable procedures. Say "save this as a skill" |
| `.env` | Your API keys |

<details>
<summary><b>HTTP API</b></summary>

<a id="http-api"></a>
Use Robo from your own apps or chat frontends such as Open WebUI. Add a key of at least
16 characters to `~/.robo/.env` (Windows: `%USERPROFILE%\.robo\.env`):

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
<summary><b>Docker (Linux and macOS)</b></summary>

```bash
ROBO_UID=$(id -u) ROBO_GID=$(id -g) docker compose up -d
```

Runs the gateway and the dashboard at `http://localhost:9119`, with your data in `~/.robo`.

</details>

## Early access

Robo 3.0.1 is in early access. Try it and tell us what you think:
[open an issue](https://github.com/igniteenow/robo/issues) or email
[support@igniteenow.com](mailto:support@igniteenow.com). Voice and GPU behavior depend on
your hardware; `robo doctor` shows what's available.

## License

[MIT](LICENSE) · Built by [Ignitee Now](https://igniteenow.com).

<sub>Based on the MIT-licensed [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).</sub>
