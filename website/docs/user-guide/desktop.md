---
sidebar_position: 3
title: "Desktop App"
description: "The native Robo desktop app — a polished experience for chatting with Robo, with streaming tool output, side-by-side previews, a file browser, voice, cron, profiles, skills, and settings. macOS, Windows, and Linux."
---

# Desktop App

The Robo desktop app is a native app built around the **same** agent you get from the CLI and the gateway — same config, same API keys, same sessions, same skills, same memory. It is not a separate product or a lightweight clone; it uses the same Robo Agent core and settings, and drives it through a modern & thoughtfully designed UI. If you have used `robo` in a terminal, everything you set up there is already here, and anything you do here shows up there.

It runs on **macOS, Windows, and Linux**.

:::tip Which interface is which?
Robo has several front ends that all talk to the same agent:

- **Desktop App** (this page) — a native application with a purpose-built UI for chat, configuration, and management.
- **CLI** (`robo`) and **[TUI](./tui.md)** (`robo --tui`) — terminal interfaces.
- **[Web Dashboard](./features/web-dashboard.md)** (`robo dashboard`) — a browser admin panel; its optional **Chat** tab embeds the TUI through a pseudo-terminal.

Pick whichever fits the moment. They share state, so you can start a session in one and resume it in another.
:::

## Install

Follow the [installation instructions for Robo Desktop](../getting-started/installation.md).

If you already have Robo installed, simply run

```bash
robo desktop
```

That uses your current config, keys, sessions, and skills. The app starts detached from the terminal — close the terminal, the app stays; quit the app to stop it (and its backend).

## What's in the app

The desktop app is organized as a chat-first window with a left sidebar for navigation. It's built to allow managing multiple simultaneous agent conversations, configuring messaging providers, creating artifacts, browsing projects' folder structures, and working on multiple projects at once.

### Chat

The center of the app. You get:

- **Streaming responses** with live tool activity and structured tool-call summaries as the agent works.
- **The same conversation history** as every other Robo surface — sessions started here resume in the CLI/TUI and vice versa.
- **Drag-and-drop files** anywhere in the chat area to attach them to your next message.
- **A right-hand preview rail** — render web pages, files, and tool outputs side by side while you keep chatting.
- **Composer history and queue editing** — press the up/down arrow keys in an empty composer to recall and reuse previous prompts, and edit messages you've queued up before they're sent. Pressing Stop (or Esc) while turns are queued pauses the queue and expands it above the composer; resume it from there, or send, edit, and delete individual entries.
- **A conversation timeline rail** — long chats get a slim rail of markers along the edge of the transcript, one per prompt. Hover it to pop open the list of prompts, click one to jump straight to that point in the conversation. (It appears once the chat has a handful of turns.)
- **Find in page** — press **Cmd/Ctrl+F** to open a find bar that searches the rendered chat transcript. Enter / Shift+Enter (or Cmd/Ctrl+G / Cmd/Ctrl+Shift+G while the bar is open) step through matches; Esc closes it.

#### Status bar

The bar along the bottom of the chat shows live session state and exposes quick controls without opening Settings:

- **Per-session YOLO toggle** — flip YOLO on or off for just this session (matching the TUI). YOLO bypasses the dangerous-command approval prompts, so know what you're turning off — see [Security → YOLO Mode](./security.md#yolo-mode).
- **Context-usage meter** — a live "% full" meter of the session's context window. Click it to open the **Context Usage** popover with a token breakdown by category (system prompt, tool definitions, skills, memory, rules, MCP, subagent definitions, and the conversation itself) so you can see exactly what's eating the window before compression kicks in.
- **Customizable items** — right-click the status bar (**Show in status bar**) to choose what appears: the context meter, workspace, model, approvals, turn/session timers, terminal, Command Center, backend version, and more — or hide the bar entirely (**Cmd/Ctrl+Shift+S** toggles it).

