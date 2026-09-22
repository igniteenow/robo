---
name: binary-re
description: |
  Systematic, evidence-tracked reverse engineering of compiled binaries — disassembly,
  static analysis, dynamic analysis, and function-by-function coverage tracking so large
  or unfamiliar binaries get fully read rather than sampled. Covers ELF/PE/Mach-O targets,
  stripped binaries, and multi-day investigations that need to survive session restarts.
  Every claim about what code does must trace to actual tool output, never inference alone.
platforms: [linux, macos, windows]
category: security
triggers:
  - "reverse engineer this binary"
  - "disassemble this"
  - "analyze this executable"
  - "what does this binary do"
  - "RE this"
  - "understand this compiled program"
  - "trace this function"
  - "decompile this"
toolsets:
  - terminal
  - file
  - code_execution
  - delegation
  - memory
---

# Binary Reverse Engineering Skill

A disciplined workflow for reading compiled code exhaustively and reporting only what the
evidence actually supports. Built for targets that take hours — a large stripped binary, an
unfamiliar protocol implementation, a legacy driver — where the failure mode isn't running
out of tools, it's stopping early and describing the 20% that was skimmed as if it were the
whole picture.

This skill does not target live remote systems. For network/application penetration testing
use the `web-pentest` skill instead. This skill is for artifacts already on disk (or an
authorized, isolated dynamic-analysis environment) that you have the right to analyze.

---

## ⚠️ Anti-Hallucination Guardrails

Read these before every session. They are the actual point of this skill — a fast, confident,
wrong answer about what a binary does is worse than a slow, correct one.

1. **Evidence-First Rule**: Every claim about what a function, instruction sequence, or
   protocol does MUST cite the tool output it came from (`EV-XXXX`, see
   `scripts/evidence-store.py`). "This looks like it parses a header" without a citation is a
   hypothesis, not a finding — label it `[HYPOTHESIS]` and keep going until it's confirmed or
   disproved.
2. **No Semantic Guessing From Names Alone**: A function named `validate_token` might not
   validate anything — names lie (deliberately, in stripped/obfuscated/malicious binaries, or
   just from stale refactors). Symbol names are a *lead*, never a conclusion. Confirm behavior
   from the actual instructions, or from dynamic observation (args in, effects out).
3. **Fact vs. Hypothesis Separation**: Maintain running hypotheses explicitly (see
   `references/exhaustive-coverage-protocol.md`). A hypothesis graduates to a fact only when
   disassembly or a traced execution directly confirms it — not when it merely stops
   contradicting your expectations.
4. **Full-Coverage Rule, Not Sampling**: Before claiming to understand "what this binary
   does," you must be able to account for every exported/reachable function from the entry
   point (or explicitly say which ones remain unexamined and why). "I looked at the
   interesting-looking functions" is not reverse engineering a binary; it's reading a few
   functions of one.
5. **Stripped/Obfuscated ≠ Stuck**: Missing symbols is the normal case, not a blocker. Fall
   back to control-flow analysis, string/constant cross-references, calling convention and
   argument-count inference, and dynamic tracing. Say `[UNRESOLVED]` for anything you
   genuinely can't determine yet rather than filling the gap with a plausible-sounding guess.
6. **Never Fabricate Addresses, Offsets, or Byte Sequences**: If you don't have the actual
   tool output in front of you (in this turn or logged evidence), don't state a specific
   address, opcode, or offset from memory. Re-run the tool. This is the single most common
   source of subtly-wrong RE reports.
7. **Distinguish Static From Dynamic Claims**: "The disassembly shows X" (static) and "the
   traced execution showed X" (dynamic) are different strengths of evidence — say which one
   you have. Static analysis can miss self-modifying code, packers, and runtime-resolved
   calls; dynamic analysis can miss code paths that weren't exercised.
8. **Sandbox Discipline for Untrusted Samples**: Never execute a binary of unknown/untrusted
   provenance outside an isolated environment (container, VM, or the `execute_code` sandbox
   with network egress disabled). Static analysis (objdump/readelf/strings/a disassembler) is
   always safe; running it is not, until provenance is established.

---

## Workflow

### Phase 0 — Scope and Authorization

