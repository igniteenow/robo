#!/usr/bin/env python3
"""Deep reverse-engineering tool for Robo.

``reverse_engineer`` gives the agent a Ghidra-MCP-style workflow with no MCP
server required: it drives a stateful analysis engine
(:mod:`tools.re_engine`) that auto-detects the strongest RE software on the
machine — Ghidra headless (bundled post-scripts, persistent project per
binary), radare2 / rizin, binutils + capstone — and always falls back to a
pure-Python ELF/PE/Mach-O parser, so *some* answer is available everywhere.

Typical loop (each call is fast after the first analysis):

    overview            → what is it, arch, hardening, notable imports/strings
    functions           → paged list (sort=size|callers, query=<regex>)
    decompile main      → C from Ghidra / r2ghidra, else pseudo-C, else disasm
    xrefs <fn|0xaddr>   → who calls / references this (also works for strings)
    strings query=tag:url / with_refs=true → interesting strings and the code that uses them
    callgraph <fn>      → callers / callees tree
    search 48 8b ?? c3  → byte pattern / text search with function attribution
    read 0x4020 length=64 → hexdump at a virtual address
    rename / comment / note → build up understanding; persisted per binary

Security properties
-------------------
* The target is **never executed**. Every backend performs static analysis.
* Backends are invoked with argv lists (no shell) and an allow-listed action
  enum; free-text arguments (names, regexes, comment text) never reach a shell.
* Analysis artifacts live in ``$ROBO_HOME/re/<sha256>/`` — keyed by content
  hash, so nothing is written next to the target.
* When the active terminal backend is remote (SSH / container) and the file
  is not on this machine, the tool degrades to running radare2 / binutils
  commands *through* the terminal tool, inheriting its sandbox and approval
  flow (structural + disassembly actions only).
"""
from __future__ import annotations

import os
import shlex
from typing import Any, Dict

from tools.registry import registry

_VALID_ACTIONS = [
    "overview", "capabilities", "functions", "decompile", "disassemble", "xrefs", "callgraph",
    "strings", "imports", "exports", "symbols", "sections", "search", "read", "entropy",
    "security", "hashes", "rename", "comment", "note", "notes", "analyze", "workspace",
]

# Remote (terminal-routed) fallback: action → ordered (binary, command template)
# where {t} is the shell-quoted target and {a} the shell-quoted function/address.
_REMOTE_CHAINS: Dict[str, list] = {
    "overview":    [("r2", "r2 -q -e scr.color=0 -c 'iI; ie; il' {t}"), ("file", "file -b {t}; readelf -h {t} 2>/dev/null | head -30")],
    "functions":   [("r2", "r2 -q -e scr.color=0 -c 'aaa; afl' {t}"), ("nm", "nm -C --defined-only {t} 2>/dev/null | grep -i ' t ' | head -400")],
    "decompile":   [("r2", "r2 -q -e scr.color=0 -c 'aaa; pdg @ {a} 2>/dev/null || pdc @ {a}' {t}")],
    "disassemble": [("r2", "r2 -q -e scr.color=0 -c 'aaa; pdf @ {a}' {t}"), ("objdump", "objdump -d -M intel --disassemble={a} {t} | head -400")],
    "xrefs":       [("r2", "r2 -q -e scr.color=0 -c 'aaa; axt @ {a}; axf @ {a}' {t}")],
    "strings":     [("r2", "r2 -q -e scr.color=0 -c 'izz' {t}"), ("strings", "strings -a -t x -n 6 {t}")],
    "imports":     [("r2", "r2 -q -e scr.color=0 -c 'ii; il' {t}"), ("objdump", "objdump -p {t}"), ("readelf", "readelf -d {t}")],
    "exports":     [("r2", "r2 -q -e scr.color=0 -c 'iE' {t}"), ("nm", "nm -DC --defined-only {t}")],
    "symbols":     [("r2", "r2 -q -e scr.color=0 -c 'is' {t}"), ("nm", "nm -C {t}")],
    "sections":    [("r2", "r2 -q -e scr.color=0 -c 'iS' {t}"), ("readelf", "readelf -hSl {t}"), ("objdump", "objdump -x {t}")],
    "security":    [("checksec", "checksec --file={t}"), ("r2", "r2 -q -e scr.color=0 -c 'iI' {t}"), ("readelf", "readelf -hd {t}")],
    "hashes":      [("sha256sum", "sha256sum {t}; md5sum {t}")],
    "entropy":     [("r2", "r2 -q -e scr.color=0 -c 'iS entropy' {t}"), ("ent", "ent {t}")],
    "read":        [("xxd", "xxd -s {a} -l 256 {t}"), ("od", "od -A x -t x1z -j {a} -N 256 {t}")],
    "search":      [("r2", "r2 -q -e scr.color=0 -c '/x {a}' {t}"), ("grep", "grep -obUaP {a} {t} | head -50")],
}