Chatting against a Robo instance on another machine instead of the bundled local backend? See [Connecting to a remote backend](#connecting-to-a-remote-backend) below — and for the full picture of how the remote-hosted dashboard connection works (the auth gate, the `/api/ws` chat socket, and WebSocket close-code triage), see [Web Dashboard → Connecting Robo Desktop to a remote backend](./features/web-dashboard.md#connecting-robo-desktop-to-a-remote-backend).

#### Repository discovery

Robo Desktop discovers local Git repositories for the Projects sidebar by scanning your home directory to a bounded depth. You can change this per profile in **Settings → Workspace**, or in `config.yaml`:

```yaml
desktop:
  repo_scan_enabled: true
  repo_scan_roots: []
  repo_scan_exclude_paths: []
```

- Set `repo_scan_enabled: false` to stop the filesystem scan completely. Existing disk-discovery cache rows for that profile are cleared; explicit projects and repositories inferred from intentional Robo sessions remain available.
- Set `repo_scan_roots` to a list of folders to restrict scanning. An empty list preserves the default home-directory scan.
- Set `repo_scan_exclude_paths` to folders whose complete subtrees should be skipped.

Changing any of these values invalidates only that profile's disk-discovery cache and starts a policy-compliant refresh. **Hide from sidebar** remains a separate per-item curation action.

#### Choosing a model

The model picker lives in the **composer**, just left of the microphone. Click it to switch the model, reasoning effort, and fast mode from one dropdown.

- **The composer picker is sticky UI state and never touches your default.** It's remembered locally (per device) and **follows** across new chats and restarts instead of snapping back to the default — pick a model once and the next `Cmd/Ctrl+N` opens on it. With a live chat, switching models scopes the change to that **current chat**; either way the selection rides along when the session is created/switched and is **never** written to the profile default. (Switching [profiles](#sessions--profiles) reseeds to that profile's own default.)
- **Set the default in Settings → Model.** That "main" model is your **per-profile global default** — it's what new chats, crons, subagents, and auxiliary tasks start from, and it's the only place that writes it. Each [profile](#sessions--profiles) keeps its own default.
- **Per-model effort/fast presets.** Each model remembers its own reasoning effort and fast-mode choice in the desktop app, re-applied to the session whenever you pick that model. These presets are a desktop convenience and don't change crons or subagents.
- **Mid-chat switches reset the prompt cache.** Switching the model inside a live chat means the next message re-reads the whole conversation at full input price (provider prompt caches are keyed to the model). Fine occasionally; on a long chat, a fresh chat on the new model is often cheaper than bouncing back and forth.

### File browser

Explore and preview the working directory without leaving the app — useful for following along as the agent reads, writes, and edits files. Set the initial project directory with `robo desktop --cwd <path>` (or the `ROBO_DESKTOP_CWD` environment variable).

### Artifacts

The **Artifacts** view collects what your sessions generate — **images, files, and links** — into one searchable, browsable gallery. Open it from the sidebar, the command palette (**Artifacts — Browse generated outputs**), or a `nav.artifacts` shortcut you bind yourself. It indexes recent session outputs automatically; every artifact shows which session produced it with a jump back to that chat, and images and files open in a preview with download / open-in-browser / copy actions.

### Windows, tabs & panes

The app is built for working on several things at once:

- **Tabs** — **Cmd/Ctrl+T** opens a new session tab; **Ctrl+Tab** / **Ctrl+Shift+Tab** cycle sessions, and **Ctrl+1…9** (macOS) / **Alt+1…9** (Windows, Linux) jump to a recent session by position — on Windows and Linux **Ctrl+1…9** is the profile switcher, so the two can't share the chord. **Cmd/Ctrl+W** closes the focused tab and **Cmd/Ctrl+Shift+T** reopens the last closed one.
- **Multiple windows** — **Cmd/Ctrl+Shift+N** opens a new window, and any session can be popped out via its context menu (**New window**) or from the command palette. A popped-out window renders that single chat without the global sidebar — handy for parking a long-running session on another monitor. Live agent output streams into every window showing the session.
- **Panes** — **Cmd/Ctrl+B** toggles the left sidebar, **Cmd/Ctrl+J** the right one, and **Cmd/Ctrl+\\** swaps which side the sidebars sit on.

### Terminal

A real terminal lives in the right sidebar, next to the file browser:

- **Ctrl+`** shows the terminal (opening one if none exist); **Ctrl+Shift+`** spawns an additional one. Multiple terminals stack in a tab rail — **Ctrl+Shift+↓/↑** walk between them, **Ctrl+Shift+W** closes the active one.
- **Shells persist while hidden.** Closing or hiding the panel doesn't kill your shell — every open terminal stays mounted with its scrollback and running processes intact until you explicitly close it.
- **Add to chat** — select terminal output and send it into the composer as context for your next message.

### Git review & worktrees

For sessions running inside a Git repository, the app has a built-in source-control surface:

- **Review pane** — **Cmd/Ctrl+G** toggles the working-tree review pane: branch and ahead/behind status, changed files (list or tree view), and diffs scoped to **Uncommitted**, **Branch**, or **Last turn** (just what the agent changed in its most recent turn). Stage/unstage files, revert changes, write a commit message (or **Generate commit message**), then **Commit** or **Commit & Push** — and **Create PR** via the GitHub CLI (`gh`), or hand the whole thing to the agent with **Ask Robo to open PR**. You can also create and switch branches from here.
- **Worktrees** — **Cmd/Ctrl+Shift+B** (or **New worktree** on a project in the sidebar) creates a Git worktree on a new branch so an agent can work on a parallel copy of the repo without touching your checkout. Worktrees show up as their own lanes under the project; removing one offers to delete the worktree directory (the branch stays) or just hide the lane and leave it on disk, with a force option when it has uncommitted changes.

### Memory Graph

The **Memory Graph** (command palette → *Memory Graph*, or the status-bar item) is an interactive map of what Robo has learned for you — skills and memories laid out as a zoomable node graph with a timeline, filterable by **All / Used / Learned**. A share control exports the map layout as a compact code you can paste to someone else (layout only — none of your memory or skill text is included) and imports codes the same way.

### Quick Entry

Quick Entry is a small always-available composer summoned by a **global hotkey from anywhere on your system** — fire off a prompt without switching to (or even opening) the main window. Enable it in **Settings → Advanced → Quick Entry**; the default shortcut is **Ctrl/Cmd+Shift+Space** and you can set your own (it needs at least one modifier). If another app already owns the chord, the settings row tells you so you can pick a different one.

### Voice

Talk to Robo and hear it back, the same [voice mode](./features/voice-mode.md) available elsewhere. On macOS the OS will prompt once for microphone access.

**Voice chat** (the mic menu's *Start voice chat*, or **Ctrl+B** on macOS / **Alt+B** on Windows and Linux, where Ctrl+B is the sidebar toggle) takes over the chat: while it is on you see only Robo's animated face in a ring that breathes with your microphone, what Robo is doing — *Listening…*, *Got it…*, *Thinking…*, *Speaking…* — and the controls (mute, send now, end). No transcript, no composer, nothing to read: just talk. Everything said still lands in the conversation, and the moment you end the voice chat (say "stop", press the same chord again or click *End voice chat*) the whole exchange is there to read, in the normal chat.

It is built to feel like a conversation, whichever model and voice you use:

- **Listening** never stops. The microphone is opened once for the whole chat, so Robo hears you the instant it finishes talking — and while it is still talking. A spoken turn ends 0.65 s after you go quiet. *Quiet* is measured against the room, which the chat keeps learning the whole time (a fan, a laptop, a boosted mic — even one that switches on mid-chat), so a noisy room neither keeps a turn listening forever nor passes for speech; a click, a tap or a cough is not a turn, and a turn is capped at 30 s of talking. Only your words, with a moment of lead-in, go to speech-to-text (as 16 kHz audio, not a recording of the whole wait), and if you pause mid-thought and carry on before your words were sent, both parts go as one turn. Local speech-to-text is preloaded when the chat starts (and when the "hey robo" ear is armed), decodes greedily, and remembers the language it detected so later turns skip the detection pass.
- **Talk over Robo** any time. The reply pauses the moment you start talking. If it was you, the reply and the turn in flight stop and what you said becomes the next turn; if it was a cough, an "um" or Robo's own voice leaking back from the speakers, the reply picks up exactly where it paused. Saying "stop" ends the chat.
- **Thinking** is short: a spoken turn runs with reasoning off (`voice.reasoning_effort: "none"`, the default — typed turns keep the model's own setting), and Robo answers a spoken question the way it would out loud: the answer first, a few plain sentences, no lists or code.
- **Speaking** begins on the first words. The voice connection is opened the moment your turn is sent, so it is ready before the reply exists; the reply's opening clause is spoken on its own, and every voice — including the free Edge voice — then continues sentence by sentence while the model is still writing. The caption says *Speaking…* only while sound is actually playing (it says *Thinking…* until then), and a voice that stops answering mid-reply ends the turn after 15 s instead of leaving the chat "speaking" for good.
- **Silent otherwise.** The only sound in a voice chat is Robo talking: no completion chime, no interface clicks or thumps (the desktop's haptic cues are audio, and stay off for the whole chat), and the turn-long "thinking" blips are an opt-in (`voice.thinking_sound: ambient`).
- **Numbers, not guesses.** Under the caption, each turn shows where its time went — `words 1.1 s · first word 1.9 s · voice 0.6 s · total 3.6 s · sentence by sentence`: how long your words took to come back (speech-to-text), how long the model took to its first word, how long the voice took to start, and how the audio arrived. `whole reply at once` means the backend serving this window is older than the app — restart it. The same line is logged to the developer console (`[voice] …`).

### Appearance

A fresh chat opens like a blank page with a question on it: the Robo mark, *What should we work on?*, and a big composer in the middle of the chat zone — your first message sends it to the bottom, where it stays for the rest of the conversation. Under the composer, on the left, is the branch of the folder you are working in (click it for the review pane). The composer is a panel you can see on any theme: a lifted fill, a hairline edge and a soft shadow, at rest and docked alike. Robo's animated 3D face appears only in the voice chat view. Light and dark appearance are one click away on the titlebar (the half-moon), and **Settings → Appearance** has System-follow and the theme presets.

### Settings & onboarding

Manage providers, models, tools, and credentials from a real UI instead of editing YAML. First-run onboarding gets you to your first message in seconds. The settings panes cover providers/keys, model selection, toolset configuration, the gateway, and session management. MCP servers live on the **Capabilities** page (**MCP** tab; Settings has an **MCP** entry that opens it): add any server by command or URL, paste an `mcp.json` snippet, or pick one from the catalog, then sign in, test it, and switch its tools on or off.

- **Providers settings pane** — a dedicated place to manage inference providers, with an Accounts / API-keys UX for signing in and storing credentials per provider.
- **Every provider and model in the menus** — the GUI surfaces the full provider list and every model that `robo model` knows about, so you pick from the same catalog the CLI sees rather than a curated subset.
- **xAI Grok OAuth** — Grok is a first-class OAuth provider in the launcher; sign in through the browser flow like the other OAuth providers.
- **Tool-backend installs from the GUI** — run a tool backend's post-setup install steps directly from the app instead of dropping to a terminal.
- **Terminal font picker** — choose an installed font in **Settings → Appearance**. Nerd Fonts such as `MesloLGS NF` render Powerlevel10k separators and icons in both interactive and agent terminals; the setting is saved per profile.
- **Auxiliary-model warning** — if you switch the main model to a new provider while auxiliary tasks (titling, summarization, and similar helpers) are still pinned to another provider, the app warns you so you don't unknowingly split work across two providers.
- **VS Code Marketplace themes** — beyond the built-in theme presets, the appearance settings include a live VS Code Marketplace search: pick any color theme and the app downloads, converts, and installs it as a desktop theme. The same importer is available from the command palette (*Install theme*), and imported themes can be removed again from the appearance settings.
- **Keep computer awake** — **Settings → Advanced → Keep computer awake** stops the machine from sleeping so long or overnight agent runs keep going (the display can still dim). This is a per-computer setting.

First-run onboarding has been redesigned on a unified overlay design system, and you can pick **Choose provider later** to skip provider setup and get into the app first.

### Management panes

The app also surfaces the broader Robo management surface so you don't have to drop to a terminal:

- **Skills** — browse, install, and manage [skills](./features/skills.md).
- **Memory graph (Star Map)** — type `/journey` (aliases `/learning`, `/memory-graph`) in chat to open an interactive constellation of learned skills and memories over time, with a playback scrubber. Nodes can be edited or deleted right from the panel (skills are archived, memories removed). See [Learning Journey](./features/memory.md#learning-journey-journey).
- **Cron** — view and manage [scheduled jobs](../reference/cli-commands.md#robo-cron).
- **Profiles** — switch between [Robo profiles](./profiles.md) (isolated config/skills/sessions).
- **Messaging** — set up gateway channels.
- **Agents** and **Command Center** — orchestration surfaces for multi-agent work.

### Keyboard & navigation

- **Command palette** — press **Cmd+K** or **Cmd+P** (Ctrl+K / Ctrl+P on Windows/Linux) to jump to actions and navigate the app from the keyboard: open any page or settings section, jump to a session by title or id, switch model/theme/color mode, spawn a terminal, restart the gateway, update Robo, and more.
- **Rebindable shortcuts** — **Settings → Keyboard Shortcuts** (or **Cmd/Ctrl+/**) opens the shortcuts panel where you can remap almost every binding — profile switching, session navigation, view toggles, and any shortcuts contributed by desktop plugins. Duplicate assignments are flagged as conflicts. A few defaults worth knowing: **Cmd/Ctrl+N** new session, **Cmd/Ctrl+.** Command Center, **Cmd/Ctrl+,** Settings, **Cmd/Ctrl+Shift+F** search sessions, **Cmd/Ctrl+1–9** switch profiles, **Shift+X** toggle light/dark.
- **Custom zoom shortcuts** — zoom the interface in half-step increments for finer control over text size.
- **UI language switcher** — change the app's interface language in-app, including Simplified Chinese (zh-Hans).

### Sessions & profiles

- **Session-list overhaul** — a reworked session list with archiving and general session hygiene to keep the list manageable as it grows.
- **Search sessions by id** — find a specific session directly by its id.
- **Concurrent multi-profile sessions** — run sessions across multiple [profiles](./profiles.md) at the same time, and reference a session in another profile with cross-profile `@session` links.

## Updating

The app checks for updates in the background and offers a one-click update when one is ready.

The [manual update process](/getting-started/updating) also works with the GUI.

## Uninstalling

Open **Settings → About → Danger zone** and pick how much to remove:

- **Uninstall Chat GUI only** — removes the desktop app and its data; the Robo agent, your config, and your chats stay. (Same as `robo uninstall --gui`.)
- **Uninstall GUI + agent, keep my data** — removes the app and the agent but keeps config, chats, and secrets for a future reinstall. (Same as `robo uninstall`.)
- **Uninstall everything** — removes the app, the agent, and all user data. (Same as `robo uninstall --full`.)

The app closes to finish the job (the cleanup runs after it exits so it can remove the running app bundle and its own venv). The agent-removing options are hidden automatically when no local agent is installed (for example, a GUI-only "lite" client connected to a remote backend).

You can do the same from the terminal — `robo uninstall --gui` for the GUI alone, or `robo uninstall` / `robo uninstall --full` for the agent too.

:::note
Running `robo uninstall --gui` from a **source checkout** (a `robo desktop` dev build) also removes the workspace `node_modules` and `apps/desktop/{dist,release}` build output, since those are GUI build artifacts. They're recoverable with `robo desktop` (or `npm install` + a rebuild) — but if you're actively hacking on the desktop app, expect to reinstall dependencies afterward.
:::

## CLI reference: `robo desktop`

To launch via the CLI, simply run `robo desktop`. By default it installs workspace Node dependencies, builds the current OS's unpacked Electron app, then launches that packaged artifact **detached**: the command returns as soon as the app is up, and the app — with the backend it runs — keeps going after you close the terminal, until you quit it like any other desktop application. Anything the app prints goes to `<ROBO_HOME>/logs/desktop-stdio.log`.

| Flag                 | Description                                                                               |
| -------------------- | ----------------------------------------------------------------------------------------- |
| `--foreground`       | Keep the app attached to this terminal (its output here, exit code mirrored) — for debugging |
| `--skip-build`       | Skip npm install/package and launch the existing unpacked app from `apps/desktop/release` |
| `--force-build`      | Force a full rebuild even if the content stamp matches                                    |
| `--build-only`       | Build the desktop app but do not launch it (used by `robo update`)                      |
| `--source`           | Launch via `electron .` against `apps/desktop/dist` instead of the packaged app           |
| `--cwd PATH`         | Initial project directory for desktop chat sessions (sets `ROBO_DESKTOP_CWD`)           |
| `--robo-root PATH` | Override the Robo source root the app uses (sets `ROBO_DESKTOP_ROBO_ROOT`)          |
| `--ignore-existing`  | Force the app to ignore any `robo` CLI already on `PATH` during backend resolution      |
| `--fake-boot`        | Enable deterministic boot delays for validating the startup UI                            |

## How it works

The packaged app ships the Electron shell and a native React chat surface. On first launch it can install the Robo Agent runtime into `ROBO_HOME` (`~/.robo`, or `%LOCALAPPDATA%\robo` on Windows) — **the same layout a CLI install uses**, which is why the two are interchangeable. Backend resolution first honours `ROBO_DESKTOP_ROBO_ROOT`, then a completed managed install, then a probed `robo` on `PATH` (unless `--ignore-existing` / `ROBO_DESKTOP_IGNORE_EXISTING=1` is set), and finally an explicit `ROBO_DESKTOP_ROBO` command override for packagers such as Nix. The React renderer talks to a headless backend the app launches for you — a `robo serve` process that serves the `tui_gateway` JSON-RPC/WebSocket API — and reuses the agent runtime rather than embedding `robo --tui`. The desktop app is **self-contained**: it runs its own `robo serve` backend and never opens or requires the [web dashboard](./features/web-dashboard.md). (Runtimes older than the `serve` command fall back to a headless `dashboard --no-open` automatically, so an app update never outruns its backend.) Install, backend-resolution, and self-update logic live in the Electron main process.

## Connecting to a remote backend

By default the app starts and manages its own **local** backend. You can instead point it at a Robo backend running on another machine — a VPS, a home server, or a Mini behind Tailscale.

**Settings → Gateway → Connection mode** offers the alternatives to the local gateway:

- **Remote gateway** — enter the URL of a `robo serve` backend you run yourself and sign in. This is the mode the rest of this section walks through.
- **Robo Cloud** — sign in once to Robo Cloud and pick from the agents on your account; no URL to paste. The app discovers your agents (with an organization picker if your account spans several orgs), and connecting to one switches the session over automatically. The status bar shows the cloud connection while it's active.

Connection modes are configured **per profile** — a per-profile override can point one profile at a remote or cloud backend while others stay local (**Use default gateway** removes an override).

:::info The remote backend is a running `robo serve` process
"Remote backend" means a **`robo serve`** server running on the remote machine — that is the process the desktop app connects to. Nothing in this section works unless that backend is actually up and reachable. The desktop app does not start it for you; you (or a `systemd` service) keep `robo serve` running on the remote host, and the app attaches to it. If you also use messaging channels (Telegram, Discord, etc.), the **gateway** is a *separate* long-running process you start independently — see the note after the setup steps.
:::

The connection has two halves: on the backend you protect it with an **auth provider**, and in the app you enter the backend's URL and sign in. Binding the backend to a non-loopback address automatically engages its auth gate, and the provider you configure is what lets the desktop app through.

**Pick a provider based on where the backend lives:**

- **Self-hosted OIDC — preferred for anything reachable beyond your own machine.** Bring your own identity provider (Keycloak, Auth0, Okta, Google, GitHub via an OIDC bridge, etc.), suitable for a VPS, a public host, or any remote backend.
- **Username/password — local / trusted-network use only.** The simplest option when the backend is on the same trusted LAN or reachable only over a VPN (e.g. Tailscale). It protects a single shared credential with no external identity provider, so **do not use it for a dashboard exposed to the public internet** — reach for OAuth there instead.

The rest of this section shows the username/password path because it's the quickest to stand up on a trusted network; for the OAuth path see [Web Dashboard → Self-hosted OIDC provider](./features/web-dashboard.md#self-hosted-oidc-provider).

### On the backend (the remote machine)

Set a username and password, then start the backend bound to a reachable address. The credentials live in `~/.robo/.env` (the secrets file, mode 0600):

```bash
# 1. Set the dashboard login credentials.
cat >> ~/.robo/.env <<'EOF'
ROBO_DASHBOARD_BASIC_AUTH_USERNAME=admin
ROBO_DASHBOARD_BASIC_AUTH_PASSWORD=choose-a-strong-password
# Recommended: a stable signing secret so sessions survive restarts.
# Without it a random key is generated per boot and you'll be logged out
# on every restart.
ROBO_DASHBOARD_BASIC_AUTH_SECRET=$(openssl rand -base64 32)
EOF
chmod 600 ~/.robo/.env

# 2. Run the backend bound to a reachable address. The non-loopback bind
#    engages the auth gate; the username/password provider handles login.
robo serve --host 0.0.0.0 --port 9119
```

On an all-interfaces bind the startup banner lists the URLs other machines can actually use (`Reachable from other machines at: http://192.168.1.20:9119 …`) — those are what you paste into the app; `0.0.0.0` itself is not an address.

Want the same host to serve a **browser** too (a laptop or phone with no desktop app)? Run `robo dashboard --no-open --host 0.0.0.0 --port 9119` instead of `robo serve`: it exposes the same API for the desktop app **and** the [web dashboard](./features/web-dashboard.md) at the same URL, behind the same login.

Keep that `robo serve` process running for as long as you want the desktop app to be able to connect — if it stops, the app can no longer reach the backend. Run it under `systemd`, `tmux`, or your process manager of choice so it survives logout and reboots.

Separately, make sure the **gateway is running** on the remote host if you rely on messaging channels — the `robo serve` backend is what the desktop app talks to, but your Telegram/Discord/Slack gateway sessions are a different process that you start and keep running on their own. See [Messaging](./messaging/index.md) for gateway setup.

Prefer not to keep a plaintext password at rest? Set `ROBO_DASHBOARD_BASIC_AUTH_PASSWORD_HASH` to a scrypt hash instead — compute it with `python -c "from plugins.dashboard_auth.basic import hash_password; print(hash_password('PW'))"`. Full configuration surface (config.yaml keys, every env var, the rate limiter): [Web Dashboard → Username/password provider](./features/web-dashboard.md#usernamepassword-provider-no-oauth-idp).

Running the backend as a systemd service? Give the unit `EnvironmentFile=%h/.robo/.env` so the credentials are in the environment at boot.

:::warning
The backend reads and writes your `.env` (API keys, secrets) and can run agent commands. The **username/password** setup shown above is for a trusted network — never expose a password-protected backend directly to the open internet; put it behind a VPN. [Tailscale](https://tailscale.com/) is the clean option: bind to the machine's tailscale IP (`--host <tailscale-ip>`) and use `http://<tailscale-ip>:9119` as the Remote URL so only your tailnet can reach it. To reach a backend over the public internet, use the **self-hosted OIDC** provider instead.
:::

### In the app

**Settings → Gateway → Remote gateway:**

1. **Remote URL** — `http://<backend-host>:9119` (path prefixes like `/robo` work if you front it with a reverse proxy)
2. **Sign in** — the app detects which provider the backend advertises and adapts the button. For a username/password backend it shows a **Sign in** button that opens a credential form (enter the credentials from step 1). For an OAuth backend it shows **Sign in with `<provider>`**, which runs the provider's browser sign-in. Either way the app ends up with an authenticated session against the backend.
3. **Save and reconnect** — switches the desktop shell onto the remote backend. The session refreshes automatically; you stay signed in across restarts when `ROBO_DASHBOARD_BASIC_AUTH_SECRET` is set.

There is also an environment override for **token-authenticated** backends only — a backend bound to loopback and reached through your own tunnel: set both `ROBO_DESKTOP_REMOTE_URL` and `ROBO_DESKTOP_REMOTE_TOKEN` before launching the app (one without the other is an error). A backend bound to a reachable address is auth-gated and rejects session tokens, so for the password / OIDC setup above use the Gateway settings panel.

:::note Per-profile remote hosts
The remote gateway host is configured per [profile](./profiles.md), so each profile can point at its own remote backend (or stay on its local one). Switching profiles switches which remote host the app connects to.
:::

### Troubleshooting

- **Sign-in fails with 401 / "Invalid credentials"** — the username or password doesn't match the backend's `ROBO_DASHBOARD_BASIC_AUTH_USERNAME` / `ROBO_DASHBOARD_BASIC_AUTH_PASSWORD`. The backend returns the same generic error for an unknown user and a wrong password (no enumeration oracle), so double-check both. Confirm the gate is on with `curl -s http://<host>:9119/api/status | jq '.auth_required, .auth_providers'` — it should report `true` and include `"basic"`.
- **No "Sign in" button — it asks for a session token instead** — the backend's username/password provider isn't active. `/api/status` won't list `"basic"` in `auth_providers`. Make sure both the username and a password (or password hash) are set in `~/.robo/.env` and that the dashboard process actually loaded them.
- **Signed out on every restart** — set `ROBO_DASHBOARD_BASIC_AUTH_SECRET` to a stable value. Without it the token-signing key is regenerated per boot, invalidating all sessions.
- **Connection refused / times out** — the backend bound to `127.0.0.1` (the default) or a firewall/VPN is blocking the port. Bind to `0.0.0.0` or the tailscale IP and open the port to your trusted network.

For the same setup from the web-dashboard angle, see [Web Dashboard → Connecting Robo Desktop to a remote backend](./features/web-dashboard.md#connecting-robo-desktop-to-a-remote-backend); the env vars are catalogued under [Environment Variables → Web Dashboard & Robo Desktop](../reference/environment-variables.md#web-dashboard--robo-desktop).

## Extending the desktop app

The desktop app is contribution-driven — panes, pages, sidebar nav, status-bar
items, palette commands, keybinds, and themes all register through one SDK, and
you can add your own. A plugin is a single ESM file dropped in
`$ROBO_HOME/desktop-plugins/<id>/plugin.js`; the app loads it within seconds and
hot-reloads every save. Manage installed plugins live in **Settings → Plugins**.

See [Desktop Plugin SDK](../developer-guide/desktop-plugin-sdk.md) for the full
reference. (This is separate from the [web dashboard plugin system](./features/extending-the-dashboard.md).)

## Troubleshooting

Boot logs land in `ROBO_HOME/logs/desktop.log` (it includes backend output and recent Python tracebacks) — check it first if the app reports a boot failure. You can also tail it from the CLI:

```bash
robo logs gui -f
```

Common resets:

```bash
# Force a clean first-launch setup (macOS/Linux)
rm "$HOME/.robo/robo-engineer/.robo-bootstrap-complete"

# Rebuild a broken Python venv (macOS/Linux)
rm -rf "$HOME/.robo/robo-engineer/venv"

# Reset a stuck macOS microphone prompt
tccutil reset Microphone com.igniteenow.robo
```

### "Build desktop app" stuck on Electron download

The build downloads the Electron runtime (~114&nbsp;MB) from `github.com/electron/electron/releases`. If the installer hangs on the **Build desktop app** step with the live output repeating `retrying attempt=…`, GitHub is being blocked or throttled on your network (firewall, proxy, or region).

The installer self-heals this automatically: on a failed build it (1) clears a corrupt cached Electron zip and retries, then (2) if it still fails and you haven't set `ELECTRON_MIRROR`, retries once more through `npmmirror.com`, the de-facto Electron community mirror. `@electron/get` SHASUM-checks the download, but the checksums come from the same mirror — that catches a corrupt or partial download, not a compromised mirror. If you'd rather not trust a third-party host, pin your own `ELECTRON_MIRROR` (below); the build never overrides one you've set.

To **choose your own mirror** (e.g. a corporate/trusted one), set `ELECTRON_MIRROR` before installing or rebuild manually — the build honors it and won't override it:

```bash
ELECTRON_MIRROR=https://npmmirror.com/mirrors/electron/ \
  bash -c 'cd "$HOME/.robo/robo-engineer/apps/desktop" && CSC_IDENTITY_AUTO_DISCOVERY=false npm run pack'
```

To clear a corrupt cached zip by hand:

```bash
rm -f "$HOME/Library/Caches/electron"/electron-*.zip   # macOS
rm -f "$HOME/.cache/electron"/electron-*.zip            # Linux
```

## Building from source

If you want to hack on the app itself, install workspace deps from the repo root once, then run the dev server from `apps/desktop`:

```bash
npm install          # from repo root — links apps/desktop, web, apps/shared
cd apps/desktop
npm run dev          # Vite renderer + Electron, which boots the Python backend
```

Point the app at a specific checkout, or sandbox it from your real config:

```bash
ROBO_DESKTOP_ROBO_ROOT=/path/to/clone npm run dev
ROBO_HOME=/tmp/throwaway npm run dev
npm run dev:fake-boot   # exercise the startup overlay with deterministic delays
```

Build installers:

```bash
npm run dist:mac     # DMG + zip
npm run dist:win     # NSIS + MSI
npm run dist:linux   # AppImage + deb + rpm
npm run pack         # unpacked app under release/ (no installer)
```

macOS/Windows signing and notarization run automatically when the relevant credentials are present in the environment (`CSC_LINK` / `CSC_KEY_PASSWORD` / `APPLE_*` for macOS, `WIN_CSC_*` for Windows).

### Windows: the taskbar and Start menu icon from source

On Windows the taskbar button, the Alt-Tab tile and the Start menu's recent-apps row show the **executable's** icon. A packaged Robo.exe has Robo's icon stamped into it (rcedit, from electron-builder's `afterPack` hook); a from-source run (`robo desktop --source`, `npm run dev`) runs the stock `electron.exe`, whose icon is the Electron atom. The source build therefore stamps the same icon and identity onto `node_modules/electron/dist/electron.exe` (`scripts/brand-dev-electron.mjs`, part of `npm run build` and `npm run dev`; `ROBO_DESKTOP_SKIP_EXE_BRAND=1` skips it). `npm ci` extracts a fresh, unbranded binary — the next build re-brands it. A running Robo holds that file open, so `robo desktop --source` stops the running instance before it builds, like a packaged rebuild does.

Windows also takes a taskbar button's icon from the Start Menu shortcut that carries the window's app id; the installer writes that shortcut for the packaged app. A from-source run (`robo desktop --source`, `npm run dev`) has no installer, so the app runs under its own id (`com.igniteenow.robo.source`) and writes its own shortcut — **Robo** in the Start menu, with the Robo mark, pointing at the same Electron + app folder that launched it — the first time it starts. Both the taskbar and the Start menu then show the Robo mark, and toasts work from source too. If a packaged Robo is installed as well, the from-source entry is named **Robo (source)** beside it — an older installed Robo keeps its own Start menu entry and icon until it is uninstalled (Settings → Apps → Robo). A from-source run is recognised by its executable (`electron.exe`), so it gets its own shortcut even though the production main bundle reports itself as packaged. The resolved icon path and the shortcut written are logged at startup (`[icon] window icon: …`, `[icon] wrote Start Menu shortcut …` in the desktop log).

### macOS permissions and local rebuilds (TCC)

macOS remembers permission grants (Full Disk Access, Desktop/Downloads/Documents,
Accessibility, Automation, microphone) against the app's *code-signing identity*,
not its path. Locally built and self-updated apps are signed with a stable
identifier-pinned ad-hoc signature, so grants persist across updates out of the
box.

For the strongest guarantee — a certificate-anchored identity, the same
mechanism yabai/skhd users rely on — create a self-signed code-signing
certificate once and tell Robo to use it:

1. Keychain Access → Certificate Assistant → **Create a Certificate…**
2. Name: `Robo Local Signing`, Identity Type: *Self-Signed Root*,
   Certificate Type: **Code Signing**.
3. `robo config set desktop.macos_signing_identity "Robo Local Signing"`

The next update re-signs the rebuilt app with that certificate; every TCC grant
survives. No Apple Developer account is required. Notarized release builds are
detected and never re-signed.

One-time note: changing the signing identity (including the first update after
this fix) changes the app's identity once, so macOS will re-prompt one final
time. Grants are stable from then on. If a permission gets stuck, reset it with
`tccutil reset All com.igniteenow.robo` and re-grant.

## See also

- [CLI Guide](./cli.md) — the terminal interface
- [TUI](./tui.md) — the modern terminal UI used by `robo --tui` and the dashboard chat tab
- [Web Dashboard](./features/web-dashboard.md) — browser admin panel with an embedded chat tab
- [Configuration](./configuration.md) — config that the desktop app reads and writes
- [Windows (Native)](./windows-native.md) — native Windows install path
