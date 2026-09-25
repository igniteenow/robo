---
sidebar_position: 1
title: "CLI Commands Reference"
description: "Authoritative reference for Robo terminal commands and command families"
---

# CLI Commands Reference

This page covers the **terminal commands** you run from your shell.

For in-chat slash commands, see [Slash Commands Reference](./slash-commands.md).

## Global entrypoint

```bash
robo [global-options] <command> [subcommand/options]
```

### Global options

| Option | Description |
|--------|-------------|
| `--version`, `-V` | Show version and exit. |
| `--profile <name>`, `-p <name>` | Select which Robo profile to use for this invocation. Overrides the sticky default set by `robo profile use`. |
| `--resume <session>`, `-r <session>` | Resume a previous session by ID or title. |
| `--continue [name]`, `-c [name]` | Resume the most recent session, or the most recent session matching a title. |
| `--worktree`, `-w` | Start in an isolated git worktree for parallel-agent workflows. |
| `--yolo` | Bypass dangerous-command approval prompts. |
| `--pass-session-id` | Include the session ID in the agent's system prompt. |
| `--ignore-user-config` | Ignore `~/.robo/config.yaml` and fall back to built-in defaults. Credentials in `.env` are still loaded. |
| `--ignore-rules` | Skip auto-injection of `AGENTS.md`, `SOUL.md`, `.cursorrules`, memory, and preloaded skills. |
| `--tui` | Launch the [TUI](../user-guide/tui.md) instead of the classic CLI. Equivalent to `ROBO_TUI=1`. Always wins over `display.interface`. |
| `--cli` | Force the classic prompt_toolkit REPL. Use this to override `display.interface: tui` for a single invocation. |
| `--dev` | With `--tui`: run the TypeScript sources directly via `tsx` instead of the prebuilt bundle (for TUI contributors). |

## Top-level commands

