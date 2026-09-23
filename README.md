<div align="center">

<img src="assets/brand/robo-lockup-dark.svg" alt="Robo — by Ignitee Now" width="440">

**The open-source AI security engineer that runs on your own machine.**

Say **"Hey Roh Boh"** and it wakes up. Robo talks, listens, reads files of any
size, browses the web, writes and runs code, and carries a task through from
start to finish — in your terminal, on your desktop, or from a web dashboard.

Built by [**Ignitee Now**](https://igniteenow.com) · Free and open source ·

[Install](#install) · [First steps](#first-steps) · [Features](#what-robo-does) · [How it's licensed](#license)

</div>

---

## What Robo is

Robo is an autonomous AI agent focused on security and engineering work. It runs
**entirely on your computer** — nothing is uploaded to any hosted service — and
connects to the AI model of your choice (OpenAI, Anthropic, DeepSeek, Kimi,
OpenRouter, a local model via Ollama, and more). You bring an API key or a local
model; Robo brings the tools, the memory, the voice, and the safety rails.

Ignitee Now is a cybersecurity company that builds AI-powered penetration
testing and proactive defense for small and midsize businesses. Robo is the
engineering agent behind that work, released as open source so anyone can run,
inspect, and extend it.

## What Robo does

- **Talks and listens.** A hands-free wake word ("Hey Roh Boh"), voice input,
  and spoken replies. All transcription runs locally by default.
- **Reads any file, any size.** Attach a PDF, Word doc, spreadsheet, or a
  multi-gigabyte log with `/attach`; Robo indexes it locally and answers
  questions by quoting the exact passages — no upload, no size limit.
- **Runs real tools.** Terminal commands, file editing, ripgrep search, a full
  browser, background processes, and code execution — with your approval on
  anything consequential.
- **Does security work.** Reconnaissance, threat analysis, reverse-engineering
  of binaries (static analysis, never executing the target), and exploit
  research are treated as legitimate engineering tasks, not refused by topic.
- **Remembers and improves.** Persistent memory across sessions, searchable
  history, and reusable skills it can create and refine over time.
- **Works across surfaces.** A polished terminal UI, a native desktop app with
  an animated face, a web dashboard, and messaging platforms (Telegram,
  Discord, Slack, and more).
- **Automates.** Scheduled jobs, parallel sub-agents for isolated workstreams,
  and multi-model "mixture of agents" mode.

## Install

Robo keeps all your data under `~/.robo`. An existing `.env`, config, memory,
skill, or asset is never overwritten.

### Linux · Kali · macOS · WSL

```bash
cd robo
bash install-robo.sh
robo model      # choose a model and enter its API key
robo            # start
```

On Linux, microphone capture also needs the system audio library:
`sudo apt install libportaudio2` (Debian/Kali/Ubuntu).

### Windows (PowerShell)

```powershell
cd robo
Set-ExecutionPolicy -Scope Process Bypass
.\install-robo.ps1
robo model
robo
```

The installer sets up Python, a managed Node runtime if needed, and the optional
hands-free voice stack. If a voice component has no package for your platform,
Robo still installs — run `robo doctor` afterward to see exactly what, if
anything, is missing and how to add it.

## First steps

| Command | What it does |
|---|---|
| `robo` | Open the terminal interface |
| `robo model` | Choose a cloud or local model and enter its API key |
| `robo desktop` | Build and launch the native desktop app |
| `robo dashboard` | Open the web dashboard in your browser |
| `robo doctor` | Check your setup and report anything missing |
| `robo status` | Show runtime status |
| `robo --robo-version` | Show the Robo and runtime versions |

Inside the terminal interface:

- **`/wake on`** arms "Hey Roh Boh" (off by default, for privacy). Say the
  phrase, then speak your task.
- **`/attach <file>`** adds a document to the knowledge base — drag a file onto
  the terminal to paste its path. `/attach` alone lists what's indexed.
- **`Ctrl+B`** is push-to-talk.
- **`/help`** lists every command.

## Make Robo yours

Robo is meant to be shaped. Everything that gives it an identity, a memory of
you, and new abilities lives as plain files under `~/.robo/`, created for you on
first run. Edit them with any text editor.

### Identity — `~/.robo/SOUL.md`

`SOUL.md` is Robo's character and operating rules: how it talks, how cautious it
is, what it prioritises. It's loaded into every session. Change it and you
change who Robo is — a terse security operator, a patient teacher, a house
style, whatever you need. A default is written on first run; edit it directly,
or ask Robo to "update your SOUL to be more concise" and it will edit the file
for you.

### What Robo knows about you — `~/.robo/USER.md` and `~/.robo/MEMORY.md`

- **`USER.md`** holds durable facts about you: your name, stack, preferences,
  the way you like answers. Robo reads it every session so you don't repeat
  yourself.
- **`MEMORY.md`** is Robo's own long-term memory of the environment and the
  work. Robo writes to it automatically with the `memory` tool as it learns
  things worth keeping, and you can edit it by hand too.

You can also just tell Robo "remember that I deploy on Fridays" and it saves it.

### Abilities — skills in `~/.robo/skills/`

A **skill** is a folder with a `SKILL.md` inside it: a reusable procedure Robo
follows for a kind of task (a recon checklist, a report format, a deploy
routine). Robo loads them automatically and applies the right one when it fits.

Create one:

```bash
robo skills create recon-checklist -d "My standard reconnaissance steps"
# scaffolds ~/.robo/skills/custom/recon-checklist/SKILL.md — edit it, and Robo will use it
robo skills list            # see what's installed
robo skills search <term>   # find community skills
robo skills install <name>  # add one
```

You can also just ask Robo to "save this as a skill" after it does something you
want repeated, and it writes the `SKILL.md` for you.

### Give Robo a document — the knowledge base

Anything you `/attach` (see [First steps](#first-steps)) is indexed under
`~/.robo/knowledge/` and searchable forever — your reports, a codebase, a stack
of PDFs. Robo pulls the relevant passages into a task instead of you pasting
them.

> All of these are just files on your machine. Back up `~/.robo/`, copy it to
> another computer, or put it in version control — that's your entire Robo,
> identity and memory and skills included.

## How Robo handles risky actions

Robo does not refuse security tasks by topic. But when a specific operation is
consequential — deleting files, running a destructive command, hitting a live
target — the terminal, desktop, and voice interfaces all present the same
choice: **Allow once**, **Allow for this session**, or **Deny**. A session grant
lets a live mission continue without repeated prompts. Every command, target,
and result stays visible in the action feed.

No language model can honestly promise zero mistakes, so Robo is built to report
what it actually observed and to verify consequential actions rather than assume
them.

## Release status

**3.0.1 is a source release, not a signed public installer.** The Python
runtime, bootstrap, terminal UI, desktop renderer, wake-model packaging, and the
Windows installer path are tested. Microphone and speaker availability, display
drivers, GPU acceleration, and package-manager behavior depend on your machine
and should be validated there before any unattended deployment. Run `robo
doctor` after installing.

## License

Robo is open source under the [MIT License](LICENSE).

Robo is built on the MIT-licensed [Hermes Agent](https://github.com/NousResearch/hermes-agent)
by Nous Research, refocused for security work by Ignitee Now, with additions
including the knowledge base, voice input across surfaces, the brand and design
system, and a number of reliability and safety fixes. The Robo name, logo, and
first-party code are Ignitee Now's. Required third-party and upstream license
records are kept in [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

The Hermes model, if you use it, carries its own license terms (several Hermes
models are built on Meta's Llama); review those before relying on it.

---

<div align="center">
<sub>Built by <a href="https://igniteenow.com">Ignitee Now</a> — cybersecurity for small and midsize businesses.</sub>
</div>
