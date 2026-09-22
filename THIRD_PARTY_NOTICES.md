# Third-party notices

Robo is developed, branded, and maintained by **Ignitee Now**. The product
identity, wake models, face, installers, defaults, terminal experience, desktop
experience are Ignitee Now's own.

This file is the single place where third-party origin and credit are recorded.
Keeping it here, rather than scattered through source comments, keeps the
product surface clean while staying accurate about where things came from.

## Upstream code (MIT)

Portions of the codebase derive from software originally published under the
MIT License by Nous Research and its contributors. The MIT License requires
that its copyright and permission notice be retained in all copies or
substantial portions of the software; that notice is preserved in
[`LICENSE`](LICENSE) alongside Ignitee Now's own copyright. **Do not remove
that line.** It is a legal record only and does not form part of Robo's product
identity, user interface, or runtime branding. Ignitee Now owns the Robo brand
and every modification it has made; it does not own, and does not claim, the
copyright in the original upstream code.

A number of bundled skills under `skills/` and `optional-skills/` also
originate from that upstream project. Skills written by other third parties
keep their own `author:` credit and any licence notice in their `SKILL.md`.

## Ideas adapted from other open-source agents

Several robustness fixes and regression tests were informed by publicly
documented issues in other MIT-licensed agent projects, including OpenClaw
(formerly Clawdbot), NEAR AI's IronClaw, and NanoClaw. These are independent
Python implementations, not copies of those projects' code.

## Third-party model identifiers

Strings such as `nousresearch/hermes-4-405b` and `hermes-3-llama-3.1-70b` are
the real catalogue identifiers of third-party open-weight models that Robo can
use. They are names of someone else's product, used to address it, in the same
way `gpt-*` or `claude-*` identifiers are. `is_hermes_chat_non_agentic()` in
`robo_cli/model_switch.py` warns users when they select one of those chat
models for agentic work, because they do not support tool calling.

## Identifiers owned by other services (must not be renamed)

These strings are defined by somebody else's server. Renaming them would not
rebrand anything; it would break the integration.

| String | Where | Why it stays |
|---|---|---|
| `yuanbao_openclaw_proxy` | `gateway/platforms/yuanbao_proto.py` | Tencent Yuanbao protobuf package name on the wire |
| `q.qq.com/qqbot/openclaw/...` | `gateway/platforms/qqbot/constants.py` | Tencent-hosted QQ bot onboarding URL |
| `openClaw` registration source | `robo_cli/dingtalk_auth.py` | The identity DingTalk's server has registered; users are told about it during setup. Override with `DINGTALK_REGISTRATION_SOURCE` once DingTalk registers Robo |
| `hermes-0day` | `robo_cli/mcp_security.py` | A literal attacker artefact matched by the MCP blocklist. Changing it disables a security control |
| `clawd*` slug filter | pet picker (TUI and desktop) | Hides placeholder entries in the external petdex gallery so they never appear in Robo |
| `clawhub` | `tools/skills_hub.py` | Name of an external skill marketplace, alongside GitHub, skills.sh, LobeHub and browse.sh. Switch it off with `skills.disabled_hub_sources: [clawhub]` |

## Shared UI component library

`packages/ui` is Ignitee Now's own implementation of the shared components,
written from `docs/ui-kit/SPEC.md` (an interface description extracted from
Robo's own call sites). It carries an Ignitee Now copyright alone, has no
third-party runtime dependencies beyond React, and is wired in as an npm
workspace package. No part of Robo's build downloads a UI package from any
third party. `tests/test_first_party_ui.py` fails the build if that changes.

## Fonts

- **Poppins** is Robo's brand typeface across the dashboard, desktop app, docs
  site and login page. It is distributed under the SIL Open Font
  License 1.1, which permits bundling and embedding in commercial software.
  Its two conditions: the licence text must travel with the font files (it
  does, as `OFL.txt` beside every copy), and the fonts may not be sold on
  their own. The shipped files are Latin subsets built from the upstream
  release. Source of truth: `assets/brand/fonts/`.
- **JetBrains Mono** (`apps/desktop/src/fonts/`, `web/public/fonts-terminal/`)
  is distributed under the SIL Open Font License 1.1. Confirm and keep its
  licence text with the font files when publishing.
- **Collapse, Mondwest, Rules Compressed, Rules Expanded** are upstream's brand
  typefaces and appear to be commercially licensed; upstream deliberately
  git-ignores them and later releases of its UI package stopped bundling them.
  The seven `.woff2` files that were in `web/public/fonts/` have been **removed
  from this distribution**. Every CSS stack that names them falls back to a
  system font, so nothing breaks. Every reference to them now points at
  Poppins.

## Other dependencies

All other third-party Python and JavaScript dependencies are listed with their
pinned versions in `pyproject.toml`, `package.json`, and the workspace
`package.json` files, and are distributed under their respective licences.
