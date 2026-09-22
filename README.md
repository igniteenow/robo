# Robo

**Robo is the AI security engineer that lives on your desktop — built by
[Ignitee Now](https://igniteenow.com).**

Say **"Hey Roh Boh"** and it wakes up: a cross-platform desktop robot and
autonomous engineering workspace that browses, writes and runs code, does deep
research, reverse-engineers binaries, builds its own tools, and remembers
everything across long sessions. It combines a professional terminal UI, a
native desktop app with an animated face, voice, durable conversations, skills,
memory, automation, and real tool execution.

Ignitee Now builds AI-powered penetration testing and proactive security for
small and midsize businesses — defending against attacks before they become
threats. Robo is the same engineering agent that powers that work, released as
open source so anyone can download it and run it.

Robo provides its own product identity, operating behavior, face, wake models,
installers, defaults, terminal experience, and desktop experience. Required
third-party license records are kept separately in
[`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md).

## Robo for iOS

`apps/ios` is a native SwiftUI app (iOS 17+). Run Robo **on the phone** with your own
API key (web research, files, real JavaScript execution, memory, reminders, calendar;
same SOUL.md, same deep-thinking posture, same approval barrier), or **pair it with a
computer** running `robo serve --pair` for the full toolset. See `apps/ios/README.md`.

## What this build does

- Starts with one command: `robo`.
- Provides a full-screen streaming TUI with progress, tool calls, session
  steering, history, and dangerous-action approval choices.
- Provides a native Robo desktop app with the supplied animated face and
  emotion/state changes for listening, thinking, working, success, approval,
  and failure.
- Uses OpenAI, Anthropic/Claude, Kimi, DeepSeek, OpenRouter, Ollama and other
  OpenAI-compatible local or hosted models through the model wizard.
- Executes routine reversible engineering actions without repeatedly asking;
  dangerous or destructive actions use Allow once, Allow for session, permanent
  allowlist, Deny, and full-command review.
- Supports long-running sessions, checkpoints, conversation search, memory,
  reusable skills, task continuation, parallel sub-work, browser and terminal
  tools, and local/SSH/container/sandbox execution backends.
- Bundles the exact ONNX and TFLite wake models supplied for “Hey Roh Boh”. The
  default openWakeWord path is ONNX-only on Linux, avoiding the unavailable
  `tflite-runtime` dependency that broke Python 3.13 Kali installs.

Robo reports observed results and tool evidence; no LLM can honestly guarantee
zero hallucinations, so important actions are configured to be verified.

## Install

Unzip the release into a new directory, then follow [`INSTALL.md`](INSTALL.md).
Robo keeps operator data under `~/.robo` by default. An existing `.env`, config,
memory, skill, or asset is never overwritten by bootstrap.

### Linux, Kali, macOS, WSL

```bash
cd robo
bash install-robo.sh
robo model
robo
```

### Windows PowerShell

```powershell
cd robo
Set-ExecutionPolicy -Scope Process Bypass
.\install-robo.ps1
robo model
robo
```

## First commands

```text
robo                 Open the professional terminal UI
robo model           Choose a cloud or local model and enter its API key
robo desktop         Build and launch the native desktop Robo interface
robo status          Show runtime status
robo assets          Show the installed face and wake-model paths
robo --robo-version  Show Robo and pinned runtime versions
```

Inside the TUI, enter `/wake on` to arm the supplied **Hey Roh Boh** model.
Press `Ctrl+B` for push-to-talk. Paste with the visible **[PASTE]** control,
`Ctrl+V`/`Cmd+V`, or right-click in the composer. Use `/help` for the complete
command list.

## Mission approvals

Robo does not reject security engineering, pentesting, bug-bounty research,
reconnaissance, or exploit-development tasks merely because of their topic.
When a concrete operation is consequential, the terminal, desktop UI, and
spoken interface present the same three choices: **Allow once**, **Allow for
this session**, or **Deny**. A session grant unlocks later guarded operations
for that live mission, so Robo can continue without repeatedly interrupting the
operator. The action feed still shows commands, targets, progress, and results.

## Release status

`3.0.1` is a source release, not a signed public installer. The Python, Robo bootstrap, TUI, desktop renderer, wake-model
packaging, dependency audit, and isolated Windows installer path are tested.
Hardware microphone/speaker availability, display drivers, GPU acceleration,
and package-manager behavior still depend on the target machine and must be
validated on the actual robot hardware before unattended deployment.
