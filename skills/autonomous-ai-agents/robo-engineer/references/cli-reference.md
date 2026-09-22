# Robo CLI Reference

Live sources when anything looks stale: `robo --help`, `robo <command> --help`,
../../../../website/docs/reference/cli-commands.md

### Global Flags

```
robo [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
robo chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
robo setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
robo model                Interactive model/provider picker
robo fallback [add|remove|list]  Fallback provider chain
robo config [show|edit|get|set|unset|path|env-path|check|migrate]
robo login / logout       OAuth sign-in / clear stored auth
robo doctor [--fix]       Check dependencies and config
robo status [--all]       Component status
```

### Tools & Skills

```
robo tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

robo skills list|browse|search QUERY|inspect ID
robo skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
robo skills config        Enable/disable skills per platform
robo skills check|update|uninstall|publish PATH
robo skills tap add REPO  Add a GitHub repo as a skill source
robo bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
robo mcp add NAME (--url or --command) | remove | list | test NAME
robo mcp catalog | install NAME     Curated catalog install
robo mcp configure NAME             Toggle tool selection
robo mcp serve                      Run Robo as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
robo gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `robo photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: ../../../../website/docs/user-guide/messaging/index.md

### Sessions

```
robo sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
robo cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
robo webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
robo profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
robo profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
robo auth                 Interactive credential manager
robo auth add [PROVIDER]  Add OAuth or API-key credential (igniteenow, openai-codex, qwen-oauth, …)
robo auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
robo desktop / gui        Native desktop app
robo dashboard            Web admin panel + embedded chat (--stop / --status)
robo proxy                OpenAI-compatible local proxy backed by an OAuth provider
robo portal               Quick setup / sign in via Ignitee Now Portal
robo kanban <verb>        Multi-agent work-queue board
robo project              Named multi-folder workspaces
robo skin list|use|set    Switch/tweak skins (see references/themes.md)
robo pets <verb>          Pet mascots (see references/petdex.md)
robo memory setup|status|off|reset   Memory provider
robo secrets bitwarden|onepassword   External secret stores
robo moa                  Mixture-of-Agents slots
robo hooks / security / backup / import / checkpoints / console
robo logs [-f] [errors]   View agent/error logs
robo send                 One-off message through a gateway platform
robo pairing / plugins / insights / journey / computer-use
robo acp                  ACP server (IDE integration)
robo completion bash|zsh|fish
robo update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `robo photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `robo config edit` · [Configuration docs](../../../../website/docs/user-guide/configuration.md) |
| Tools / toolsets | `robo tools list` · [Tools reference](../../../../website/docs/reference/tools-reference.md) |
| Skills catalog | `robo skills browse` · [Skills catalog](../../../../website/docs/reference/skills-catalog.md) |
| Provider setup | `robo model` · [Providers guide](../../../../website/docs/integrations/providers.md) |
| Env variables | `robo config env-path` · [Env vars reference](../../../../website/docs/reference/environment-variables.md) |
| Gateway logs | `~/.robo/logs/gateway.log` (or `robo logs`) |
| Sessions | `robo sessions browse` (reads state.db) |