| Command | Purpose |
|---------|---------|
| `robo chat` | Interactive or one-shot chat with the agent. |
| `robo model` | Interactively choose the default provider and model. |
| `robo moa` | Configure named Mixture of Agents presets selectable from the model picker. |
| `robo fallback` | Manage fallback providers tried when the primary model errors. |
| `robo gateway` | Run or manage the messaging gateway service. |
| `robo proxy` | Local OpenAI-compatible proxy that attaches OAuth provider credentials. See [Subscription Proxy](../user-guide/features/subscription-proxy.md). |
| `robo egress` | Outbound credential-injection firewall for remote terminal sandboxes (iron-proxy). Disabled by default. See [Egress proxy](../user-guide/egress/iron-proxy.md). |
| `robo lsp` | Manage Language Server Protocol integration (semantic diagnostics for write_file/patch). |
| `robo setup` | Interactive setup wizard for all or part of the configuration. |
| `robo whatsapp` | Configure and pair the WhatsApp bridge. |
| `robo whatsapp-cloud` | Configure the official Meta WhatsApp Business Cloud API adapter (Business account + public webhook required). Distinct from `robo whatsapp` (Baileys personal-account bridge). |
| `robo slack` | Slack helpers (currently: generate the app manifest with every command as a native slash). |
| `robo auth` | Manage credentials — add, list, remove, reset, status, logout. Handles OAuth flows for Codex/Anthropic/xAI. |
| `robo login` / `logout` | **Deprecated** — use `robo auth` instead. |
| `robo send` | Send a one-shot message to a configured messaging platform (Telegram, Discord, Slack, Signal, SMS, …). Useful from shell scripts, cron jobs, CI hooks, and monitoring daemons — no agent loop, no LLM. |
| `robo secrets` | Manage external secret sources (currently Bitwarden Secrets Manager) for pulling API keys at process startup instead of from `~/.robo/.env`. |
| `robo migrate` | Diagnose and (optionally) rewrite `config.yaml` to replace references to retired models or deprecated settings (e.g. `migrate xai`). |
| `robo status` | Show agent, auth, and platform status. |
| `robo cron` | Inspect and tick the cron scheduler. |
| `robo kanban` | Multi-profile collaboration board (tasks, links, dispatcher). |
| `robo project` | Manage named, multi-folder workspaces (projects). Anchors desktop session grouping and, when bound to a kanban board, gives tasks a deterministic worktree + branch convention. State is per-profile. |
| `robo webhook` | Manage dynamic webhook subscriptions for event-driven activation. |
| `robo hooks` | Inspect, approve, or remove shell-script hooks declared in `config.yaml`. |
| `robo doctor` | Diagnose config and dependency issues. |
| `robo security audit` | On-demand supply-chain audit (OSV.dev) for the venv, plugin requirements, and pinned MCP servers. |
| `robo approvals` | Approval-prompt tools — mine approval history into allowlist proposals. |
| `robo dump` | Copy-pasteable setup summary for support/debugging. |
| `robo prompt-size` | Show a byte breakdown of the system prompt + tool schemas (skills index, memory, profile). Runs offline. |
| `robo debug` | Debug tools — upload logs and system info for support. |
| `robo backup` | Back up Robo home directory to a zip file. |
| `robo checkpoints` | Inspect / prune / clear `~/.robo/checkpoints/` (the shadow store used by `/rollback`). Run with no args for a status overview. |
| `robo import` | Restore a Robo backup from a zip file. |
| `robo logs` | View, tail, and filter agent/gateway/error log files. |
| `robo config` | Show, edit, migrate, and query configuration files. |
| `robo skin` | List, switch, and tweak display skins. |
| `robo console` | Open the safe Robo command console. |
| `robo pairing` | Approve or revoke messaging pairing codes. |
| `robo skills` | Browse, install, publish, audit, and configure skills. |
| `robo bundles` | Group several skills under a single `/<name>` slash command. See [Skill Bundles](../user-guide/features/skills.md#skill-bundles). |
| `robo curator` | Background skill maintenance — status, run, pause, pin. See [Curator](../user-guide/features/curator.md). |
| `robo journey` (aliases `learning`, `memory-graph`) | Timeline of learned skills + memories over time. |
| `robo memory` | Configure external memory provider. Plugin-specific subcommands (e.g. `robo honcho`) register automatically when their provider is active. |
| `robo acp` | Run Robo as an ACP server for editor integration. |
| `robo mcp` | Manage MCP server configurations and run Robo as an MCP server. |
| `robo plugins` | Manage Robo Agent plugins (install, enable, disable, remove). |
| `robo tools` | Configure enabled tools per platform. |
| `robo computer-use` | Install or check the Computer Use (cua-driver) backend (macOS/Windows/Linux). |
| `robo pets` | Browse, install, and select [petdex](../user-guide/features/pets.md) animated pets shown across the CLI, TUI, and desktop app. Subcommands: `list`, `install`, `select`, `show`, `off`, `scale`, `remove`, `doctor`. |
| `robo sessions` | Browse, export, prune, rename, and delete sessions. |
| `robo insights` | Show token/cost/activity analytics. |
| `robo import-agent` | Import a Claude Code (`~/.claude`) or Codex CLI (`~/.codex`) setup. |
| `robo dashboard` | Launch the web dashboard for managing config, API keys, and sessions. |
| `robo serve` | Start the Robo backend server (headless; powers the desktop app and remote backends). |
| `robo desktop` (alias `gui`) | Build and launch the native Electron desktop app. |
| `robo profile` | Manage profiles — multiple isolated Robo instances. |
| `robo completion` | Print shell completion scripts (bash/zsh/fish). |
| `robo version` | Show version information. |
| `robo update` | Pull latest code and reinstall dependencies. `--check` previews without installing; `--backup` takes a pre-pull `ROBO_HOME` snapshot. |
| `robo uninstall` | Remove Robo from the system. |

## `robo chat`

```bash
robo chat [options]
```

Common options:

| Option | Description |
|--------|-------------|
| `-q`, `--query "..."` | One-shot, non-interactive prompt. |
| `-m`, `--model <model>` | Override the model for this run. |
| `-t`, `--toolsets <csv>` | Enable a comma-separated set of toolsets. |
| `--provider <provider>` | Force a provider: `auto`, `openrouter`, `openai-codex`, `copilot-acp`, `copilot`, `anthropic`, `gemini`, `huggingface`, `novita` (aliases `novita-ai`, `novitaai`), `openai-api`, `zai`, `kimi-coding`, `kimi-coding-cn`, `minimax`, `minimax-cn`, `minimax-oauth`, `kilocode`, `xiaomi`, `arcee`, `gmi`, `upstage` (alias `solar`), `alibaba`, `alibaba-coding-plan` (alias `alibaba_coding`), `deepseek`, `nvidia`, `ollama-cloud`, `xai` (alias `grok`), `xai-oauth` (alias `grok-oauth`), `qwen-oauth`, `bedrock`, `opencode-zen`, `opencode-go`, `ai-gateway`, `azure-foundry`, `lmstudio`, `stepfun`, `tencent-tokenhub` (alias `tencent`, `tokenhub`). |
| `-s`, `--skills <name>` | Preload one or more skills for the session (can be repeated or comma-separated). |
| `-v`, `--verbose` | Verbose output. |
| `-Q`, `--quiet` | Programmatic mode: suppress banner/spinner/tool previews. |
| `--image <path>` | Attach a local image to a single query. |
| `--resume <session>` / `--continue [name]` | Resume a session directly from `chat`. |
| `--worktree` | Create an isolated git worktree for this run. |
| `--checkpoints` | Enable filesystem checkpoints before destructive file changes. |
| `--yolo` | Skip approval prompts. |
| `--pass-session-id` | Pass the session ID into the system prompt. |
| `--ignore-user-config` | Ignore `~/.robo/config.yaml` and use built-in defaults. Credentials in `.env` are still loaded. Useful for isolated CI runs, reproducible bug reports, and third-party integrations. |
| `--ignore-rules` | Skip auto-injection of `AGENTS.md`, `SOUL.md`, `.cursorrules`, persistent memory, and preloaded skills. Combine with `--ignore-user-config` for a fully isolated run. |
| `--safe-mode` | Troubleshooting mode: disable ALL customizations — user config, rules/memory injection, plugins, shell hooks, and MCP servers (implies `--ignore-user-config` and `--ignore-rules`). Use to isolate whether a problem comes from your setup or from Robo itself. |
| `--source <tag>` | Session source tag for filtering (default: `cli`). Use `tool` for third-party integrations that should not appear in user session lists. |
| `--max-turns <N>` | Maximum tool-calling iterations per conversation turn (default: 500, or `agent.max_turns` in config). |

Examples:

```bash
robo
robo chat -q "Summarize the latest PRs"
robo chat --provider openrouter --model anthropic/claude-sonnet-4.6
robo chat --toolsets web,terminal,skills
robo chat --quiet -q "Return only JSON"
robo chat --worktree -q "Review this repo and open a PR"
robo chat --ignore-user-config --ignore-rules -q "Repro without my personal setup"
robo chat --safe-mode -q "Is this bug mine or Robo'?"
```

### `robo -z <prompt>` — scripted one-shot

For programmatic callers (shell scripts, CI, cron, parent processes piping in a prompt), `robo -z` is the purest one-shot entry point: **single prompt in, final response text out, nothing else on stdout or stderr.** No banner, no spinner, no tool previews, no `Session:` line — just the agent's final reply as plain text.

```bash
robo -z "What's the capital of France?"
# → Paris.

# Parent scripts can cleanly capture the response:
answer=$(robo -z "summarize this" < /path/to/file.txt)
```

Per-run overrides (no mutation to `~/.robo/config.yaml`):

| Flag | Equivalent env var | Purpose |
|---|---|---|
| `-m` / `--model <model>` | `ROBO_INFERENCE_MODEL` | Override the model for this run |
| `--provider <provider>` | _(none)_ | Override the provider for this run |
| `--usage-file <path>` | _(none)_ | Write a JSON usage report after the run (see below) |

```bash
robo -z "…" --provider openrouter --model openai/gpt-5.5
# or:
ROBO_INFERENCE_MODEL=anthropic/claude-sonnet-4.6 robo -z "…"
```

Same agent, same tools, same skills — just strips every interactive / cosmetic layer. If you need tool output in the transcript too, use `robo chat -q` instead; `-z` is explicitly for "I only want the final answer".

#### `--usage-file` — JSON usage report for pipelines

`robo -z "…" --usage-file /path/report.json` writes a machine-readable usage report after the run: `estimated_cost_usd`, `input_tokens` / `output_tokens` / `cache_read_tokens` / `cache_write_tokens` / `reasoning_tokens` / `total_tokens`, `api_calls`, `model`, `provider`, `session_id`, `service_tier`, and `completed` / `failed` flags. The report is written **even when the run fails**, so batch pipelines can always account for spend. It has no effect outside `-z`/`--oneshot`, and a broken usage write never masks the run's own outcome.

```bash
robo -z "summarize this repo" --usage-file /tmp/usage.json
jq .estimated_cost_usd /tmp/usage.json
```

## `robo model`

Interactive provider + model selector. **This is the command for adding new providers, setting up API keys, and running OAuth flows.** Run it from your terminal — not from inside an active Robo chat session.

```bash
robo model
```

Use this when you want to:
- **add a new provider** (OpenRouter, Anthropic, Copilot, DeepSeek, custom, etc.)
- log into OAuth-backed providers (Anthropic, Copilot, Codex, xAI)
- enter or update API keys
- pick from provider-specific model lists
- configure a custom/self-hosted endpoint
- save the new default into config

:::warning robo model vs /model — know the difference
**`robo model`** (run from your terminal, outside any Robo session) is the **full provider setup wizard**. It can add new providers, run OAuth flows, prompt for API keys, and configure endpoints.

**`/model`** (typed inside an active Robo chat session) can only **switch between providers and models you've already set up**. It cannot add new providers, run OAuth, or prompt for API keys.

**If you need to add a new provider:** Exit your Robo session first (`Ctrl+C` or `/quit`), then run `robo model` from your terminal prompt.
:::

### `/model` slash command (mid-session)

Switch between already-configured models without leaving a session:

```
/model                              # Show current model and available options
/model claude-sonnet-4              # Switch model (auto-detects provider)
/model zai:glm-5                    # Switch provider and model
/model custom:qwen-2.5              # Use model on your custom endpoint
/model custom                       # Auto-detect model from custom endpoint
/model custom:local:qwen-2.5        # Use a named custom provider
/model openrouter:anthropic/claude-sonnet-4  # Switch back to cloud
```

By default, `/model` changes apply **to the current session only**. Add `--global` to persist the change to `config.yaml` (or set `model.persist_switch_by_default: true` to make every switch persist):

```
/model claude-sonnet-4 --global     # Switch and save as new default
```

:::info What if I only see OpenRouter models?
If you've only configured OpenRouter, `/model` will only show OpenRouter models. To add another provider (Anthropic, DeepSeek, Copilot, etc.), exit your session and run `robo model` from the terminal.
:::

On a `--global` switch, provider and base URL changes are persisted to `config.yaml` alongside the model. When switching away from a custom endpoint, the stale base URL is cleared to prevent it leaking into other providers.

## `robo gateway`

```bash
robo gateway <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `run` | Run the gateway in the foreground. Recommended for WSL, Docker, and Termux. |
| `start` | Start the installed systemd/launchd background service. |
| `stop` | Stop the service (or foreground process). |
| `restart` | Restart the service. |
| `status` | Show service status. |
| `list` | List **all profiles** and whether each profile's gateway is currently running (with PID where available). Handy when you run multiple profiles side-by-side and want a single overview. |
| `install` | Install as a systemd (Linux) or launchd (macOS) background service. |
| `uninstall` | Remove the installed service. |
| `setup` | Interactive messaging-platform setup. |
| `migrate-legacy` | Remove legacy `robo.service` units left over from pre-rename installs. Profile units (`robo-gateway-<profile>.service`) and unrelated services are never touched. Flags: `--dry-run`, `-y`/`--yes`. |
| `enroll` | Experimental: enroll this gateway with a relay connector and save relay credentials for connector-backed platforms. See [Robo Relay](/user-guide/messaging/relay). |

Options:

| Option | Description |
|--------|-------------|
| `--all` | On `start` / `restart` / `stop`: act on **every profile's** gateway, not just the active `ROBO_HOME`. Useful if you run multiple profiles side-by-side and want to restart them all after `robo update`. |
| `--no-supervise` | On `run`: inside the s6-overlay Docker image, opt out of auto-supervision and use pre-s6 foreground semantics — gateway runs as the container's main process with no auto-restart. No-op outside the s6 image. Equivalent to setting `ROBO_GATEWAY_NO_SUPERVISE=1`. |
| `--external-supervisor` | On `run`: declare that a wrapper-provided process manager owns the foreground gateway. Use this when `sudo`, `env -i`, or another wrapper strips launchd/systemd's native environment marker. In-chat restarts and updates exit back to that manager instead of spawning a detached replacement. |

`--external-supervisor` is a restart-policy contract: an in-chat restart or
service-restart update exits with status `75`, so the wrapper's supervisor must
relaunch the gateway after that nonzero exit. For systemd, use
`Restart=on-failure` or `Restart=always` and do not include `75` in
`RestartPreventExitStatus`; for launchd, configure `KeepAlive` to relaunch after
unsuccessful exits. Without that policy, a requested restart leaves the gateway
stopped.

Relay credentials (`GATEWAY_RELAY_ID`, `GATEWAY_RELAY_SECRET`, `GATEWAY_RELAY_DELIVERY_KEY`, `GATEWAY_RELAY_URL`, optional `GATEWAY_RELAY_WAKE_URL`) are set in the active profile's `.env` or provisioned automatically at boot — see [Relay](/user-guide/messaging/relay#credentials). There is no `robo gateway enroll` subcommand.

:::tip WSL users
Use `robo gateway run` instead of `robo gateway start` — WSL's systemd support is unreliable. Wrap it in tmux for persistence: `tmux new -s robo 'robo gateway run'`. See [WSL FAQ](/reference/faq#wsl-gateway-keeps-disconnecting-or-robo-gateway-start-fails) for details.
:::

## `robo lsp`

```bash
robo lsp <subcommand>
```

Manage the Language Server Protocol integration. LSP runs real
language servers (pyright, gopls, rust-analyzer, …) in the
background and feeds their diagnostics into the post-write check
used by `write_file` and `patch`. Gated on git workspace detection
— LSP only runs when the cwd or edited file is inside a git
worktree.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `status` | Show service state, configured servers, install status. |
| `list` | Print the registry of supported servers. Pass `--installed-only` to skip missing ones. |
| `install <id>` | Eagerly install one server's binary. |
| `install-all` | Install every server with a known auto-install recipe. |
| `restart` | Tear down running clients so the next edit re-spawns. |
| `which <id>` | Print the resolved binary path for one server. |

See [LSP — Semantic Diagnostics](/user-guide/features/lsp) for
the full guide, supported languages, and configuration knobs.

## `robo setup`

```bash
robo setup [model|tts|terminal|gateway|tools|agent] [--non-interactive] [--reset] [--quick] [--reconfigure]
```

**Easiest path:** `robo setup` — pick a provider, authenticate, and go.

**First run:** launches the first-time wizard.

**Returning user (already configured):** drops straight into the full reconfigure wizard — every prompt shows your current value as its default, press Enter to keep or type a new value. No menu.

Jump into one section instead of the full wizard:

| Section | Description |
|---------|-------------|
| `model` | Provider and model setup. |
| `terminal` | Terminal backend and sandbox setup. |
| `gateway` | Messaging platform setup. |
| `tools` | Enable/disable tools per platform. |
| `agent` | Agent behavior settings. |

Options:

| Option | Description |
|--------|-------------|
| `--quick` | On returning-user runs: only prompt for items that are missing or unset. Skip items you already have configured. |
| `--non-interactive` | Use defaults / environment values without prompts. |
| `--reset` | Reset configuration to defaults before setup. |
| `--reconfigure` | Backwards-compat alias — bare `robo setup` on an existing install now does this by default. |

## `robo whatsapp`

```bash
robo whatsapp
```

Runs the WhatsApp pairing/setup flow, including mode selection and QR-code pairing.

## `robo slack`

```bash
robo slack manifest              # print manifest to stdout
robo slack manifest --write      # write to ~/.robo/slack-manifest.json
robo slack manifest --long-description-file AGENTS.md --write
robo slack manifest --slashes-only  # just the features.slash_commands array
```

Generates a Slack app manifest that registers every gateway command in
`COMMAND_REGISTRY` (`/btw`, `/stop`, `/model`, …) as a first-class
Slack slash command — matching Discord and Telegram parity. Paste the
output into your Slack app config at
[https://api.slack.com/apps](https://api.slack.com/apps) → your app →
**Features → App Manifest → Edit**, then **Save**. Slack prompts for
reinstall if scopes or slash commands changed.

| Flag | Default | Purpose |
|------|---------|---------|
| `--write [PATH]` | stdout | Write to a file instead of stdout. Bare `--write` writes `$ROBO_HOME/slack-manifest.json`. |
| `--name NAME` | `Robo` | Bot display name in Slack. |
| `--description DESC` | default blurb | Bot description shown in the Slack app directory. |
| `--long-description TEXT` | unset | Set `display_information.long_description` inline (175–4,000 characters). Incompatible with `--slashes-only`. |
| `--long-description-file PATH` | unset | Read the long description from a UTF-8 text file, preserving its contents exactly. Mutually exclusive with `--long-description` and incompatible with `--slashes-only`. |
| `--slashes-only` | off | Emit only `features.slash_commands` for merging into a manually-maintained manifest. |

Run `robo slack manifest --write` again after `robo update` to pick
up any new commands.


## `robo send`

```bash
robo send --to <target> "message text"
robo send --to <target> --file <path>
echo "message" | robo send --to <target>
robo send --list [platform]
```

Send a one-shot message to a configured messaging platform without spinning up an agent or gateway loop. Reuses the gateway's already-configured credentials (`~/.robo/.env` + `~/.robo/config.yaml`) so ops scripts, cron jobs, CI hooks, and monitoring daemons can post status updates without reimplementing each platform's REST client.

For bot-token platforms (Telegram, Discord, Slack, Signal, SMS, WhatsApp-CloudAPI) no running gateway is required — `robo send` talks directly to the platform's REST endpoint. Plugin platforms that need a persistent adapter still require a live gateway.

| Option | Description |
|--------|-------------|
| `-t`, `--to <TARGET>` | Delivery target. Formats: `platform` (uses home channel), `platform:chat_id`, `platform:chat_id:thread_id`, or `platform:#channel-name`. Examples: `telegram`, `telegram:-1001234567890`, `discord:#ops`, `slack:C0123ABCD`, `signal:+15551234567`. |
| `-f`, `--file <PATH>` | Read the message body from `PATH` (text files only — logs, reports, markdown). Pass `-` to force reading from stdin. To send an image or other binary file, use `MEDIA:<path>` (see below). |
| `-s`, `--subject <LINE>` | Prepend a subject/header line before the message body. |
| `-l`, `--list [platform]` | List configured targets across all platforms (or only the given platform). |
| `-q`, `--quiet` | Suppress stdout on success — useful in scripts (rely on exit code only). |
| `--json` | Emit raw JSON result instead of human-readable output. |

If neither a positional `message` argument nor `--file` is provided, `robo send` reads from stdin when it is not a TTY. Exit codes: `0` on success, `1` on delivery/backend failure, `2` on usage errors.

### Sending images and other media

`--file` is for *text* bodies only. To deliver an image, document, video, or audio file as a native platform attachment, reference it inside the message text with the `MEDIA:<local_path>` directive:

```bash
robo send --to telegram "MEDIA:/tmp/screenshot.png"
robo send --to telegram "Build chart for today MEDIA:/tmp/chart.png"   # with caption
robo send --to discord:#ops "MEDIA:/tmp/report.pdf"
```

By default, image files are sent as photos (platforms like Telegram recompress these). Add `[[as_document]]` to the message to deliver them as uncompressed file attachments instead:

```bash
robo send --to telegram "[[as_document]] MEDIA:/tmp/screenshot.png"
```

Examples:

```bash
robo send --to telegram "deploy finished"
echo "RAM 92%" | robo send --to telegram:-1001234567890
robo send --to discord:#ops --file /tmp/report.md
robo send --to slack:#eng --subject "[CI]" --file build.log
robo send --list                  # all platforms
robo send --list telegram         # filter by platform
```


## `robo secrets`

```bash
robo secrets bitwarden <subcommand>
robo secrets bw <subcommand>          # short alias
```

Pull API keys from an external secret manager at process startup instead of storing them in `~/.robo/.env`. Currently supports **Bitwarden Secrets Manager**. See the full guide: [Bitwarden integration](../user-guide/secrets/bitwarden.md).

`bitwarden` (alias `bw`) subcommands:

| Subcommand | Description |
|------------|-------------|
| `setup` | Interactive wizard: install the pinned `bws` binary, store an access token, and pick a project. Accepts `--project-id`, `--access-token`, and `--server-url` for non-interactive use. |
| `status` | Show current config, binary path/version, and token validation status. |
| `token` | Rotate the access token: validates the new token against Bitwarden before storing it in `.env` (a rejected token changes nothing). Accepts `--access-token` for non-interactive use and `--no-verify` to skip the probe. |
| `sync` | Fetch secrets now and report what changed. Add `--apply` to actually export the secrets into the current shell's environment (default is dry-run). |
| `install` | Download and verify the pinned `bws` binary. `--force` re-downloads even if a managed copy already exists. |
| `disable` | Turn off the Bitwarden integration. |


## `robo migrate`

```bash
robo migrate <type>
```

Diagnose and (optionally) rewrite the active `config.yaml` to replace references to retired models or deprecated settings. A timestamped backup of the original `config.yaml` is taken before any rewrite (skip with `--no-backup`).

| Subcommand | Description |
|------------|-------------|
| `xai` | Scan `config.yaml` for references to xAI models scheduled for retirement on May 15, 2026 and (with `--apply`) rewrite them in-place to the official replacements per the xAI migration guide. Defaults to dry-run. |

Common flags for migration subcommands:

| Flag | Description |
|------|-------------|
| `--apply` | Rewrite `config.yaml` in-place (default: dry-run, no writes). |
| `--no-backup` | Skip the timestamped backup of `config.yaml` when applying. |


## `robo proxy`

```bash
robo proxy <subcommand>
```

Run a local OpenAI-compatible HTTP server that forwards requests to an OAuth-authenticated upstream provider. External apps can point at the proxy with any bearer token; the proxy attaches your real OAuth credentials on the way out.

| Subcommand | Description |
|------------|-------------|
| `start` | Run the proxy in the foreground. Flags: `--provider <xai>` (default `xai`), `--host <addr>` (default `127.0.0.1`; use `0.0.0.0` to expose on LAN), `--port <int>` (default `8645`). |
| `status` | Show which proxy upstreams are ready (credentials present, OAuth valid). |
| `providers` | List available proxy upstream providers. |


## `robo security`

```bash
robo security <subcommand>
```

On-demand vulnerability scan against [OSV.dev](https://osv.dev). Covers the Robo venv (installed PyPI distributions), Python dependencies declared by plugins under `~/.robo/plugins/`, and pinned `npx`/`uvx` MCP servers in `config.yaml`. Does NOT scan globally-installed packages or editor/browser extensions.

| Subcommand | Description |
|------------|-------------|
| `audit` | Run a one-shot supply-chain audit. |

`audit` flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--json` | off | Emit machine-readable JSON instead of human-readable text. |
| `--fail-on <level>` | `critical` | Exit non-zero when any finding meets this severity (`low`, `moderate`, `high`, `critical`). |
| `--skip-venv` | off | Skip scanning the Robo Python venv. |
| `--skip-plugins` | off | Skip scanning plugin requirements files. |
| `--skip-mcp` | off | Skip scanning pinned MCP servers in `config.yaml`. |


## `robo login` / `robo logout` *(Deprecated)*

:::caution
`robo login` has been removed. Use `robo auth` to manage OAuth credentials, `robo model` to select a provider, or `robo setup` for full interactive setup.
:::

## `robo auth`

Manage credential pools for same-provider key rotation. See [Credential Pools](/user-guide/features/credential-pools) for full documentation.

```bash
robo auth                                              # Interactive wizard
robo auth list                                         # Show all pools
robo auth list openrouter                              # Show specific provider
robo auth add openrouter --api-key sk-or-v1-xxx        # Add API key
robo auth add anthropic --type oauth                   # Add OAuth credential
robo auth remove openrouter 2                          # Remove by index
robo auth reset openrouter                             # Clear cooldowns
robo auth status anthropic                             # Show auth status for a provider
robo auth logout anthropic                             # Log out and clear stored auth state
robo auth spotify                                      # Authenticate Robo with Spotify via PKCE
```

Subcommands: `add`, `list`, `remove`, `reset`, `status`, `logout`, `spotify`. When called with no subcommand, launches the interactive management wizard.

## `robo status`

```bash
robo status [--all] [--deep]
```

| Option | Description |
|--------|-------------|
| `--all` | Show all details in a shareable redacted format. |
| `--deep` | Run deeper checks that may take longer. |

## `robo cron`

```bash
robo cron <list|create|edit|pause|resume|run|remove|status|tick>
```

| Subcommand | Description |
|------------|-------------|
| `list` | Show scheduled jobs. |
| `create` / `add` | Create a scheduled job from a prompt, optionally attaching one or more skills via repeated `--skill`. |
| `edit` | Update a job's schedule, prompt, name, delivery, repeat count, or attached skills. Supports `--clear-skills`, `--add-skill`, and `--remove-skill`. |
| `pause` | Pause a job without deleting it. |
| `resume` | Resume a paused job and compute its next future run. |
| `run` | Trigger a job on the next scheduler tick. |
| `remove` | Delete a scheduled job. |
| `status` | Check whether the cron scheduler is running. |
| `tick` | Run due jobs once and exit. |

The cron **trigger** is pluggable via the `cron.provider` config key. Empty
(the default) uses the built-in in-process ticker. Set it to `chronos` (the
NAS-managed provider for scale-to-zero hosted gateways) — configured via the
`cron.chronos.*` keys (`portal_url`, `callback_url`, `expected_audience`,
`nas_jwks_url`) — or name a custom provider under `plugins/cron/<name>/` or
`$ROBO_HOME/plugins/<name>/`. An unknown or unavailable provider falls back to
the built-in, so cron is never left without a trigger. See the
[cron internals](../developer-guide/cron-internals.md#gateway-integration) doc.

## `robo kanban`

```bash
robo kanban [--board <slug>] <action> [options]
```

Multi-profile, multi-project collaboration board. Each install can host many boards (one per project, repo, or domain); each board is a standalone queue with its own SQLite DB and dispatcher scope. New installs start with one board called `default`, whose DB is `~/.robo/kanban.db` for back-compat; additional boards live at `~/.robo/kanban/boards/<slug>/kanban.db`. The gateway-embedded dispatcher sweeps every board per tick.

**Global flags (apply to every action below):**

| Flag | Purpose |
|------|---------|
| `--board <slug>` | Operate on a specific board. Defaults to the current board (set via `robo kanban boards switch`, the `ROBO_KANBAN_BOARD` env var, or `default`). |

**This is the human / scripting surface.** Agent workers spawned by the dispatcher drive the board through a dedicated `kanban_*` [toolset](/user-guide/features/kanban#how-workers-interact-with-the-board) (`kanban_show`, `kanban_complete`, `kanban_block`, `kanban_create`, `kanban_link`, `kanban_comment`, `kanban_heartbeat`; orchestrator profiles also get `kanban_list` and `kanban_unblock`) instead of shelling to `robo kanban`. Workers have `ROBO_KANBAN_BOARD` pinned in their env so they physically cannot see other boards.

| Action | Purpose |
|--------|---------|
| `init` | Create `kanban.db` if missing. Idempotent. |
| `boards list` / `boards ls` | List all boards with task counts. `--json`, `--all` (include archived). |
| `boards create <slug>` | Create a new board. Flags: `--name`, `--description`, `--icon`, `--color`, `--switch` (make active). Slug is kebab-case, auto-downcased. |
| `boards switch <slug>` / `boards use` | Persist `<slug>` as the active board (writes `~/.robo/kanban/current`). |
| `boards show` / `boards current` | Print the currently-active board's name, DB path, and task counts. |
| `boards rename <slug> "<name>"` | Change a board's display name. Slug is immutable. |
| `boards rm <slug>` | Archive (default) or hard-delete a board. `--delete` skips the archive step. Archived boards move to `boards/_archived/<slug>-<ts>/`. Refused for `default`. |
| `create "<title>"` | Create a new task on the active board. Flags: `--body`, `--assignee`, `--parent` (repeatable), `--workspace scratch\|worktree\|dir:<path>`, `--tenant`, `--priority`, `--triage`, `--idempotency-key`, `--max-runtime`, `--max-retries`, `--skill` (repeatable). |
| `list` / `ls` | List tasks on the active board. Filter with `--mine`, `--assignee`, `--status`, `--tenant`, `--archived`, `--json`. |
| `show <id>` | Show a task with comments and events. `--json` for machine output. |
| `assign <id> <profile>` | Assign or reassign. Use `none` to unassign. Refused while task is running. |
| `link <parent> <child>` | Add a dependency. Cycle-detected. Both tasks must be on the same board. |
| `unlink <parent> <child>` | Remove a dependency. |
| `claim <id>` | Atomically claim a ready task. Prints resolved workspace path. |
| `comment <id> "<text>"` | Append a comment. The next worker that claims the task reads it as part of its `kanban_show()` response. |
| `complete <id>` | Mark task done. Flags: `--result`, `--summary`, `--metadata`. |
| `block <id> "<reason>"` | Mark task blocked for human input. Also appends the reason as a comment. |
| `schedule <id> "<reason>"` | Park time-delay/follow-up work in `scheduled` so it is not shown as a human blocker. |
| `unblock <id>` | Return a blocked or scheduled task to ready (or `todo` if dependencies are still open). |
| `archive <id>` | Hide from default list. `gc` will remove scratch workspaces. |
| `tail <id>` | Follow a task's event stream. |
| `dispatch` | One dispatcher pass on the active board. Flags: `--dry-run`, `--max N`, `--failure-limit N`, `--json`. |
| `context <id>` | Print the full context a worker would see (title + body + parent results + comments). |
| `specify <id>` / `specify --all` | Flesh out a triage-column task into a concrete spec (title + body with goal, approach, acceptance criteria) via the auxiliary LLM, then promote it to `todo`. Flags: `--tenant` (scope `--all` to one tenant), `--author`, `--json`. Configure the model under `auxiliary.triage_specifier` in `config.yaml`. |
| `decompose <id>` / `decompose --all` | Fan a triage-column task out into a graph of child tasks routed to specialist profiles by description. Falls back to specify-style single-task promotion when the LLM decides the task doesn't benefit from fan-out. Same flags as `specify`. Configure the decomposer model under `auxiliary.kanban_decomposer` in `config.yaml`; `kanban.orchestrator_profile` only controls who owns the root/orchestration task after fan-out. Also runs automatically every dispatcher tick when `kanban.auto_decompose: true` (the default). See [Auto vs Manual orchestration](/user-guide/features/kanban#auto-vs-manual-orchestration). |
| `gc` | Remove scratch workspaces for archived tasks. |

Examples:

```bash
# Create a second board and put a task on it without switching away.
robo kanban boards create atm10-server --name "ATM10 Server" --icon 🎮
robo kanban --board atm10-server create "Restart server" --assignee ops

# Switch the active board for subsequent calls.
robo kanban boards switch atm10-server
robo kanban list                  # shows atm10-server tasks

# Archive a board (recoverable) or hard-delete it.
robo kanban boards rm atm10-server
robo kanban boards rm atm10-server --delete
```

Board resolution order (highest precedence first): `--board <slug>` flag → `ROBO_KANBAN_BOARD` env var → `~/.robo/kanban/current` file → `default`.

All actions are also available as a slash command in the gateway (`/kanban …`), with the same argument surface — including `boards` subcommands and the `--board` flag.

For collaboration patterns, worked examples and the concurrency model, see the [Kanban user guide](/user-guide/features/kanban).

## `robo egress`

Outbound credential-injection firewall for remote terminal sandboxes. Wraps the [iron-proxy](https://github.com/ironsh/iron-proxy) daemon — a TLS-intercepting proxy that swaps opaque proxy tokens for real upstream API credentials at the network boundary, so sandboxes never hold real keys. Disabled by default; see the full [Egress proxy](../user-guide/egress/iron-proxy.md) page for setup + architecture.

```bash
robo egress install                  # download the pinned iron-proxy binary
robo egress install --force          # re-download even if already installed

robo egress setup                    # interactive wizard: CA, mappings, config
robo egress setup --tunnel-port N    # override the tunnel listener port (default 9090)
robo egress setup --from-bitwarden   # use Bitwarden Secrets Manager as credential source
robo egress setup --no-bitwarden     # explicitly switch back to env-based credentials
robo egress setup --rotate-tokens    # mint fresh proxy tokens (default preserves existing)

robo egress start                    # spawn the managed proxy daemon
robo egress stop                     # SIGTERM (then SIGKILL after 5s grace)
robo egress restart                  # stop (if running) then start — needed for secret changes
robo egress reload                   # hot-reload the ruleset in-place (no restart, no dropped
                                       #   connections) via the loopback management API

robo egress status                   # binary + config + pid + listening + mappings
robo egress status --show-tokens     # print proxy tokens in full (default: redacted)

robo egress disable                  # flip proxy.enabled = false (does not stop a running proxy)
robo egress config                   # print the path to proxy.yaml for inspection
```

### Common flows

```bash
# First-time setup
export OPENROUTER_API_KEY=…
robo egress setup && robo egress start
robo config set terminal.backend docker   # if not already

# Switching credential source after the fact
robo egress setup --from-bitwarden       # env → bitwarden
robo egress setup --no-bitwarden         # bitwarden → env
# (just `setup` without either flag preserves the existing mode)

# Rotating all tokens (e.g. after a suspected token leak)
robo egress setup --rotate-tokens    # setup offers to restart the running daemon for you
# (running sandboxes still hold old tokens; restart them too)

# Adding a new upstream
# Edit ~/.robo/config.yaml proxy.extra_allowed_hosts: [api.example.com]
robo egress setup
robo egress restart                  # one-command apply (stop + start)
```

### Diagnostic shortcuts

```bash
robo egress status                     # current state in one view
cat ~/.robo/proxy/proxy.yaml           # the rendered iron-proxy config
tail -20 ~/.robo/proxy/iron-proxy.log  # daemon-level diagnostics
tail -f ~/.robo/proxy/iron-proxy.log | jq  # daemon + per-request log (line-delimited JSON; v0.39 combines both streams)
```

Common failure modes + recovery are covered in [Egress proxy → Troubleshooting](../user-guide/egress/iron-proxy.md#troubleshooting).

## `robo project`

```bash
robo project <create|list|show|add-folder|remove-folder|rename|set-primary|use|archive|restore|bind-board>
```

Projects are human-named workspaces that can span multiple folders / repos. They anchor desktop session grouping and, when bound to a kanban board, give tasks a deterministic worktree + branch convention. State is per-profile.

| Subcommand | Description |
|------------|-------------|
| `create` | Create a new project. |
| `list` (alias `ls`) | List projects. |
| `show` | Show a project's details. |
| `add-folder` | Add a folder / repo to a project. |
| `remove-folder` | Remove a folder from a project. |
| `rename` | Rename a project. |
| `set-primary` | Set the primary folder. |
| `use` | Set the active project. |
| `archive` | Archive a project (recoverable). |
| `restore` | Restore an archived project. |
| `bind-board` | Bind a kanban board to this project. |

## `robo webhook`

```bash
robo webhook <subscribe|list|remove|test>
```

Manage dynamic webhook subscriptions for event-driven agent activation. Requires the webhook platform to be enabled in config — if not configured, prints setup instructions.

| Subcommand | Description |
|------------|-------------|
| `subscribe` / `add` | Create a webhook route. Returns the URL and HMAC secret to configure on your service. |
| `list` / `ls` | Show all agent-created subscriptions. |
| `remove` / `rm` | Delete a dynamic subscription. Static routes from config.yaml are not affected. |
| `test` | Send a test POST to verify a subscription is working. |

### `robo webhook subscribe`

```bash
robo webhook subscribe <name> [options]
```

| Option | Description |
|--------|-------------|
| `--prompt` | Prompt template with `{dot.notation}` payload references. |
| `--events` | Comma-separated event types to accept (e.g. `issues,pull_request`). Empty = all. |
| `--description` | Human-readable description. |
| `--skills` | Comma-separated skill names to load for the agent run. |
| `--deliver` | Delivery target: `log` (default), `telegram`, `discord`, `slack`, `github_comment`. |
| `--deliver-chat-id` | Target chat/channel ID for cross-platform delivery. |
| `--secret` | Custom HMAC secret. Auto-generated if omitted. |
| `--deliver-only` | Skip the agent — deliver the rendered `--prompt` as the literal message. Zero LLM cost, sub-second delivery. Requires `--deliver` to be a real target (not `log`). |
| `--script` | Filter/transform script under `~/.robo/scripts/`. The webhook payload is passed as JSON on stdin; JSON stdout replaces the payload, and empty stdout, `[SILENT]`, or a nonzero exit code ignores the webhook. See [Script Filters and Transforms](../user-guide/messaging/webhooks.md#script-filters-and-transforms). |

Subscriptions persist to `~/.robo/webhook_subscriptions.json` and are hot-reloaded by the webhook adapter without a gateway restart.

## `robo doctor`

```bash
robo doctor [--fix]
```

| Option | Description |
|--------|-------------|
| `--fix` | Attempt automatic repairs where possible. |

## `robo dump`

```bash
robo dump [--show-keys]
```

Outputs a compact, plain-text summary of your entire Robo setup. Designed to be copy-pasted into Discord, GitHub issues, or Telegram when asking for support — no ANSI colors, no special formatting, just data.

| Option | Description |
|--------|-------------|
| `--show-keys` | Show redacted API key prefixes (first and last 4 characters) instead of just `set`/`not set`. |

### What it includes

| Section | Details |
|---------|---------|
| **Header** | Robo version, release date, git commit hash |
| **Environment** | OS, Python version, OpenAI SDK version |
| **Identity** | Active profile name, ROBO_HOME path |
| **Model** | Configured default model and provider |
| **Terminal** | Backend type (local, docker, ssh, etc.) |
| **API keys** | Presence check for all 22 provider/tool API keys |
| **Features** | Enabled toolsets, MCP server count, memory provider |
| **Services** | Gateway status, configured messaging platforms |
| **Workload** | Cron job counts, installed skill count |
| **Config overrides** | Any config values that differ from defaults |

### Example output

```
--- robo dump ---
version:          0.8.0 (2026.4.8) [af4abd2f]
os:               Linux 6.14.0-37-generic x86_64
python:           3.11.14
openai_sdk:       2.24.0
profile:          default
robo_home:      ~/.robo
model:            anthropic/claude-opus-4.6
provider:         openrouter
terminal:         local

api_keys:
  openrouter           set
  openai               not set
  anthropic            set
  firecrawl            set
  ...

features:
  toolsets:           all
  mcp_servers:        0
  memory_provider:    built-in
  gateway:            running (systemd)
  platforms:          telegram, discord
  cron_jobs:          3 active / 5 total
  skills:             42

config_overrides:
  agent.max_turns: 250
  compression.threshold: 0.85
  display.streaming: True
--- end dump ---
```

### When to use

- Reporting a bug on GitHub — paste the dump into your issue
- Asking for help in Discord — share it in a code block
- Comparing your setup to someone else's
- Quick sanity check when something isn't working

:::tip
`robo dump` is specifically designed for sharing. For interactive diagnostics, use `robo doctor`. For a visual overview, use `robo status`.
:::

## `robo debug`

```bash
robo debug share [options]
```

Upload a debug report (system info + recent logs) to a paste service and get a shareable URL. Useful for quick support requests — includes everything a helper needs to diagnose your issue.

| Option | Description |
|--------|-------------|
| `--lines <N>` | Number of log lines to include per log file (default: 200). |
| `--expire <days>` | Paste expiry in days (default: 7). |
| `--local` | Print the report locally instead of uploading. |
| `--no-redact` | Disable upload-time secret redaction. By default, uploads are redacted. |

The report includes system info (OS, Python version, Robo version), recent agent, gateway, GUI/dashboard, and desktop logs (512 KB limit per file), and redacted API key status. By default, uploads are redacted so secrets are not included.

Default uploads use public paste services tried in order: paste.rs, dpaste.com.

### Examples

```bash
robo debug share              # Upload debug report, print URL
robo debug share --lines 500  # Include more log lines
robo debug share --expire 30  # Keep paste for 30 days
robo debug share --local      # Print report to terminal (no upload)
```

## `robo backup`

```bash
robo backup [options]
```

Create a zip archive of your Robo configuration, skills, sessions, and data. The backup excludes the robo-engineer codebase itself.

| Option | Description |
|--------|-------------|
| `-o`, `--output <path>` | Output path for the zip file (default: `~/robo-backup-<timestamp>.zip`). |
| `-q`, `--quick` | Quick snapshot: only critical state files (config.yaml, state.db, .env, auth, cron jobs). Much faster than a full backup. |
| `-l`, `--label <name>` | Label for the snapshot (only used with `--quick`). |

The backup uses SQLite's `backup()` API for safe copying, so it works correctly even when Robo is running (WAL-mode safe).

**What's excluded from the zip:**

- `*.db-wal`, `*.db-shm`, `*.db-journal` — SQLite's WAL / shared-memory / journal sidecars. The `*.db` file already got a consistent snapshot via `sqlite3.backup()`; shipping the live sidecars alongside it would let a restore see a half-committed state.
- `checkpoints/` — per-session trajectory caches. Hash-keyed and regenerated per session; wouldn't port cleanly to another install anyway.
- The `robo-engineer` code itself (this is a user-data backup, not a repo snapshot).

### Examples

```bash
robo backup                           # Full backup to ~/robo-backup-*.zip
robo backup -o /tmp/robo.zip        # Full backup to specific path
robo backup --quick                   # Quick state-only snapshot
robo backup --quick --label "pre-upgrade"  # Quick snapshot with label
```

## `robo checkpoints`

```bash
robo checkpoints [COMMAND]
```

Inspect and manage the shadow git store at `~/.robo/checkpoints/` — the storage layer behind the in-session `/rollback` command. Safe to run any time; does not require the agent to be running.

| Subcommand | Description |
|------------|-------------|
| `status` (default) | Show total size, project count, and per-project breakdown. Bare `robo checkpoints` is equivalent. |
| `list` | Alias for `status`. |
| `prune` | Force a cleanup sweep — delete orphan and stale projects, GC the store, enforce the size cap. Ignores the 24h idempotency marker. |
| `clear` | Delete the entire checkpoint base. Irreversible; asks for confirmation unless `-f`. |
| `clear-legacy` | Delete only the `legacy-<timestamp>/` archives produced by the v1→v2 migration. |

### Options

| Option | Subcommand | Description |
|--------|------------|-------------|
| `--limit N` | `status`, `list` | Max projects to list (default 20). |
| `--retention-days N` | `prune` | Drop projects whose `last_touch` is older than N days (default 7). |
| `--max-size-mb N` | `prune` | After the orphan/stale pass, drop the oldest commit per project until total store size ≤ N MB (default 500). |
| `--keep-orphans` | `prune` | Skip deleting projects whose working directory no longer exists. |
| `-f`, `--force` | `clear`, `clear-legacy` | Skip the confirmation prompt. |

### Examples

```bash
robo checkpoints                                  # status overview
robo checkpoints prune --retention-days 3         # aggressive cleanup
robo checkpoints prune --max-size-mb 200          # tighten size cap once
robo checkpoints clear-legacy -f                  # drop v1 archive dirs
robo checkpoints clear -f                         # wipe everything
```

See [Checkpoints and `/rollback`](../user-guide/checkpoints-and-rollback.md) for the full architecture and the in-session commands.

## `robo import`

```bash
robo import <zipfile> [options]
```

Restore a previously created Robo backup into your Robo home directory. All files in the archive overwrite existing files in your Robo home; `--force` only skips the confirmation prompt that fires when the target already has a Robo installation.

| Option | Description |
|--------|-------------|
| `-f`, `--force` | Skip the existing-installation confirmation prompt. |

:::warning
Stop the gateway before importing to avoid conflicts with running processes.
:::

### Examples
```bash
robo import ~/robo-backup-20260423.zip           # Prompts before overwriting existing config
robo import ~/robo-backup-20260423.zip --force   # Overwrite without prompting
```

## `robo logs`

```bash
robo logs [log_name] [options]
```

View, tail, and filter Robo log files. All logs are stored in `~/.robo/logs/` (or `<profile>/logs/` for non-default profiles).

### Log files

| Name | File | What it captures |
|------|------|-----------------|
| `agent` (default) | `agent.log` | All agent activity — API calls, tool dispatch, session lifecycle (INFO and above) |
| `errors` | `errors.log` | Warnings and errors only — a filtered subset of agent.log |
| `gateway` | `gateway.log` | Messaging gateway activity — platform connections, message dispatch, webhook events |
| `gui` | `gui.log` | Dashboard / TUI-gateway / PTY-bridge / websocket events |
| `desktop` | `desktop.log` | Electron desktop app — boot, backend spawn output, and recent Python tracebacks |

### Options

| Option | Description |
|--------|-------------|
| `log_name` | Which log to view: `agent` (default), `errors`, `gateway`, or `list` to show available files with sizes. |
| `-n`, `--lines <N>` | Number of lines to show (default: 50). |
| `-f`, `--follow` | Follow the log in real time, like `tail -f`. Press Ctrl+C to stop. |
| `--level <LEVEL>` | Minimum log level to show: `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`. |
| `--session <ID>` | Filter lines containing a session ID substring. |
| `--since <TIME>` | Show lines from a relative time ago: `30m`, `1h`, `2d`, etc. Supports `s` (seconds), `m` (minutes), `h` (hours), `d` (days). |
| `--component <NAME>` | Filter by component: `gateway`, `agent`, `tools`, `cli`, `cron`. |

### Examples

```bash
# View the last 50 lines of agent.log (default)
robo logs

# Follow agent.log in real time
robo logs -f

# View the last 100 lines of gateway.log
robo logs gateway -n 100

# Show only warnings and errors from the last hour
robo logs --level WARNING --since 1h

# Filter by a specific session
robo logs --session abc123

# Follow errors.log, starting from 30 minutes ago
robo logs errors --since 30m -f

# List all log files with their sizes
robo logs list
```

### Filtering

Filters can be combined. When multiple filters are active, a log line must pass **all** of them to be shown:

```bash
# WARNING+ lines from the last 2 hours containing session "tg-12345"
robo logs --level WARNING --since 2h --session tg-12345
```

Lines without a parseable timestamp are included when `--since` is active (they may be continuation lines from a multi-line log entry). Lines without a detectable level are included when `--level` is active.

### Log rotation

Robo uses Python's `RotatingFileHandler`. Old logs are rotated automatically — look for `agent.log.1`, `agent.log.2`, etc. The `robo logs list` subcommand shows all log files including rotated ones.


## `robo prompt-size`

```bash
robo prompt-size [--platform <name>] [--json]
```

Reports the fixed prompt budget for a fresh session — what gets sent on every
API call *before* any conversation content. Useful when a downstream adapter or
proxy has a tighter prompt budget than the model's context window, or when you
want to see which block (skills index, memory, profile) dominates.

It builds the same system prompt the agent would, then breaks it down:

- **System prompt total** — full assembled prompt (identity, guidance, skills
  index, context files, memory, profile, timestamp).
- **Skills index** — the `<available_skills>` block. This is often the largest
  single block when many skills are installed.
- **Memory** and **user profile** — your `MEMORY.md` / `USER.md` snapshots.
- **Prompt tiers** — stable / context / volatile, matching how Robo layers
  the prompt for cache-friendliness.
- **Tool schemas** — the JSON for all enabled tools (the other half of the
  fixed per-call payload).

Runs entirely offline — no API call, works with no credentials configured.

```bash
# Human-readable breakdown for the CLI platform (default)
robo prompt-size

# Simulate a messaging platform's prompt (different platform hint)
robo prompt-size --platform telegram

# Machine-readable output for scripts
robo prompt-size --json
```

:::tip
The skills index and tool schemas scale with how many skills and tools you have
enabled. To shrink the prompt, disable unused toolsets (`robo tools`) or
uninstall skills you don't need (`robo skills`). Context files (AGENTS.md,
.cursorrules) in your current directory also count toward the total.
:::

## `robo config`

```bash
robo config <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `show` | Show current config values. |
| `edit` | Open `config.yaml` in your editor. |
| `get <key> [--json]` | Print a single config value by dotted key (e.g. `robo config get model.default`). `--json` emits machine-readable output. |
| `set <key> <value>` | Set a config value. |
| `unset <key>` | Remove a config key, reverting it to the built-in default. |
| `path` | Print the config file path. |
| `env-path` | Print the `.env` file path. |
| `check` | Check for missing or stale config. |
| `migrate` | Add newly introduced options interactively. |

## `robo pairing`

```bash
robo pairing <list|approve|revoke|clear-pending>
```

| Subcommand | Description |
|------------|-------------|
| `list` | Show pending and approved users. |
| `approve <platform> <code>` | Approve a pairing code. |
| `revoke <platform> <user-id>` | Revoke a user's access. |
| `clear-pending` | Clear pending pairing codes. |

## `robo skills`

```bash
robo skills <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `browse` | Paginated browser for skill registries. |
| `search` | Search skill registries. |
| `install` | Install a skill. |
| `inspect` | Preview a skill without installing it. |
| `list` | List installed skills. |
| `check` | Check installed hub skills for upstream updates. |
| `update` | Reinstall hub skills with upstream changes when available. |
| `audit` | Re-scan installed hub skills. |
| `uninstall` | Remove a hub-installed skill. |
| `reset` | Un-stick a bundled skill flagged as `user_modified` by clearing its manifest entry. With `--restore`, also replaces the user copy with the bundled version. |
| `opt-out` | Stop bundled skills from being seeded into the active profile. Writes a `.no-bundled-skills` marker so the installer, `robo update`, and any sync skip bundled-skill seeding. Safe by default — nothing on disk is touched. With `--remove`, also deletes already-present bundled skills that are **unmodified** (user-edited, hub-installed, and hand-written skills are never removed; previews and confirms first, `--yes` to skip). |
| `opt-in` | Undo `opt-out` by removing the `.no-bundled-skills` marker so bundled skills are seeded again on the next `robo update`. With `--sync`, re-seed immediately. |
| `publish` | Publish a skill to a registry. |
| `snapshot` | Export/import skill configurations. |
| `tap` | Manage custom skill sources. |
| `config` | Interactive enable/disable configuration for skills by platform. |

Common examples:

```bash
robo skills browse
robo skills browse --source official
robo skills search react --source skills-sh
robo skills search https://mintlify.com/docs --source well-known
robo skills inspect official/security/1password
robo skills inspect skills-sh/vercel-labs/json-render/json-render-react
robo skills install skills-sh/anthropics/skills/pdf --force
robo skills install https://sharethis.chat/SKILL.md                     # Direct URL (+ referenced support files)
robo skills install https://example.com/SKILL.md --name my-skill        # Override name when frontmatter has none
robo skills check
robo skills update
robo skills config
robo skills reset google-workspace
robo skills reset google-workspace --restore --yes
robo skills opt-out                  # stop future bundled-skill seeding (nothing deleted)
robo skills opt-out --remove --yes   # also delete UNMODIFIED bundled skills
robo skills opt-in --sync            # undo: remove marker and re-seed now
```

Notes:
- `--force` can override non-dangerous policy blocks for third-party/community skills.
- `--force` does not override a `dangerous` scan verdict.
- `--source skills-sh` searches the public `skills.sh` directory.
- `--source well-known` lets you point Robo at a site exposing `/.well-known/skills/index.json`.
- `--source browse-sh` searches [browse.sh](https://browse.sh)'s catalog of 200+ site-specific browser-automation skills. Identifiers look like `browse-sh/airbnb.com/search-listings-ddgioa`.
- Passing an `http(s)://…/*.md` URL installs `SKILL.md` plus explicitly referenced files under `references/`, `templates/`, `scripts/`, `assets/`, and `examples/`. When frontmatter has no `name:` and the URL slug isn't a valid identifier, an interactive terminal prompts for a name; non-interactive surfaces (`/skills install` inside the TUI, gateway platforms) require `--name <x>` instead.

## `robo bundles`

```bash
robo bundles <subcommand>
```

Skill bundles group several skills under one `/<bundle-name>` slash command. Invoking the bundle loads every referenced skill into a single combined user message. Storage: `~/.robo/skill-bundles/<slug>.yaml`. See [Skill Bundles](../user-guide/features/skills.md#skill-bundles) for the YAML schema and behavior.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `list` | List installed bundles (default when no subcommand given) |
| `show <name>` | Show one bundle's name, description, skills, and file path |
| `create <name>` | Create a new bundle. Pass `--skill <id>` (repeat) or omit for interactive entry. `--description`, `--instruction`, `--force` available. |
| `delete <name>` | Remove a bundle file |
| `reload` | Re-scan `~/.robo/skill-bundles/` and report added/removed bundles |

Examples:

```bash
robo bundles create backend-dev \
  --skill github-code-review \
  --skill test-driven-development \
  --skill github-pr-workflow \
  -d "Backend feature work"

robo bundles list
robo bundles show backend-dev
robo bundles delete backend-dev
```

In a chat session, `/bundles` lists installed bundles and `/<bundle-name>` loads one.

## `robo curator`

```bash
robo curator <subcommand>
```

The curator is an auxiliary-model background task that periodically reviews agent-created skills, prunes stale ones, consolidates overlaps, and archives obsolete skills. Bundled and hub-installed skills are never touched. Archives are recoverable; auto-deletion never happens.

| Subcommand | Description |
|------------|-------------|
| `status` | Show curator status and skill stats |
| `run` | Trigger a curator review now (blocks until the LLM pass finishes) |
| `run --background` | Start the LLM pass in a background thread and return immediately |
| `run --dry-run` | Preview only — produce the review report with no mutations |
| `backup` | Take a manual tar.gz snapshot of `~/.robo/skills/` (curator also snapshots automatically before every real run) |
| `rollback` | Restore `~/.robo/skills/` from a snapshot (defaults to newest) |
| `rollback --list` | List available snapshots |
| `rollback --id <ts>` | Restore a specific snapshot by id |
| `rollback -y` | Skip the confirmation prompt |
| `pause` | Pause the curator until resumed |
| `resume` | Resume a paused curator |
| `pin <skill>` | Pin a skill so the curator never auto-transitions it |
| `unpin <skill>` | Unpin a skill |
| `restore <skill>` | Restore an archived skill |
| `archive <skill>` | Archive a skill manually |
| `prune` | Manually prune skills the curator would normally clean up |
| `list-archived` | List archived skills (recoverable via `restore`) |

On a fresh install the first scheduled pass is deferred by one full `interval_hours` (7 days by default) — the gateway will not curate immediately on the first tick after `robo update`. Use `robo curator run --dry-run` to preview before that happens.

See [Curator](../user-guide/features/curator.md) for behavior and config.

## `robo moa`

Configure named Mixture of Agents presets. Presets appear as selectable models under a `Mixture of Agents` provider in every model picker; `/moa <prompt>` runs one prompt through the default preset.

```bash
robo moa list
robo moa configure [name]
robo moa delete <name>
```

`robo moa configure` reuses Robo' provider → model picker for each reference model and the aggregator. A preset is an execution-mode configuration, not a primary model or provider.

## `robo fallback`

```bash
robo fallback <subcommand>
```

Manage the fallback provider chain. Fallback providers are tried in order when the primary model fails with rate-limit, overload, or connection errors.

| Subcommand | Description |
|------------|-------------|
| `list` (alias: `ls`) | Show the current fallback chain (default when no subcommand) |
| `add` | Pick a provider + model (same picker as `robo model`) and append to the chain |
| `remove` (alias: `rm`) | Pick an entry to delete from the chain |
| `clear` | Remove all fallback entries |

See [Fallback Providers](../user-guide/features/fallback-providers.md).

## `robo hooks`

```bash
robo hooks <subcommand>
```

Inspect shell-script hooks declared in `~/.robo/config.yaml`, test them against synthetic payloads, and manage the first-use consent allowlist at `~/.robo/shell-hooks-allowlist.json`.

| Subcommand | Description |
|------------|-------------|
| `list` (alias: `ls`) | List configured hooks with matcher, timeout, and consent status |
| `test <event>` | Fire every hook matching `<event>` against a synthetic payload |
| `revoke` (aliases: `remove`, `rm`) | Remove a command's allowlist entries (takes effect on next restart) |
| `doctor` | Check each configured hook: exec bit, allowlist, mtime drift, JSON validity, and synthetic run timing |

See [Hooks](../user-guide/features/hooks.md) for event signatures and payload shapes.

## `robo memory`

```bash
robo memory <subcommand>
```

Set up and manage external memory provider plugins. Available providers: honcho, openviking, mem0, hindsight, holographic, retaindb, byterover, supermemory. Only one external provider can be active at a time. Built-in memory (MEMORY.md/USER.md) is always active.

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `setup` | Interactive provider selection and configuration. |
| `status` | Show current memory provider config. |
| `off` | Disable external provider (built-in only). |

:::info Provider-specific subcommands
When an external memory provider is active, it may register its own top-level `robo <provider>` command for provider-specific management (e.g. `robo honcho` when Honcho is active). Inactive providers do not expose their subcommands. Run `robo --help` to see what's currently wired in.
:::

## `robo acp`

```bash
robo acp
```

Starts Robo as an ACP (Agent Client Protocol) stdio server for editor integration.

Related entrypoints:

```bash
robo-acp
python -m acp_adapter
```

Install support first:

```bash
cd ~/.robo/robo-engineer && uv pip install -e '.[acp]'
```

See [ACP Editor Integration](../user-guide/features/acp.md) and [ACP Internals](../developer-guide/acp-internals.md).

## `robo mcp`

```bash
robo mcp <subcommand>
```

Manage MCP (Model Context Protocol) server configurations and run Robo as an MCP server.

| Subcommand | Description |
|------------|-------------|
| *(none)* or `picker` | Interactive catalog picker — browse the bundled MCP catalog and install/enable/disable. |
| `catalog` | List the bundled MCP catalog (plain text, scriptable). |
| `install <name>` | Install a catalog entry (e.g. `robo mcp install n8n`). |
| `serve [-v\|--verbose]` | Run Robo as an MCP server — expose conversations to other agents. |
| `add <name> [--url URL] [--command CMD] [--auth oauth\|header] [--args ...]` | Add a custom MCP server with automatic tool discovery. `--args` passes the remaining argv to the stdio command, so put it last. |
| `remove <name>` (alias: `rm`) | Remove an MCP server from config. |
| `list` (alias: `ls`) | List configured MCP servers. |
| `test <name>` | Test connection to an MCP server. |
| `configure <name>` (alias: `config`) | Toggle tool selection for a server. |
| `login <name>` | Force re-authentication for an OAuth-based MCP server. |

See [MCP Config Reference](./mcp-config-reference.md), [Use MCP with Robo](../guides/use-mcp-with-robo.md), and [MCP Server Mode](../user-guide/features/mcp.md#running-robo-as-an-mcp-server).

## `robo plugins`

```bash
robo plugins [subcommand]
```

Unified plugin management — general plugins, memory providers, and context engines in one place. Running `robo plugins` with no subcommand opens a composite interactive screen with two sections:

- **General Plugins** — multi-select checkboxes to enable/disable installed plugins
- **Provider Plugins** — single-select configuration for Memory Provider and Context Engine. Press ENTER on a category to open a radio picker.

| Subcommand | Description |
|------------|-------------|
| *(none)* | Composite interactive UI — general plugin toggles + provider plugin configuration. |
| `install <identifier> [--force]` | Install a plugin from a Git URL or `owner/repo`. |
| `update <name>` | Pull latest changes for an installed plugin. |
| `remove <name>` (aliases: `rm`, `uninstall`) | Remove an installed plugin. |
| `enable <name>` | Enable a disabled plugin. |
| `disable <name>` | Disable a plugin without removing it. |
| `list` (alias: `ls`) | List installed plugins with enabled/disabled status. |

Provider plugin selections are saved to `config.yaml`:
- `memory.provider` — active memory provider (empty = built-in only)
- `context.engine` — active context engine (`"compressor"` = built-in default)

General plugin disabled list is stored in `config.yaml` under `plugins.disabled`.

See [Plugins](../user-guide/features/plugins.md) and [Build a Robo Plugin](../developer-guide/plugins/index.md).

## `robo tools`

```bash
robo tools [--summary]
```

| Option | Description |
|--------|-------------|
| `--summary` | Print the current enabled-tools summary and exit. |

Without `--summary`, this launches the interactive per-platform tool configuration UI.

## `robo computer-use`

```bash
robo computer-use <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `install` | Run the upstream cua-driver installer (macOS, Windows, and Linux). |
| `install --upgrade` | Re-run the installer even if cua-driver is already on PATH. The upstream script always pulls the latest release, so this performs an in-place upgrade. |
| `status` | Print whether `cua-driver` is on `$PATH` and which version is installed. |

`robo computer-use install` is the stable entry point for installing the
[cua-driver](https://github.com/trycua/cua) binary used by the
`computer_use` toolset. It runs the same upstream installer that
`robo tools` invokes when you first enable Computer Use, so it's safe
to use for re-running the install if the toolset toggle didn't trigger
it (for example, on returning-user setups).

`robo update` automatically re-runs the upstream installer at the end
of the update if cua-driver is on PATH, so most users will not need to
call `--upgrade` manually. Use it when upstream ships a fix you want
right now without waiting for the next Robo update.

## `robo pets`

```bash
robo pets <list|install|select|show|off|scale|remove|doctor>
```

[Petdex](https://github.com/crafter-station/petdex) is a public gallery of animated sprite pets for coding agents. Install one and Robo shows it reacting to agent activity across the CLI, TUI, and desktop app.

| Subcommand | Description |
|------------|-------------|
| `list` | Browse the petdex gallery. |
| `install` | Install a pet from the gallery. |
| `select` | Set the active pet (writes `display.pet.*`). |
| `show` | Animate the active pet in the terminal. |
| `off` | Disable the pet display. |
| `scale` | Resize the pet everywhere (`display.pet.scale`). |
| `remove` | Delete an installed pet. |
| `doctor` | Check pet setup + terminal graphics support. |

You can also generate a brand-new pet from a text description with the `/hatch` slash command. See [Pets](../user-guide/features/pets.md).

## `robo sessions`

```bash
robo sessions <subcommand>
```

Subcommands:

| Subcommand | Description |
|------------|-------------|
| `list` | List recent sessions. |
| `browse` | Interactive session picker with search and resume. |
| `export <output> [--session-id ID]` | Export sessions to JSONL. |
| `delete <session-id>` | Delete one session. |
| `prune` | Delete sessions matching filters: time bounds `--older-than`/`--newer-than`/`--before`/`--after` (durations like `5h`/`2d`, bare days, or ISO timestamps); attributes `--source`, `--title`, `--model`, `--provider`, `--branch`, `--end-reason`, `--user`, `--chat-id`, `--chat-type`, `--cwd`; numeric bounds `--min/--max-messages`, `--min/--max-tokens`, `--min/--max-cost`, `--min/--max-tool-calls`; plus `--include-archived`, `--dry-run`, `--yes`. Default: older than 90 days. |
| `archive` | Bulk-archive (soft-hide, no deletion) sessions matching the same filters as `prune`. Requires at least one filter. |
| `stats` | Show session-store statistics. |
| `rename <session-id> <title>` | Set or change a session title. |
| `optimize` | Reclaim disk space: merge FTS5 index segments + VACUUM. Non-destructive — no session data changes. |
| `optimize-storage` | Migrate the full-text search index to the compact v23 external-content layout; on large databases this reclaims a large fraction of `state.db`. |
| `repair` | Repair a malformed `state.db` schema (e.g. `table messages_fts already exists`) so hidden sessions reappear; a backup is made first. |
| `recover` | Offline, non-destructive recovery of a damaged `state.db` into a separate clean database. |
| `retitle-skills` | Regenerate titles for sessions opened with a `/skill`, using what the user actually typed; lists changes unless `--apply` is passed. |

## `robo insights`

```bash
robo insights [--days N] [--source platform]
```

| Option | Description |
|--------|-------------|
| `--days <n>` | Analyze the last `n` days (default: 30). |
| `--source <platform>` | Filter by source such as `cli`, `telegram`, or `discord`. |

## `robo import-agent`

```bash
robo import-agent [claude-code|codex] [options]
```

Import a **Claude Code** (`~/.claude`) or **OpenAI Codex CLI** (`~/.codex`) setup into Robo. Maps `CLAUDE.md`/`AGENTS.md` instructions to memory entries, `Bash(...)` permission allow/deny rules to `command_allowlist`/`approvals.deny`, MCP servers to `mcp_servers` in `config.yaml`, and skill directories into `~/.robo/skills/`. Always previews before applying; API keys and credentials are never imported.

| Option | Description |
| --- | --- |
| `agent` | `claude-code` or `codex` (default: auto-detect). |
| `--source <path>` | Custom source directory (default: `~/.claude` or `~/.codex`). |
| `--dry-run` | Preview only — write nothing. |
| `--overwrite` | Replace conflicting MCP servers / skills (default: skip). |
| `--yes`, `-y` | Skip confirmation prompts. |

See the **[import guide](../user-guide/import-from-other-agents.md)** for the full mapping tables.

## `robo serve`

```bash
robo serve [options]
```

Start the Robo **backend server** — the JSON-RPC/WebSocket gateway the [desktop app](/user-guide/desktop) and remote clients connect to. It is the same server `robo dashboard` runs, but **headless**: it never opens a browser UI. The desktop app launches its own `robo serve` backend; use this command directly when you want a headless backend on a remote host. Accepts the same `--host` / `--port` / `--insecure` / `--skip-build` / `--stop` / `--status` options as `robo dashboard` below (a non-loopback bind engages the same auth gate). Requires the `[web]` extra; the embedded Chat socket additionally needs `[pty]` on a POSIX host.

## `robo dashboard`

```bash
robo dashboard [options]
```

Launch the web dashboard — a browser-based UI for managing configuration, API keys, and monitoring sessions. (For a headless backend with no browser UI — e.g. what the desktop app spawns — use [`robo serve`](#robo-serve) above.) Requires `cd ~/.robo/robo-engineer && uv pip install -e ".[web]"` (FastAPI + Uvicorn). The embedded browser Chat tab is always available and additionally needs the `pty` extra (`cd ~/.robo/robo-engineer && uv pip install -e ".[web,pty]"`) plus a POSIX PTY environment such as Linux, macOS, or WSL2. See [Web Dashboard](/user-guide/features/web-dashboard) for full documentation.

| Option | Default | Description |
|--------|---------|-------------|
| `--port` | `9119` | Port to run the web server on |
| `--host` | `127.0.0.1` | Bind address |
| `--no-open` | — | Don't auto-open the browser |
| `--insecure` | off | **Deprecated / no-op.** Formerly bypassed auth on a non-loopback bind. Since the June 2026 hardening a public bind *always* requires an auth provider (password or OAuth). Bind `127.0.0.1` and tunnel to keep it local. |
| `--skip-build` | off | Skip the web UI build step and serve the existing `dist` directly. Useful for non-interactive contexts (Windows Scheduled Tasks, CI) where npm isn't available. Pre-build with `cd web && npm run build`. |
| `--isolated` | off | When launched from a named profile (`worker dashboard`), run a dedicated per-profile server instead of routing to the machine dashboard. |
| `--stop` | — | Stop running `robo dashboard` processes and exit. |
| `--status` | — | List running `robo dashboard` processes and exit. |

```bash
# Default — opens browser to http://127.0.0.1:9119
robo dashboard

# Custom port, no browser
robo dashboard --port 8080 --no-open

# From a profile alias — routes to the machine dashboard with the
# profile preselected in the sidebar switcher (attach if running)
worker dashboard
```

## `robo profile`

```bash
robo profile <subcommand>
```

Manage profiles — multiple isolated Robo instances, each with its own config, sessions, skills, and home directory.

| Subcommand | Description |
|------------|-------------|
| `list` | List all profiles. |
| `use <name>` | Set a sticky default profile. |
| `create <name> [--clone] [--clone-all] [--clone-from <source>] [--no-alias]` | Create a new profile. `--clone` copies config, `.env`, `SOUL.md`, and skills from the active profile. `--clone-all` copies all state. `--clone-from` specifies a source profile and implies config clone unless paired with `--clone-all`. |
| `delete <name> [-y]` | Delete a profile. |
| `show <name>` | Show profile details (home directory, config, etc.). |
| `alias <name> [--remove] [--name NAME]` | Manage wrapper scripts for quick profile access. |
| `rename <old> <new>` | Rename a profile. |
| `export <name> [-o FILE]` | Export a profile to a `.tar.gz` archive (local backup). |
| `import <archive> [--name NAME]` | Import a profile from a `.tar.gz` archive (local restore). |
| `install <source> [--name N] [--alias] [--force] [-y]` | Install a profile distribution from a git URL or local directory. |
| `update <name> [--force-config] [-y]` | Re-pull a distribution; preserves user data (memories, sessions, auth). |
| `info <name>` | Show a profile's distribution manifest (version, requirements, source). |

Examples:

```bash
robo profile list
robo profile create work --clone
robo profile use work
robo profile alias work --name h-work
robo profile export work -o work-backup.tar.gz
robo profile import work-backup.tar.gz --name restored
robo profile install github.com/user/my-distro --alias
robo profile update work
robo -p work chat -q "Hello from work profile"
```

## `robo completion`

```bash
robo completion [bash|zsh|fish]
```

Print a shell completion script to stdout. Source the output in your shell profile for tab-completion of Robo commands, subcommands, and profile names.

Examples:

```bash
# Bash
robo completion bash >> ~/.bashrc

# Zsh
robo completion zsh >> ~/.zshrc

# Fish
robo completion fish > ~/.config/fish/completions/robo.fish
```

## `robo update`

```bash
robo update [--gateway] [--check] [--no-backup] [--backup] [--yes]
```

Pulls the latest `robo-engineer` code and reinstalls dependencies in the managed venv, then re-runs the post-install hooks (MCP servers, skills sync, completion install). Safe to run on a live install. Use `--check` to see whether your checkout is behind `origin/main` without installing.

`robo update` pulls the configured update branch (default: `main`). If your checkout is on another branch, Robo may check out the update branch before pulling. Commit branch work before updating when you want to keep it outside the update autostash flow.

| Option | Description |
|--------|-------------|
| `--gateway` | Internal mode used by the messaging `/update` command. Uses file-based IPC for prompts and progress streaming instead of reading from terminal stdin. Not a gateway restart flag. |
| `--check` | Check whether an update is available without pulling, installing dependencies, or restarting anything. |
| `--no-backup` | Skip all pre-update backups for this run (both the quick state snapshot and the full zip), regardless of `updates.pre_update_backup`. |
| `--backup` | Force a **full** pre-update backup for this run: the quick state snapshot plus a complete zip of `ROBO_HOME` (config, auth, sessions, skills, pairing data). The default mode is `quick` — a lightweight state snapshot only. Set the permanent mode via `updates.pre_update_backup: quick | full | off` in `config.yaml`. |
| `--yes`, `-y` | Assume yes for interactive prompts such as config migration and stash restore. API-key entry is skipped; run `robo config migrate` separately for those. |

Additional behavior:

- **Gateway restart.** After a successful update, Robo attempts to restart all running gateway profiles automatically so they pick up the new code. Use `robo gateway restart` when you want to restart a gateway without applying an update.
- **Local source changes.** For git installs, dirty tracked files and untracked files are auto-stashed before branch checkout or pull (`git stash push --include-untracked`). Interactive terminal updates ask before restoring the stash. Non-interactive updates restore it by default; set `updates.non_interactive_local_changes: discard` only on managed installs where local source edits should be thrown away after a successful pull. If stash restore conflicts or the pull fails, the stash is left in place for manual recovery.
- **npm lockfile churn.** Before stashing or switching branches, Robo makes a best-effort cleanup of tracked `package-lock.json` diffs produced by npm install/build steps. Commit or manually stash intentional lockfile edits before running `robo update`.
- **Pairing data snapshot.** Even when `--backup` is off, `robo update` takes a lightweight snapshot of `~/.robo/pairing/` and the Feishu comment rules before `git pull`. You can roll it back with `robo backup restore --state pre-update` if a pull rewrites a file you were editing.
- **Legacy `robo.service` warning.** If Robo detects a pre-rename `robo.service` systemd unit (instead of the current `robo-gateway.service`), it prints a one-time migration hint so you can avoid flap-loop issues.
- **Exit codes.** `0` on success, `1` on pull/install/post-install errors, `2` on unexpected working-tree changes that block `git pull`.

## Maintenance commands

| Command | Description |
|---------|-------------|
| `robo version` | Print version information. |
| `robo update` | Pull latest changes and reinstall dependencies. |

| `robo uninstall [--full] [--gui] [--dry-run] [--yes]` | Remove Robo, optionally deleting all config/data. `--gui` removes only the desktop Chat GUI, leaving the agent intact; `--full` also deletes config/data; `--dry-run` prints what would be removed without changing anything; `--yes` skips prompts. |

## See also

- [Slash Commands Reference](./slash-commands.md)
- [CLI Interface](../user-guide/cli.md)
- [Sessions](../user-guide/sessions.md)
- [Skills System](../user-guide/features/skills.md)
- [Skins & Themes](../user-guide/features/skins.md)