def _terminal_env_is_local() -> bool:
    try:
        from robo_cli.config import load_config_readonly
        term = (load_config_readonly() or {}).get("terminal") or {}
        return str(term.get("backend", "local") or "local").lower() in ("local", "")
    except Exception:
        return True


def _remote_fallback(target: str, action: str, spec: str, task_id, session_id) -> str:
    from tools.terminal_tool import terminal_tool

    chain = _REMOTE_CHAINS.get(action)
    if not chain:
        return (f"action '{action}' needs the file on this machine (remote terminal backend detected). "
                "Copy the binary locally, or use one of: " + ", ".join(sorted(_REMOTE_CHAINS)))
    quoted = shlex.quote(target)
    aq = shlex.quote(spec or "main")

    def probe(binary: str) -> bool:
        out = terminal_tool(command=f"command -v {shlex.quote(binary)} >/dev/null 2>&1 && echo __OK__ || echo __NO__",
                            timeout=20, task_id=task_id, session_id=session_id)
        return "__OK__" in (out or "")

    exists = terminal_tool(command=f"test -e {quoted} && echo __EXISTS__ || echo __MISSING__", timeout=20,
                           task_id=task_id, session_id=session_id)
    if "__MISSING__" in (exists or ""):
        return f"Target not found on the remote execution backend: {target}"
    for binary, template in chain:
        if probe(binary):
            cmd = template.format(t=quoted, a=aq)
            out = terminal_tool(command=cmd, timeout=600, task_id=task_id, session_id=session_id)
            return (f"# reverse_engineer · {action} · remote backend via terminal ({binary})\n"
                    f"# (structural / disassembly only; copy the file locally for the full engine)\n\n{out}")
    return (f"No tool for '{action}' on the remote backend. Install radare2 (`apt install radare2`) or binutils there, "
            "or copy the binary to this machine.")


def reverse_engineer(target: str = "", action: str = "overview", **kw: Any) -> str:
    """Run one action of the reverse-engineering engine against *target*."""
    action = (action or "overview").strip().lower()
    task_id = kw.pop("task_id", None)
    session_id = kw.pop("session_id", None)
    if action not in _VALID_ACTIONS:
        return f"Unknown action '{action}'. Valid: {', '.join(_VALID_ACTIONS)}"
    from tools.re_engine.engine import run_action

    if action == "capabilities":
        return run_action("", "capabilities")
    if not target or not str(target).strip():
        return "No target path provided. Pass the path to the binary to analyze."
    target = os.path.expanduser(str(target).strip())
    if not os.path.isfile(target) and not _terminal_env_is_local():
        return _remote_fallback(target, action, str(kw.get("function") or kw.get("address") or kw.get("query") or ""),
                                task_id, session_id)
    return run_action(target, action, **kw)


REVERSE_ENGINEER_DESCRIPTION = (
    "Deep, stateful reverse engineering of compiled binaries, shared libraries, drivers, firmware and other "
    "opaque artifacts — the workflow you would drive in Ghidra, without needing Ghidra open or an MCP server. "
    "Auto-detects the strongest analyzer installed (Ghidra headless with a persistent per-binary project and real "
    "decompiler → radare2/rizin (r2ghidra decompiler if present, else pseudo-C) → binutils/capstone) and always "
    "falls back to a built-in ELF/PE/Mach-O parser. Never executes the target. Results are cached per file "
    "(sha256) so follow-up calls are instant, and rename/comment/note annotations persist across sessions.\n"
    "Workflow: action=overview → action=functions (sort=size|callers, query=regex) → action=decompile "
    "function=main (or 0xaddr) → action=xrefs function=<name|0xaddr|string> → action=strings query=tagged|tag:url "
    "with_refs=true → action=callgraph → action=search query='48 8b ?? c3' or text → action=read address=0x... "
    "length=64. Record findings with action=rename/comment/note so later calls show them. Page long lists with "
    "limit/offset. action=capabilities reports which backends exist and how to install missing ones."
)

