# Langfuse Observability Plugin

This plugin ships bundled with Robo but is **opt-in** — it only loads when
you explicitly enable it.

## Enable

Pick one:

```bash
# Interactive: walks you through credentials + SDK install + enable
robo tools  # → Langfuse Observability

# Manual
pip install langfuse
robo plugins enable observability/langfuse
```

## Required credentials

Set these in `~/.robo/.env` (or via `robo tools`):

```bash
ROBO_LANGFUSE_PUBLIC_KEY=pk-lf-...
ROBO_LANGFUSE_SECRET_KEY=sk-lf-...
ROBO_LANGFUSE_BASE_URL=https://cloud.langfuse.com   # or your self-hosted URL
```

Without the SDK or credentials the hooks no-op silently — the plugin fails
open.

## Verify

```bash
robo plugins list                 # observability/langfuse should show "enabled"
robo chat -q "hello"              # then check Langfuse for a "Robo turn" trace
```

## Optional tuning

```bash
ROBO_LANGFUSE_ENV=production       # environment tag
ROBO_LANGFUSE_RELEASE=v1.0.0       # release tag
ROBO_LANGFUSE_SAMPLE_RATE=0.5      # sample 50% of traces
ROBO_LANGFUSE_MAX_CHARS=12000      # max chars per field (default: 12000)
ROBO_LANGFUSE_DEBUG=true           # verbose plugin logging
```

## Disable

```bash
robo plugins disable observability/langfuse
```
