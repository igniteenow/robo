<div align="center">

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="assets/brand/robo-lockup-dark.svg">
  <img src="assets/brand/robo-lockup-light.svg" alt="Robo by Ignitee Now" width="420">
</picture>

# Stop chatting with AI. Hand it the work.

Robo runs the commands, reads the files, drives the browser, and checks the result.<br>
Talk to it or type to it, on your computer or your server.

![Windows · macOS · Linux](https://img.shields.io/badge/Windows%20%C2%B7%20macOS%20%C2%B7%20Linux-0E1437?style=for-the-badge)
![Terminal · Desktop · Web · API](https://img.shields.io/badge/Terminal%20%C2%B7%20Desktop%20%C2%B7%20Web%20%C2%B7%20API-3F3E98?style=for-the-badge)

[Install](#install) · [Run it](#run-it) · [What it does](#what-robo-does) · [Make it yours](#make-it-yours)

</div>

---

## Hand it anything

```text
"Go through this 2 GB server log and tell me what broke last night."
"Compare these two CSV exports and list every customer missing from the new one."
"Turn these meeting notes into a to-do list with owners and dates."
"Clean up my Downloads folder and sort everything by type."
"Every morning at 8, send me the top tech news on Telegram."
"Open this .exe and tell me which servers it talks to."
```

Robo plans the job, does it with real tools, checks its work, and asks before
anything risky. It works with the model you choose: OpenAI, Anthropic, Gemini,
DeepSeek, Kimi, OpenRouter and more, or a local model through Ollama or any
OpenAI-compatible server. Everything it learns stays in `~/.robo`
(`%LOCALAPPDATA%\robo` on Windows) on the machine it runs on.

## What Robo does

- **Works from your documents.** Attach logs, notes, code, CSV, JSON, HTML, or
  PowerPoint files of any size, even multi-gigabyte logs. Robo indexes them on
  your machine, works offline, and answers with the exact passages.
- **Talks and listens.** A wake word, hands-free voice chat that adjusts to the
  noise in your room, and spoken replies that start with the first sentence.
  Transcription runs locally by default.
- **Gets real work done.** Coding, research, writing, data work, file cleanup,
  system admin, and security analysis. It runs terminal commands, edits files,
  uses a real browser, and executes code.
- **Looks inside software safely.** Static analysis of programs and binaries with
  Ghidra, radare2, or rizin when installed, and a built-in parser when not. The
  file is never run.
- **Gets sharper with use.** Turns what works into reusable skills and improves
  them, keeps long-term memory, searches past conversations, and learns how you
  like things done.
- **Goes where you are.** Lives on your computer, a home server, or a cloud
  machine. Heavy or risky jobs can run in Docker, over SSH, or in a cloud
  sandbox (Modal, Daytona), so your own machine stays clean. Message it from
  Telegram, WhatsApp, Discord, Slack, and more.
- **Runs on a schedule.** Recurring jobs and parallel sub-agents that work while
  you don't.

## Install

**Linux · macOS · WSL**

```bash
git clone https://github.com/igniteenow/robo
cd robo
bash install-robo.sh
robo model        # pick a model and add its API key
```

On Debian/Ubuntu, voice input also needs `sudo apt install libportaudio2`.

**Windows (PowerShell)**

```powershell
git clone https://github.com/igniteenow/robo
cd robo
Set-ExecutionPolicy -Scope Process Bypass
.\install-robo.ps1
robo model
```

The installer sets up Python and Node, and never overwrites your existing
config, memory, or skills. Voice and other optional features install themselves
the first time you use them. Run `robo doctor` at any time to see
what's missing.
For scripted installs, call `scripts/install.sh` or `scripts/install.ps1`
directly.

## Run it

Pick the way you like to work. All of them share the same sessions, memory, and
settings.

### 1. Terminal (TUI)

```bash
robo              # full-screen terminal interface
robo --cli        # classic line-by-line prompt
robo chat -q "Summarize README.md"   # one question, one answer, no UI
```

### 2. Desktop app

```bash
robo desktop      # builds the app and opens it
```

It works on Windows, macOS, and Linux. The first run builds the app; after that
it opens straight away and rebuilds only when Robo is updated.

### 3. Browser (localhost)

```bash
robo dashboard    # opens http://localhost:9119
```

This gives you chat, settings, API keys, sessions, logs, skills, and MCP servers
in any browser. Useful flags: `--port 8080`, `--no-open`, `--stop`, `--status`.

**Open it from another device (phone, laptop, server):** set a login in
`~/.robo/.env` (`%LOCALAPPDATA%\robo\.env` on Windows), then bind to your
network:

```bash
ROBO_DASHBOARD_BASIC_AUTH_USERNAME=admin
ROBO_DASHBOARD_BASIC_AUTH_PASSWORD=choose-a-strong-password
ROBO_DASHBOARD_BASIC_AUTH_SECRET=<32+ random characters, e.g. from: openssl rand -base64 32>
```

```bash
robo dashboard --host 0.0.0.0 --no-open    # then visit http://<this-machine-ip>:9119
```

Robo refuses to start on a network address without a login. You can also point
the desktop app at this address (Settings → Gateway → Remote gateway) to use a Robo that
runs on another machine.

### 4. HTTP API (OpenAI-compatible)

Use Robo from your own apps, scripts, or chat frontends such as Open WebUI.
Add a key of at least 16 characters to `~/.robo/.env`:

```bash
API_SERVER_KEY=<your-secret-key-16-plus-chars>
```

```bash
robo gateway      # serves http://localhost:8642/v1
```

```bash
curl http://localhost:8642/v1/chat/completions \
  -H "Authorization: Bearer <your-secret-key-16-plus-chars>" \
  -H "Content-Type: application/json" \
  -d '{"model": "robo-engineer", "messages": [{"role": "user", "content": "Hello!"}]}'
```

### 5. Docker (Linux and macOS)

```bash
ROBO_UID=$(id -u) ROBO_GID=$(id -g) docker compose up -d
```

This runs the gateway and the dashboard at `http://localhost:9119`, with your
data in `~/.robo`.

## Everyday commands

| Command / key | What it does |
|---|---|
| `robo model` | Switch model or provider |
| `robo doctor` | Check your setup |
| `robo update` | Update Robo |
| `/help` | List all commands inside a chat |
| `/attach <file>` | Add a document to Robo's knowledge base (TUI) |
| `/voice on` · `/wake on` | Turn on voice chat · the "Hey Roh Boh" wake word |
| `/edit` | Take back your last message and rewrite it (TUI) |

While Robo is working you can just type: your message redirects the task that
is already running.

## Make it yours

Everything is plain files in `~/.robo/` (`%LOCALAPPDATA%\robo\` on Windows),
which you can edit, back up, or copy to another computer:

- **`SOUL.md`**: Robo's personality and rules (tone, how careful it is, house
  style).
- **`memories/USER.md`**: facts about you, so you don't repeat yourself.
- **`memories/MEMORY.md`**: what Robo has learned. It updates on its own, and you can
  also say "remember that…".
- **`skills/`**: reusable procedures. Say "save this as a skill", or run
  `robo skills create <name>`.

## Safety

Before anything consequential, such as deleting files, running a destructive
command, or touching a live system, Robo asks: **Allow once**, **Allow for this
session**, or **Deny**. Every command and result stays visible.

## Status

Version 3.0.1 is a source release. Voice, GPU, and audio behavior depend on
your hardware, so run `robo doctor` after installing.

## License

[MIT](LICENSE) · Built by [Ignitee Now](https://igniteenow.com).

<sub>Based on the MIT-licensed [Hermes Agent](https://github.com/NousResearch/hermes-agent) by Nous Research. See [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).</sub>
