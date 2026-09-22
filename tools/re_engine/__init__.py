"""Robo reverse-engineering engine.

A stateful, backend-agnostic static-analysis engine behind the
``reverse_engineer`` tool. It gives the agent the same *kind* of workflow it
would have driving Ghidra through an MCP server — list functions, decompile
one, follow cross-references, read strings with their referencing code,
rename/comment as understanding grows — without requiring any MCP server.

Layers (lowest first):

* :mod:`tools.re_engine.formats` — pure-Python ELF / PE / Mach-O parsers
  (headers, sections/segments, symbols, imports/exports, strings with
  offsets, entropy, hashes). Zero external dependencies; works everywhere.
* :mod:`tools.re_engine.backends` — adapters for whatever real RE tooling is
  installed: Ghidra headless (bundled post-scripts), radare2 / rizin,
  binutils (+ capstone when importable). Detected automatically; the best
  available backend is used per action and the tool says which one it used.
* :mod:`tools.re_engine.workspace` — per-target cache directory keyed by the
  file's SHA-256 (analysis snapshots, decompiled functions, the persistent
  Ghidra project, user annotations) so follow-up queries are instant and
  survive across sessions.
* :mod:`tools.re_engine.engine` — the action dispatcher the tool calls.

Nothing in this package ever executes the target binary.
"""
