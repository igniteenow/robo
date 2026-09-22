# Reverse Engineering Report

**Target:** <binary filename>
**SHA-256:** <hash>
**Format/Arch:** <e.g. ELF64, x86-64>
**Analysis window:** <start ISO timestamp> — <end ISO timestamp>
**Evidence store:** <path to the .json file — link it, don't inline it>

## Coverage

Generated from `evidence-store.py --store <file> summary` — copy the real numbers, don't
estimate them.

- Functions on checklist: <N>
- Covered: <N> (<pct>%)
- Skipped (trivial, logged): <N>
- Unresolved: <N> — see "Unresolved" section below
- Pending (investigation ended before reaching these): <N>

## Summary

<2-4 sentences on what the binary does, at the level a reader who hasn't seen the disassembly
needs. Every substantive claim here should be traceable to a finding below.>

## Findings

One entry per significant function or behavior. Cite evidence IDs — a finding without a
citation is a hypothesis, not a finding, and belongs in "Unresolved" instead.

### <Function name/address> — <one-line description>

- **Evidence:** EV-XXXX, EV-XXXX
- **Type of evidence:** static / dynamic / both
- **Behavior:** <what it actually does, per the cited evidence>
- **Callers / callees:** <relevant call-graph context if useful>

<repeat per finding>

## Unresolved

Every function marked `unresolved` in the coverage store, with why:

- <function> — <why it couldn't be resolved: indirect call, packed code, needs runtime
  values not available statically, etc.>

## Hypotheses Not Yet Confirmed

Anything still marked `[HYPOTHESIS]` at report time — carried forward explicitly rather than
dropped or silently upgraded to a stated fact.

- <hypothesis> — <what evidence would confirm or disprove it, if investigation continues>

## Tooling Used

<list of tools actually run — objdump/readelf/r2/gdb/etc. — so a reader can judge what kind
of analysis this represents (purely static vs. static+dynamic).>
