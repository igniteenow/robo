# Exhaustive Coverage Protocol

The difference between "I looked at this binary" and "I reverse engineered this binary" is
whether you can produce a checklist showing every reachable function was actually accounted
for — not just the ones that looked interesting.

## Why sampling fails silently

A model (or a human) skimming a disassembly naturally gravitates toward functions with
recognizable names, obvious string references, or familiar patterns. That's a reasonable
prioritization for *finding something fast*, but it quietly produces a report that describes
20-30% of the binary while implying full understanding — the reader has no way to tell which
claim rests on real analysis and which rests on "the rest is probably just error handling."
The coverage checklist makes that distinction externally checkable instead of a private
impression.

## The protocol

1. **Enumerate before reading.** Phase 1 produces the full function address list — from
   symbols if present, from `objdump -d`'s address markers if stripped. This list is seeded
   into the coverage store with `cov-init` *before* any function gets read in detail. This
   ordering matters: it's what prevents the checklist from silently growing to match whatever
   got covered, rather than the other way around.

2. **Every function gets one of exactly four end states**, never left implicit:
   - `covered` — disassembled and understood well enough to describe its behavior, with an
     evidence entry backing that description.
   - `skipped_trivial` — genuinely trivial (e.g. a bare `jmp` to a PLT stub, a
     compiler-generated thunk) — still gets a one-line evidence entry saying so. "Trivial" is
     a conclusion you reached, not a reason to skip logging it.
   - `unresolved` — examined, but genuinely couldn't be determined (indirect calls resolved
     only at runtime, packed/obfuscated code, or it needs dynamic analysis to move further).
     This is a legitimate, honest end state — better than a guess.
   - `pending` — not yet reached. This should only be true for functions the current session
     hasn't gotten to, never as a place to quietly leave something you looked at and couldn't
     figure out.

3. **`cov-next` is how you resume**, whether resuming five minutes later or five days later
   after a session restart. It always returns the next `pending` entry — there's no need to
   remember where you were, and no temptation to jump to "the interesting parts" instead of
   working the list in order.

4. **The report's coverage statement is generated from the store, not from memory.** Run
   `summary` and report the real numbers: "47 of 52 functions covered, 3 unresolved (indirect
   calls only resolvable at runtime — see EV-0031, EV-0034, EV-0040), 2 skipped as trivial PLT
   stubs." That sentence is either true (because it's read off the checklist) or it's the
   thing this whole protocol exists to prevent.

## When the checklist is huge

A large binary can have thousands of functions. Exhaustive doesn't mean "manually disassemble
every single one at the same depth" — it means every one gets a real end state:

- Batch triage first: many functions in a large binary are compiler-generated boilerplate
  (bounds checkers, C++ vtable thunks, exception-handling landing pads). Recognize these
  *patterns* once, then mark matching functions `skipped_trivial` with a shared evidence
  entry explaining the pattern-match — still logged, still honest, just not re-derived from
  scratch thousands of times.
- Depth should scale with relevance: a function that's on the path from an interesting string
  reference or an exported entry point earns a full read; a leaf utility function three calls
  removed from anything security/behavior-relevant can get a lighter pass, but still an
  explicit `covered` or `skipped_trivial`, not silence.
- Delegate breadth, not judgment: `delegate_task` sub-agents can each work through a batch of
  independent leaf functions and report evidence entries back. Keep the hypothesis graph and
  the "is this actually trivial" judgment calls with the primary agent so nothing gets
  double-counted or inconsistently classified between workers.