REVERSE_ENGINEER_SCHEMA = {
    "name": "reverse_engineer",
    "description": REVERSE_ENGINEER_DESCRIPTION,
    "parameters": {
        "type": "object",
        "properties": {
            "target": {
                "type": "string",
                "description": "Path to the binary or artifact to analyze (local path; inspected, never executed). Not needed for action=capabilities.",
            },
            "action": {
                "type": "string",
                "enum": _VALID_ACTIONS,
                "default": "overview",
                "description": (
                    "overview=identify/arch/hardening/notable imports+strings; capabilities=installed backends; "
                    "functions=list; decompile=C for one function; disassemble=listing; xrefs=references to/from a "
                    "function, address or string; callgraph=callers/callees tree; strings=strings (with code refs); "
                    "imports/exports/symbols/sections; search=hex bytes (?? wildcard) or text/regex; read=hexdump at an "
                    "address; entropy=packing detection; security=hardening report; hashes; rename/comment/note=persist "
                    "your understanding; notes=show annotations; analyze=force re-analysis; workspace=cache info."
                ),
            },
            "function": {
                "type": "string",
                "description": "Function name, renamed name, or hex address (0x401000) for decompile/disassemble/xrefs/callgraph/rename/comment. Defaults to main/entry for decompile.",
            },
            "address": {
                "type": "string",
                "description": "Hex virtual address (0x...) or 'offset:0x...' file offset — for read/disassemble/xrefs when no function name applies.",
            },
            "query": {
                "type": "string",
                "description": "Filter regex (functions/strings/imports/exports/symbols); for strings also 'tagged' or 'tag:url|ip|path|format|credential|exec|api|sql'; for search: hex bytes with ?? wildcards, or text/regex.",
            },
            "limit": {"type": "integer", "default": 200, "description": "Max rows per page (1-5000)."},
            "offset": {"type": "integer", "default": 0, "description": "Row offset for paging."},
            "length": {"type": "integer", "description": "read: bytes to dump (16-65536). disassemble: instruction count (0/omit = whole function)."},
            "sort": {"type": "string", "enum": ["addr", "size", "callers"], "description": "functions: sort order (size/callers surfaces the interesting ones)."},
            "depth": {"type": "integer", "default": 2, "description": "callgraph: tree depth (1-5)."},
            "min_length": {"type": "integer", "default": 4, "description": "strings: minimum length."},
            "with_refs": {"type": "boolean", "default": False, "description": "strings: only strings referenced from code (needs ghidra/radare2/binutils backend)."},
            "new_name": {"type": "string", "description": "rename: the new function/label name."},
            "text": {"type": "string", "description": "comment/note: the text to record."},
            "backend": {
                "type": "string",
                "enum": ["auto", "ghidra", "radare2", "rizin", "binutils", "python"],
                "default": "auto",
                "description": "Force a backend (auto picks the strongest installed).",
            },
        },
        "required": ["target"],
    },
}


def _check_reverse_engineering_requirements() -> bool:
    """Always available: the pure-Python parser needs nothing installed."""
    return True


def _handle_reverse_engineer(args, **kw):
    params = dict(args or {})
    target = params.pop("target", "")
    action = params.pop("action", "overview")
    return reverse_engineer(
        target=target,
        action=action,
        task_id=kw.get("task_id"),
        session_id=kw.get("session_id"),
        **params,
    )


registry.register(
    name="reverse_engineer",
    toolset="reverse_engineering",
    schema=REVERSE_ENGINEER_SCHEMA,
    handler=_handle_reverse_engineer,
    check_fn=_check_reverse_engineering_requirements,
    emoji="🔬",
    max_result_size_chars=200_000,
)
