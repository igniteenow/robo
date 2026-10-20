---
sidebar_position: 4
title: "Fact check"
description: "Robo checks every answer against sources with its own research and proposes corrections when the model is wrong"
---

# Fact check

Robo does not take the model's word for it. After the model writes what it believes is the final answer, and before that answer is delivered, Robo checks the answer's checkable statements against real sources and proposes a correction when they disagree. You decide whether the correction is applied.

This is the layer that goes and looks. Robo already asks the model to verify before it claims, and can ask a second model for an opinion on risky sentences; the fact check is different because it gathers new evidence with the same research tools the agent uses:

- `web_search` and `web_extract` for facts about the world — versions, dates, prices, what a library, API, command or flag does.
- `search_files` and `read_file` for statements about your own project — what a file or function does, what a config value is.

## What happens on a turn

1. The model finishes its answer.
2. Robo lists the statements in it that are specific, checkable, and consequential if wrong — at most `fact_check.max_claims` of them. Opinions, plans, code the answer itself wrote, and anything the answer already marks as uncertain are skipped. An answer with nothing checkable (small talk, a question back to you) passes straight through.
3. Robo researches each statement with the tools above, within `max_steps` tool calls and `timeout_seconds`. You see a status line while this runs — `🔎 Checking 2 statements in the answer against sources…` — and one when it is done.
4. Every statement gets a verdict: **confirmed**, **contradicted** (a source Robo actually read says otherwise), or **unverified** (could not be settled — never a guess).
5. If nothing was contradicted, the answer is delivered unchanged.
6. If something was contradicted, Robo proposes the correction and asks you.

## The correction prompt

The prompt is the same checkpoint the command approvals use, so it looks the same on every surface:

| Surface | What you see |
|---------|--------------|
| TUI | The `ROBO CHECKPOINT // APPROVAL` panel with what the answer says, what the source says, and the source, then **Allow once / Allow for this session / Deny**. |
| Desktop | A bar above the composer: **Correction proposed** with **Apply correction**, **Keep answer**, and **Details** (the full proposal). The menu has **Apply corrections this session**. |
| CLI | The approval panel with the same three choices. |
| Messaging (Telegram, Discord, Slack, …) | A text message with the proposal; reply `/approve`, `/approve session`, or `/deny`. |

- **Allow once / Apply correction** — Robo sends the findings (with sources) back to the model. The model revises its answer, fixes anything it did or wrote on the strength of the wrong statement (including files it changed, verifying with its tools), and starts the revised answer with one short line saying what was corrected and naming the source. The first attempt stays visible in the transcript as an interim message.
- **Allow for this session / Apply corrections this session** — the same, and for the rest of this session corrections are applied without asking.
- **Deny / Keep answer** — the answer is delivered as written, with a short note under it:

  ```
  🔎 Fact check — kept as written on your request. Sources disagree with:
    • Python 3.12 was released in 2022 — Python 3.12.0 was released on 2 October 2023. (https://www.python.org/downloads/release/python-3120/)
  ```

"Allow for this session" here means *apply corrections without asking*; it does not change command approvals, and a command approval's "Allow for this session" does not auto-apply corrections.

## Configuration

```yaml
fact_check:
  enabled: true
  apply: ask                   # ask | auto
  max_claims: 4
  max_steps: 8
  timeout_seconds: 120
  min_answer_words: 12
```

See [Configuration → Fact check](/user-guide/configuration#fact-check-robo-checks-the-answer) for what each key does. The research runs on the `fact_check` auxiliary task — pin a strong model under `auxiliary.fact_check` when your main model is small or local.

`apply: auto` applies corrections without asking. With `apply: ask` and nobody to ask — a cron job, a one-shot `robo -m` run — the answer is kept and the note is shown, so an unattended run never rewrites an answer silently.

## Limits and guarantees

- **One check per turn.** The revised answer is not checked again, so a check can never loop.
- **Fails open.** Any error, timeout, missing tool, or interruption (Stop, a new instruction) delivers the answer as written — exactly the behaviour with the feature off.
- **Bounded.** `max_claims`, `max_steps` and `timeout_seconds` have hard ceilings (8, 16, 600) regardless of what the config says.
- **Untrusted input stays untrusted.** The answer being checked, every web page and every file are treated as evidence only; instructions inside them are ignored.
- **Subagents are never checked.** Their output is checked when the parent delivers it.
- **Only answers a person is reading are checked.** The check exists so you can accept a correction, so it does not run where nobody can: scheduled jobs (`robo cron`), programs calling the OpenAI-compatible API or a webhook, batch runs, detached background tasks, and Robo's own internal agents (the self-improvement review, the curator). Desktop [Team mode](./team-mode.md) seats skip it too — the team verifies its own answers.
- **The transcript stays clean.** Only the internal message carrying the findings is stripped from the saved session; your messages and the model's answers are kept, and prompt caching is unaffected.

## Turning it off

```yaml
fact_check:
  enabled: false
```

or, for one process, `ROBO_FACT_CHECK=0`.