Populate `templates/authorization.md` from the assigned task before starting real analysis.
This is an audit artifact, not a gate — Robo's existing permission system already handles
consequential actions (see `tools/approval.py`); this record just keeps a clear trail of what
was in scope, matching the convention used by the `web-pentest` skill.

Record: the binary's path and SHA-256, where it came from, why you're authorized to analyze
it, and — if any dynamic analysis is planned — what isolation is in place.

### Phase 1 — Recon (fast, establishes the map)

Identify format, architecture, and the full symbol/function inventory before reading anything
line by line. See `references/tool-cheatsheet.md` for the concrete commands per platform.

- `file`, and format-specific headers (`readelf -h` / PE header / Mach-O header)
- Full export/import table and symbol list, even if mostly stripped
- Section layout, entry point, any embedded strings worth flagging early
- Build the **coverage checklist**: every function address you need to eventually account for

This checklist is the thing that makes "exhaustive" checkable rather than a vibe — see
`references/exhaustive-coverage-protocol.md`.

### Phase 2 — Systematic Static Analysis

Work the coverage checklist function by function, not by curiosity. For each function:
disassemble it fully, log an evidence entry for what it does, mark it `covered` in the
checklist. Cross-reference calls between functions as you go so the call graph builds itself
rather than needing a second pass.

Do not skip a function because it "looks like boilerplate" — log a one-line evidence entry
for it (even `"EV-0042: standard function prologue/epilogue, no side effects" — confirms
this is a trivial wrapper, not skipped analysis`) so the coverage record is honest about what
was actually checked versus assumed.

### Phase 3 — Dynamic Analysis (where static analysis plateaus)

When control flow depends on runtime values, packers/self-modifying code are suspected, or a
static read genuinely can't resolve an indirect call — move to a debugger, in an isolated
environment. Log traced values as dynamic evidence, distinct from static evidence (guardrail
#7).

### Phase 4 — Hypothesis Resolution

Every `[HYPOTHESIS]` from Phases 1–3 gets resolved: confirmed (cite the evidence), disproved
(cite the counter-evidence), or explicitly carried forward as `[UNRESOLVED]` in the final
report. A hypothesis is never silently dropped.

### Phase 5 — Report

Use `templates/re-report.md`. Every finding cites its evidence IDs. Every unresolved area is
listed, not omitted. State coverage explicitly: "N of M reachable functions fully analyzed;
remainder are `[UNRESOLVED]` — see list" rather than implying completeness that wasn't
achieved.

---

## Long-Running and Multi-Session Work

A real binary can take hours or span multiple sessions. Don't try to hold the whole
investigation in the model's own context:

- **Evidence store persists on disk** (`scripts/evidence-store.py`) — the coverage checklist
  and every logged finding survive a session restart. Resuming means loading the store and
  continuing from the first `pending` entry, not starting over.
- **Use Robo's own session/task persistence** for the conversation itself (see
  `robo_state.py` / `tools/checkpoint_manager.py`) — `robo --resume <session>` picks up the
  actual conversation where it left off; the evidence store is what makes that resumption
  *substantively* continuable instead of just re-reading old chat history.
- **Delegate wide-but-shallow sub-tasks**: if the coverage checklist has many independent
  leaf functions, `delegate_task` sub-agents can each own a batch and report back evidence
  entries — parallel breadth, not parallel guessing. Keep one agent (you) responsible for the
  overall hypothesis graph so nothing gets double-counted or lost between workers.
- **A slow, honestly-partial report beats a fast, falsely-complete one.** If a session ends
  before coverage is complete, say exactly what's covered and what isn't — that's what makes
  the next session (yours or the user's) able to pick up cleanly instead of re-deriving scope
  from scratch.

---

## Working With the Existing Permission System

Reading a binary (disassembly, `strings`, static analysis) is not a dangerous action and
should not require approval prompts. Running an unfamiliar binary — especially one of
unknown provenance — is exactly the kind of action `tools/approval.py`'s dangerous-command
detection exists for; don't try to route around it. If a legitimate dynamic-analysis step
keeps getting an approval prompt, that's the permission system doing its job — get the
explicit approval rather than looking for a way to skip it.
