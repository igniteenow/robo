"""Action dispatcher for the ``reverse_engineer`` tool.

Turns a (target, action, params) request into a compact, readable report,
using the strongest installed backend and the per-target workspace cache.
Output is deliberately dense and paginated: the model is expected to call
this many times in a loop (overview → functions → decompile main → xrefs →
strings → …) the way an analyst drives Ghidra.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from .backends import (
    Backend, BackendError, GhidraBackend, PythonBackend, capabilities_report, detect_tools,
    make_backend, select_backend,
)
from .formats import BinaryInfo, classify_string, hexdump, parse_binary, shannon_entropy
from .workspace import Workspace, parse_address

ACTIONS = [
    "overview", "capabilities", "functions", "decompile", "disassemble", "xrefs", "callgraph",
    "strings", "imports", "exports", "symbols", "sections", "search", "read", "entropy",
    "security", "hashes", "rename", "comment", "note", "notes", "analyze", "workspace",
]

_MAX_TARGET_BYTES = 512 * 1024 * 1024  # refuse to slurp >512 MB into memory


def _fmt_addr(a: Optional[int]) -> str:
    return f"0x{a:x}" if isinstance(a, int) else "?"


def _resolve_function(snap: dict, ws: Workspace, spec: str) -> Optional[dict]:
    """Find a function by name, renamed name, or address (exact / containing)."""
    if not spec:
        return None
    funcs = snap.get("functions", []) or []
    addr = parse_address(spec) if re.fullmatch(r"(?:0x)?[0-9a-fA-F]+", spec.strip()) else None
    renamed = ws.resolve_renamed(spec.strip())
    if renamed is not None:
        addr = renamed
    if addr is not None:
        for f in funcs:
            if f.get("addr") == addr:
                return f
        for f in funcs:
            size = f.get("size") or 0
            if size and f.get("addr", 0) <= addr < f.get("addr", 0) + size:
                return f
    name = spec.strip()
    for f in funcs:
        if f.get("name") == name:
            return f
    # Common decorations: FUN_00401000, sym.main, _main, main@plt
    cands = [f for f in funcs if f.get("name", "").endswith(("." + name, "_" + name)) or f.get("name", "").rstrip("_").endswith(name)]
    if len(cands) == 1:
        return cands[0]
    if addr is not None:
        return {"name": f"loc_{addr:x}", "addr": addr, "size": 0, "signature": "", "callers": [], "callees": []}
    return None


class REEngine:
    def __init__(self, target: str, backend: str = "auto"):
        self.target = os.path.abspath(os.path.expanduser(target))
        if not os.path.isfile(self.target):
            raise FileNotFoundError(self.target)
        size = os.path.getsize(self.target)
        if size > _MAX_TARGET_BYTES:
            raise ValueError(f"target is {size // (1 << 20)} MB; refusing to load more than {_MAX_TARGET_BYTES >> 20} MB into memory")
        with open(self.target, "rb") as fh:
            self.data = fh.read()
        self.ws = Workspace(self.target)
        cached = self.ws.read_json("target.json")
        self.info: BinaryInfo = parse_binary(self.target, self.data)
        if not cached:
            self.ws.write_json("target.json", {"path": self.target, "size": size, "hashes": self.info.hashes,
                                               "format": self.info.format, "arch": self.info.arch, "first_seen": time.time()})
        self.backend_pref = backend or "auto"
        self._backend: Optional[Backend] = None
        self.notes: List[str] = []

    # -- backend + snapshot ---------------------------------------------------
    def backend(self, *, need_decompiler: bool = False) -> Backend:
        if self._backend is not None and (not need_decompiler or self._backend.has_decompiler):
            return self._backend
        be, notes = select_backend(self.backend_pref, self.ws, self.info, self.data, need_decompiler=need_decompiler)
        if need_decompiler and not be.has_decompiler:
            be, notes2 = select_backend(self.backend_pref, self.ws, self.info, self.data)
            notes += notes2
        self.notes.extend(notes)
        self._backend = be
        return be

    def snapshot(self, force: bool = False) -> dict:
        be = self.backend()
        snap = self.ws.analysis
        if snap and not force and snap.get("backend") in (be.name,):
            return snap
        if snap and not force:
            # A weaker backend produced the cache; a stronger one is now available → upgrade.
            rank = {"ghidra": 4, "radare2": 3, "rizin": 3, "binutils": 2, "python": 1}
            if rank.get(snap.get("backend", ""), 0) >= rank.get(be.name, 0):
                return snap
        fresh = be.export()
        self.ws.save_analysis(be.name, fresh)
        if force:
            self.ws.invalidate_function_cache()
        return self.ws.analysis or fresh

    # -- helpers ---------------------------------------------------------------
    def _name(self, f: dict) -> str:
        return self.ws.display_name(int(f.get("addr", 0)), f.get("name", "?"))

    def _header(self, action: str, extra: str = "") -> str:
        be = self._backend.name if self._backend else "-"
        h = f"# reverse_engineer · {action} · {os.path.basename(self.target)} · backend={be}"
        if extra:
            h += f" · {extra}"
        return h

    def _footer(self) -> str:
        return ("\n".join(f"note: {n}" for n in self.notes) + "\n") if self.notes else ""

    # -- actions ---------------------------------------------------------------
    def overview(self) -> str:
        i = self.info
        lines = [self._header("overview"), ""]
        lines.append(f"file:    {self.target} ({i.size:,} bytes)")
        lines.append(f"sha256:  {i.hashes.get('sha256')}   md5: {i.hashes.get('md5')}")
        lines.append(f"format:  {i.format} {i.subformat} · {i.file_type} · {i.arch} {i.bits}-bit {i.endian} · os={i.os}")
        lines.append(f"entry:   {_fmt_addr(i.entry)}   image base: {_fmt_addr(i.image_base)}"
                     + (f"   interpreter: {i.interpreter}" if i.interpreter else ""))
        sec = []
        sec.append(f"PIE={'yes' if i.pie else 'no' if i.pie is False else '?'}")
        sec.append(f"NX={'yes' if i.nx else 'no' if i.nx is False else '?'}")
        if i.relro is not None:
            sec.append(f"RELRO={i.relro}")
        sec.append(f"canary={'yes' if i.canary else 'no' if i.canary is False else '?'}")
        sec.append(f"stripped={'yes' if i.stripped else 'no' if i.stripped is False else '?'}")
        sec.append(f"static={'yes' if i.static else 'no' if i.static is False else '?'}")
        lines.append("hardening: " + "  ".join(sec))
        if i.libraries:
            lines.append("libraries: " + ", ".join(i.libraries[:20]) + (" …" if len(i.libraries) > 20 else ""))
        for n in i.notes:
            lines.append(f"note: {n}")
        for w in i.warnings:
            lines.append(f"warning: {w}")
        if i.members:
            lines.append("slices: " + ", ".join(f"{a} @0x{o:x} ({s} bytes)" for a, o, s in i.members))
        lines.append("")
        # Sections summary
        code = [s for s in i.sections if s.kind == "code"]
        lines.append(f"sections: {len(i.sections)} ({len(code)} code)  segments: {len(i.segments)}")
        for s in i.sections[:40]:
            if not s.name:
                continue
            ent = f" ent={s.entropy:.2f}" if s.size else ""
            flag = " ⚠packed?" if s.entropy >= 7.2 and s.kind == "code" and s.size > 4096 else ""
            lines.append(f"  {s.name:<22} {_fmt_addr(s.vaddr):>12} size={max(s.vsize, s.size):<8} {s.flags} {s.kind:<6}{ent}{flag}")
        if len(i.sections) > 40:
            lines.append(f"  … {len(i.sections) - 40} more (action=sections)")
        lines.append("")
        lines.append(f"symbols: {len(i.symbols)}   imports: {len(i.imports)}   exports: {len(i.exports)}")
        # Interesting imports
        interesting = [imp.name for imp in i.imports if re.search(
            r"(?i)^(?:_?(?:system|popen|exec[lv]p?e?|fork|ptrace|mprotect|mmap|dlopen|dlsym|socket|connect|bind|listen|accept|"
            r"recv|send|getaddrinfo|inet_|CreateProcess|WinExec|ShellExecute|VirtualAlloc|VirtualProtect|WriteProcessMemory|"
            r"CreateRemoteThread|LoadLibrary|GetProcAddress|RegSetValue|CryptEncrypt|InternetOpen|URLDownload|WSAStartup|"
            r"strcpy|strcat|sprintf|gets|scanf|memcpy|IsDebuggerPresent|NtQueryInformationProcess|OpenProcess|"
            r"SetWindowsHook|GetAsyncKeyState|EncryptFile|CreateService|StartService))", imp.name)]
        if interesting:
            lines.append("notable imports: " + ", ".join(sorted(set(interesting))[:40]))
        # Strings highlights
        try:
            snap = self.ws.analysis
            strings = (snap or {}).get("strings") if snap else None
            if not strings:
                from .formats import extract_strings
                strings = [{"value": t, "tags": classify_string(t), "addr": None} for _, _, t in extract_strings(self.data, 6, limit=20000)]
            tagged = [s for s in strings if s.get("tags")]
            if tagged:
                lines.append(f"notable strings ({len(tagged)} tagged; action=strings for all):")
                for s in tagged[:15]:
                    lines.append(f"  [{','.join(s['tags'])}] {s['value'][:100]}")
        except Exception:
            pass
        lines.append("")
        wsum = self.ws.summary()
        lines.append(f"workspace: {wsum['workspace']}  cached: backend={wsum['backend'] or '-'} functions={wsum['functions']} "
                     f"strings={wsum['strings']} decompiled={wsum['decompiled_cached']} renames={wsum['renames']}")
        tools = detect_tools()
        avail = [k for k in ("ghidra", "r2", "rizin", "objdump", "capstone") if tools.get(k)]
        lines.append("backends available: " + (", ".join(avail) or "python parser only") + "   (action=capabilities for install hints)")
        lines.append("next: action=functions (list), action=decompile function=main (or the entry point), action=strings query=<regex>")
        return "\n".join(lines) + "\n" + self._footer()

    def functions(self, query: str, limit: int, offset: int, sort: str = "addr") -> str:
        snap = self.snapshot()
        funcs = list(snap.get("functions", []) or [])
        if query:
            rx = re.compile(query, re.IGNORECASE)
            funcs = [f for f in funcs if rx.search(self._name(f)) or rx.search(f.get("name", ""))]
        if sort == "size":
            funcs.sort(key=lambda f: -(f.get("size") or 0))
        elif sort == "callers":
            funcs.sort(key=lambda f: -len(f.get("callers") or []))
        total = len(funcs)
        page = funcs[offset: offset + limit]
        lines = [self._header("functions", f"{total} total, showing {offset}–{offset + len(page)}"), ""]
        lines.append(f"{'address':>12}  {'size':>7}  {'in':>3} {'out':>3}  name / signature")
        for f in page:
            name = self._name(f)
            sig = f.get("signature") or ""
            if sig and sig != f"{f.get('name')}()" and not sig.startswith(name):
                sig = f"  {sig}"
            else:
                sig = ""
            tag = " (thunk)" if f.get("thunk") else " (ext)" if f.get("external") else ""
            lines.append(f"{_fmt_addr(f.get('addr')):>12}  {f.get('size', 0) or 0:>7}  {len(f.get('callers') or []):>3} {len(f.get('callees') or []):>3}  {name}{tag}{sig}")
        if offset + len(page) < total:
            lines.append(f"… more: offset={offset + limit}")
        lines.append("")
        lines.append("hint: action=decompile function=<name|0xaddr>; action=xrefs function=<name>; sort=size|callers; query=<regex>")
        return "\n".join(lines) + "\n" + self._footer()

    def decompile(self, spec: str) -> str:
        snap = self.snapshot()
        if not spec:
            spec = self._default_entry_name(snap)
        f = _resolve_function(snap, self.ws, spec)
        if f is None:
            return self._not_found(spec, snap)
        addr = int(f["addr"])
        be = self.backend(need_decompiler=True)
        cached = self.ws.cached_decomp(addr, be.name)
        hdr = self._header("decompile", f"{self._name(f)} @ {_fmt_addr(addr)}")
        if cached:
            return f"{hdr} · cached\n{self._annotation_block(addr)}{cached}\n{self._callgraph_line(f)}\n{self._footer()}"
        if not be.has_decompiler:
            try:
                dis = be.disasm(addr, 200, True)
            except (BackendError, NotImplementedError) as exc:
                dis = f"(no disassembler: {exc})"
            return (f"{hdr} · NO DECOMPILER on this machine — showing disassembly instead\n"
                    f"{self._annotation_block(addr)}{dis}\n\n"
                    "install Ghidra (best), or radare2 (+ r2ghidra), or rizin (+ rz-ghidra) for real decompilation; "
                    "action=capabilities lists what was detected.\n" + self._callgraph_line(f) + "\n" + self._footer())
        try:
            text = be.decompile(addr, self._name(f))
        except BackendError as exc:
            return f"{hdr}\nerror: {exc}\n{self._footer()}"
        self.ws.save_decomp(addr, be.name, text)
        return f"{hdr}\n{self._annotation_block(addr)}{text}\n{self._callgraph_line(f)}\n{self._footer()}"

    def disassemble(self, spec: str, count: int) -> str:
        snap = self.snapshot()
        if not spec:
            spec = self._default_entry_name(snap)
        f = _resolve_function(snap, self.ws, spec)
        addr = parse_address(spec) if f is None else int(f["addr"])
        if addr is None:
            return self._not_found(spec, snap)
        whole = f is not None and f.get("addr") == addr and bool(f.get("size")) and count <= 0
        be = self.backend()
        key = addr if whole else None
        cached = self.ws.cached_disasm(addr, be.name) if whole else None
        hdr = self._header("disassemble", f"{self._name(f) if f else _fmt_addr(addr)} @ {_fmt_addr(addr)}" + ("" if whole else f" · {count} instructions"))
        if cached:
            return f"{hdr} · cached\n{self._annotation_block(addr)}{cached}\n{self._footer()}"
        try:
            text = be.disasm(addr, count if count > 0 else 200, whole or count <= 0)
        except (BackendError, NotImplementedError) as exc:
            return f"{hdr}\nerror: {exc}\n{self._footer()}"
        if whole:
            self.ws.save_disasm(addr, be.name, text)
        return f"{hdr}\n{self._annotation_block(addr)}{text}\n{self._footer()}"

    def xrefs(self, spec: str, limit: int) -> str:
        snap = self.snapshot()
        f = _resolve_function(snap, self.ws, spec)
        addr = int(f["addr"]) if f else parse_address(spec)
        if addr is None:
            # maybe a string
            for s in snap.get("strings", []) or []:
                if spec and spec in (s.get("value") or ""):
                    addr = s.get("addr")
                    break
        if addr is None:
            return self._not_found(spec, snap)
        be = self.backend()
        try:
            res = be.xrefs(addr)
        except (BackendError, NotImplementedError) as exc:
            return f"{self._header('xrefs')}\nerror: {exc}\n{self._footer()}"
        name = res.get("name") or (self._name(f) if f else "")
        lines = [self._header("xrefs", f"{name or '?'} @ {_fmt_addr(addr)}"), ""]
        to = res.get("to", []) or []
        frm = res.get("from", []) or []
        lines.append(f"references TO {_fmt_addr(addr)} ({len(to)}):")
        for r in to[:limit]:
            fn = r.get("func") or "?"
            lines.append(f"  {_fmt_addr(r.get('from')):>12}  in {fn:<32} {r.get('type', '')} {r.get('opcode', '')}".rstrip())
        if len(to) > limit:
            lines.append(f"  … {len(to) - limit} more")
        if frm:
            lines.append("")
            lines.append(f"references FROM {name or _fmt_addr(addr)} ({len(frm)}):")
            for r in frm[:limit]:
                lines.append(f"  {_fmt_addr(r.get('from')):>12} → {_fmt_addr(r.get('to')):>12}  {r.get('target') or ''} {r.get('type', '')}".rstrip())
            if len(frm) > limit:
                lines.append(f"  … {len(frm) - limit} more")
        if res.get("note"):
            lines.append(f"note: {res['note']}")
        return "\n".join(lines) + "\n" + self._footer()

    def callgraph(self, spec: str, depth: int, limit: int) -> str:
        snap = self.snapshot()
        f = _resolve_function(snap, self.ws, spec)
        if f is None:
            return self._not_found(spec, snap)
        by_name = {fn.get("name"): fn for fn in snap.get("functions", []) or []}
        lines = [self._header("callgraph", f"{self._name(f)} @ {_fmt_addr(f['addr'])} · depth={depth}"), ""]

        def walk(fn: dict, key: str, prefix: str, d: int, seen: set, out: List[str]) -> None:
            if d > depth or len(out) > limit:
                return
            for nm in (fn.get(key) or [])[:40]:
                child = by_name.get(nm)
                disp = self._name(child) if child else nm
                mark = " ↺" if nm in seen else ""
                out.append(f"{prefix}{disp}{(' @ ' + _fmt_addr(child['addr'])) if child else ''}{mark}")
                if child and nm not in seen:
                    walk(child, key, prefix + "  ", d + 1, seen | {nm}, out)

        callers: List[str] = []
        walk(f, "callers", "  ", 1, {f.get("name")}, callers)
        callees: List[str] = []
        walk(f, "callees", "  ", 1, {f.get("name")}, callees)
        lines.append(f"callers ({len(f.get('callers') or [])} direct):")
        lines.extend(callers or ["  (none — entry point, exported, or reached indirectly)"])
        lines.append("")
        lines.append(f"callees ({len(f.get('callees') or [])} direct):")
        lines.extend(callees or ["  (none / leaf)"])
        return "\n".join(lines) + "\n" + self._footer()

    def strings(self, query: str, limit: int, offset: int, min_len: int, with_refs: bool) -> str:
        snap = self.snapshot()
        strings = list(snap.get("strings", []) or [])
        if not strings:
            from .formats import extract_strings
            strings = [{"addr": self.info.offset_to_vaddr(o), "offset": o, "value": t, "enc": e, "refs": [], "tags": classify_string(t),
                        "section": (self.info.section_for_offset(o).name if self.info.section_for_offset(o) else "")}
                       for o, e, t in extract_strings(self.data, min_len, limit=50000)]
        if min_len > 4:
            strings = [s for s in strings if len(s.get("value", "")) >= min_len]
        if query:
            if query.lower() in ("tagged", "interesting", "notable"):
                strings = [s for s in strings if s.get("tags")]
            elif query.startswith("tag:"):
                want = query[4:].strip().lower()
                strings = [s for s in strings if want in [t.lower() for t in s.get("tags", [])]]
            else:
                rx = re.compile(query, re.IGNORECASE)
                strings = [s for s in strings if rx.search(s.get("value", ""))]
        if with_refs:
            strings = [s for s in strings if s.get("refs")]
        total = len(strings)
        page = strings[offset: offset + limit]
        lines = [self._header("strings", f"{total} match, showing {offset}–{offset + len(page)}"), ""]
        for s in page:
            tags = f" [{','.join(s['tags'])}]" if s.get("tags") else ""
            loc = _fmt_addr(s.get("addr")) if s.get("addr") is not None else f"off:0x{s.get('offset', 0):x}"
            refs = ""
            if s.get("refs"):
                names = []
                for r in s["refs"][:6]:
                    fn = r.get("func") or _fmt_addr(r.get("from"))
                    if fn not in names:
                        names.append(fn)
                refs = f"  ← {', '.join(names)}" + (" …" if len(s["refs"]) > 6 else "")
            val = s.get("value", "").replace("\n", "\\n")
            lines.append(f"{loc:>12}{tags} {val[:160]}{refs}")
        if offset + len(page) < total:
            lines.append(f"… more: offset={offset + limit}")
        lines.append("")
        lines.append("hint: query=<regex> | query=tagged | query=tag:url; with_refs=true shows only strings referenced from code; "
                     "action=xrefs function=<0xaddr of string> lists the code that uses it")
        return "\n".join(lines) + "\n" + self._footer()

    def imports(self, query: str, limit: int, offset: int) -> str:
        snap = self.ws.analysis or {}
        items = snap.get("imports") or [{"name": i.name, "library": i.library, "addr": i.addr} for i in self.info.imports]
        if query:
            rx = re.compile(query, re.IGNORECASE)
            items = [i for i in items if rx.search(i.get("name", "")) or rx.search(i.get("library", "") or "")]
        items = sorted(items, key=lambda i: ((i.get("library") or ""), i.get("name", "")))
        total = len(items)
        page = items[offset: offset + limit]
        lines = [self._header("imports", f"{total} total, showing {offset}–{offset + len(page)}"), ""]
        bylib: Dict[str, List[str]] = {}
        for i in page:
            bylib.setdefault(i.get("library") or "(unresolved)", []).append(i.get("name", "?") + (f" @{_fmt_addr(i['addr'])}" if i.get("addr") else ""))
        for lib, names in bylib.items():
            lines.append(f"{lib}: " + ", ".join(names))
        if offset + len(page) < total:
            lines.append(f"… more: offset={offset + limit}")
        return "\n".join(lines) + "\n" + self._footer()

    def exports(self, query: str, limit: int, offset: int) -> str:
        snap = self.ws.analysis or {}
        items = snap.get("exports") or [{"name": e.name, "addr": e.addr} for e in self.info.exports]
        if query:
            rx = re.compile(query, re.IGNORECASE)
            items = [e for e in items if rx.search(e.get("name", ""))]
        total = len(items)
        page = items[offset: offset + limit]
        lines = [self._header("exports", f"{total} total, showing {offset}–{offset + len(page)}"), ""]
        for e in page:
            lines.append(f"{_fmt_addr(e.get('addr')):>12}  {e.get('name')}")
        if offset + len(page) < total:
            lines.append(f"… more: offset={offset + limit}")
        return "\n".join(lines) + "\n" + self._footer()

    def symbols(self, query: str, limit: int, offset: int) -> str:
        items = [{"name": s.name, "addr": s.addr, "size": s.size, "type": s.kind, "bind": s.bind, "section": s.section, "defined": s.defined}
                 for s in self.info.symbols]
        snap = self.ws.analysis or {}
        if not items and snap.get("symbols"):
            items = snap["symbols"]
        if query:
            rx = re.compile(query, re.IGNORECASE)
            items = [s for s in items if rx.search(s.get("name", ""))]
        items.sort(key=lambda s: (s.get("addr") or 0))
        total = len(items)
        page = items[offset: offset + limit]
        lines = [self._header("symbols", f"{total} total, showing {offset}–{offset + len(page)}"), ""]
        for s in page:
            lines.append(f"{_fmt_addr(s.get('addr')):>12}  {s.get('size', 0) or 0:>6}  {s.get('type', ''):<7} {s.get('bind', ''):<6} "
                         f"{s.get('section', ''):<16} {s.get('name')}{'' if s.get('defined', True) else '  (undefined)'}")
        if offset + len(page) < total:
            lines.append(f"… more: offset={offset + limit}")
        return "\n".join(lines) + "\n" + self._footer()

    def sections(self) -> str:
        i = self.info
        lines = [self._header("sections"), ""]
        lines.append(f"{'name':<24}{'vaddr':>14}{'offset':>12}{'size':>10}{'vsize':>10}  perms kind    entropy")
        for s in i.sections:
            if not s.name:
                continue
            lines.append(f"{s.name:<24}{_fmt_addr(s.vaddr):>14}{'0x%x' % s.offset:>12}{s.size:>10}{s.vsize:>10}  {s.flags}   {s.kind:<7} {s.entropy:.2f}")
        if i.segments:
            lines.append("")
            lines.append("segments / program headers:")
            for s in i.segments:
                lines.append(f"  {s.name:<16}{_fmt_addr(s.vaddr):>14}{'0x%x' % s.offset:>12}{s.size:>10}{s.vsize:>10}  {s.flags}")
        snap = self.ws.analysis or {}
        if snap.get("blocks") and snap.get("backend") == "ghidra":
            lines.append("")
            lines.append("ghidra memory blocks:")
            for b in snap["blocks"]:
                lines.append(f"  {b.get('name', ''):<24}{_fmt_addr(b.get('start')):>14}{b.get('size', 0):>10}  {b.get('perms', '')}")
        return "\n".join(lines) + "\n" + self._footer()

    def search(self, query: str, limit: int) -> str:
        if not query:
            return "search needs query=<hex bytes like 48 8b ?? c3 | text | regex>"
        be = self.backend()
        try:
            hits = be.search(query, limit)
        except (BackendError, NotImplementedError) as exc:
            hits = PythonBackend(self.ws, self.info, self.data).search(query, limit)
            self.notes.append(f"{be.name} search failed ({exc}); used python byte search")
        lines = [self._header("search", f"{len(hits)} hit(s) for {query!r}"), ""]
        snap = self.ws.analysis or {}
        funcs = snap.get("functions", []) or []
        for h in hits:
            fn = h.get("func") or ""
            if not fn and h.get("addr") is not None:
                for f in funcs:
                    if f.get("size") and f["addr"] <= h["addr"] < f["addr"] + f["size"]:
                        fn = self._name(f)
                        break
            lines.append(f"{_fmt_addr(h.get('addr')):>12}  off=0x{(h.get('offset') or 0):x}  {h.get('section', ''):<14} {fn:<28} {h.get('preview', '')[:48]}")
        return "\n".join(lines) + "\n" + self._footer()

    def read(self, spec: str, length: int) -> str:
        addr = parse_address(spec)
        if addr is None:
            snap = self.ws.analysis or {}
            f = _resolve_function(snap, self.ws, spec)
            if f:
                addr = int(f["addr"])
        if addr is None:
            return "read needs address=0x... (virtual address) or offset:0x... (file offset)"
        if spec.lower().startswith("off"):
            off = parse_address(spec.split(":", 1)[1] if ":" in spec else spec[3:])
            base = self.info.offset_to_vaddr(off) if off is not None else None
        else:
            off = self.info.vaddr_to_offset(addr)
            base = addr
        if off is None:
            return f"{_fmt_addr(addr)} is not backed by file bytes (bss/unmapped); try offset:0x..."
        length = max(16, min(length or 256, 65536))
        chunk = self.data[off: off + length]
        sec = self.info.section_for_offset(off)
        lines = [self._header("read", f"{_fmt_addr(base)} (file offset 0x{off:x}) · {len(chunk)} bytes · {sec.name if sec else '?'} · entropy={shannon_entropy(chunk):.2f}"), ""]
        lines.append(hexdump(chunk, base or off))
        return "\n".join(lines) + "\n" + self._footer()

    def entropy(self) -> str:
        i = self.info
        lines = [self._header("entropy"), ""]
        lines.append(f"whole file: {shannon_entropy(self.data[:8 << 20]):.3f} bits/byte  (≥7.2 in code/data usually means packed or encrypted)")
        lines.append("")
        for s in i.sections:
            if not s.size or not s.name:
                continue
            bar = "█" * int(s.entropy * 4) + "·" * (32 - int(s.entropy * 4))
            flag = "  ⚠" if s.entropy >= 7.2 and s.kind in ("code", "data", "rodata", "") and s.size > 2048 else ""
            lines.append(f"{s.name:<22} {s.entropy:5.2f} {bar} {s.size:>9}B {s.kind}{flag}")
        # Sliding window over the file for unlabeled blobs
        lines.append("")
        win = max(4096, len(self.data) // 64)
        lines.append(f"sliding window ({win} bytes):")
        hot = []
        for off in range(0, len(self.data), win):
            e = shannon_entropy(self.data[off: off + win])
            if e >= 7.4:
                hot.append(off)
        if hot:
            lines.append("  high-entropy windows at: " + ", ".join(f"0x{o:x}" for o in hot[:40]) + (" …" if len(hot) > 40 else ""))
        else:
            lines.append("  no window ≥ 7.4 — nothing looks packed/encrypted")
        return "\n".join(lines) + "\n" + self._footer()

    def security(self) -> str:
        i = self.info
        lines = [self._header("security"), ""]
        rows = [
            ("PIE / ASLR", i.pie, "randomized base; return-oriented attacks need a leak"),
            ("NX / DEP", i.nx, "stack/heap not executable"),
            ("RELRO", i.relro, "GOT protection (full = read-only after relocation)"),
            ("stack canary", i.canary, "__stack_chk_fail present"),
            ("stripped", i.stripped, "no local symbol table"),
            ("static", i.static, "no dynamic dependencies"),
        ]
        for label, val, desc in rows:
            v = val if isinstance(val, str) else ("yes" if val else "no" if val is False else "unknown")
            lines.append(f"{label:<14} {v:<9} {desc}")
        for n in i.notes:
            lines.append(f"note: {n}")
        tools = detect_tools()
        if tools.get("checksec"):
            from .backends import _run
            rc, out, _ = _run([tools["checksec"], f"--file={self.target}"], timeout=60)
            if out.strip():
                lines.append("")
                lines.append("checksec:")
                lines.extend("  " + ln for ln in out.strip().splitlines()[:20])
        risky = [imp.name for imp in i.imports if re.match(r"(?i)^_?(gets|strcpy|strcat|sprintf|vsprintf|scanf|sscanf|memcpy|strncpy|alloca|system|popen)$", imp.name)]
        if risky:
            lines.append("")
            lines.append("risky libc imports: " + ", ".join(sorted(set(risky))))
        return "\n".join(lines) + "\n" + self._footer()

    def hashes(self) -> str:
        i = self.info
        lines = [self._header("hashes"), ""]
        for k, v in i.hashes.items():
            lines.append(f"{k:<8}{v}")
        if i.sections:
            import hashlib
            lines.append("")
            lines.append("per-section sha256 (first 16 hex):")
            for s in i.sections:
                if s.size and s.name:
                    lines.append(f"  {s.name:<22} {hashlib.sha256(self.data[s.offset:s.offset + s.size]).hexdigest()[:16]}")
        return "\n".join(lines) + "\n" + self._footer()

    def rename(self, spec: str, new_name: str) -> str:
        if not new_name or not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.$@]{0,120}", new_name):
            return "rename needs new_name=<identifier> (letters, digits, _ . $ @)"
        snap = self.snapshot()
        f = _resolve_function(snap, self.ws, spec)
        addr = int(f["addr"]) if f else parse_address(spec)
        if addr is None:
            return self._not_found(spec, snap)
        old = self._name(f) if f else _fmt_addr(addr)
        self.ws.rename(addr, new_name, old)
        be = self.backend()
        try:
            msg = be.rename(addr, new_name)
        except BackendError as exc:
            msg = f"backend rename failed ({exc}); kept in workspace annotations"
        return f"{self._header('rename')}\n{old} @ {_fmt_addr(addr)} → {new_name}\n{msg}\n{self._footer()}"

    def comment(self, spec: str, text: str) -> str:
        if not text:
            return "comment needs text=<note>"
        snap = self.snapshot()
        f = _resolve_function(snap, self.ws, spec)
        addr = int(f["addr"]) if f else parse_address(spec)
        if addr is None:
            return self._not_found(spec, snap)
        self.ws.comment(addr, text)
        be = self.backend()
        try:
            msg = be.comment(addr, text)
        except BackendError as exc:
            msg = f"backend comment failed ({exc}); kept in workspace annotations"
        return f"{self._header('comment')}\n{self._name(f) if f else _fmt_addr(addr)} @ {_fmt_addr(addr)}: {text}\n{msg}\n{self._footer()}"

    def note(self, text: str) -> str:
        if not text:
            return "note needs text=<analysis note>"
        self.ws.append_note(text)
        return f"{self._header('note')}\nsaved to {self.ws.dir / 'notes.md'}\n"

    def notes_report(self) -> str:
        ann = self.ws.annotations
        lines = [self._header("notes"), ""]
        if ann["renames"]:
            lines.append("renames:")
            for k, r in ann["renames"].items():
                lines.append(f"  0x{k}: {r.get('old', '?')} → {r.get('name')}")
        if ann["comments"]:
            lines.append("comments:")
            for k, cs in ann["comments"].items():
                for c in cs:
                    lines.append(f"  0x{k}: {c.get('text')}")
        n = self.ws.notes()
        if n.strip():
            lines.append("")
            lines.append("notes.md:")
            lines.append(n.strip())
        if len(lines) == 2:
            lines.append("(no annotations yet — action=rename/comment/note)")
        return "\n".join(lines) + "\n"

    def analyze(self) -> str:
        be = self.backend()
        t0 = time.time()
        if isinstance(be, GhidraBackend):
            # Force a re-export (project kept; export is cheap once analyzed).
            self.ws.write_json("analysis.json", {})
        snap = self.snapshot(force=True)
        return (f"{self._header('analyze')}\nre-analyzed with {be.name} in {time.time() - t0:.1f}s: "
                f"{len(snap.get('functions', []))} functions, {len(snap.get('strings', []))} strings, "
                f"{len(snap.get('imports', []))} imports\n{self._footer()}")

    def workspace(self) -> str:
        s = self.ws.summary()
        lines = [self._header("workspace"), ""]
        for k, v in s.items():
            lines.append(f"{k:<20} {v}")
        return "\n".join(lines) + "\n"

    # -- misc helpers ---------------------------------------------------------
    def _default_entry_name(self, snap: dict) -> str:
        for cand in ("main", "_main", "sym.main", "WinMain", "wmain", "DllMain", "entry", "_start", "entry0", "start"):
            if any(f.get("name") == cand for f in snap.get("functions", []) or []):
                return cand
        eps = snap.get("entry_points") or ([self.info.entry] if self.info.entry else [])
        return _fmt_addr(eps[0]) if eps else ""

    def _not_found(self, spec: str, snap: dict) -> str:
        funcs = snap.get("functions", []) or []
        sugg = []
        if spec:
            low = spec.lower()
            sugg = [self._name(f) for f in funcs if low in f.get("name", "").lower()][:10]
        msg = f"function/address {spec!r} not found among {len(funcs)} known functions."
        if sugg:
            msg += " Did you mean: " + ", ".join(sugg)
        msg += "\nUse action=functions query=<regex>, or pass a hex address (0x...)."
        return msg

    def _annotation_block(self, addr: int) -> str:
        cs = self.ws.comments_for(addr)
        r = self.ws.annotations["renames"].get(f"{addr:x}")
        out = ""
        if r:
            out += f"// renamed: {r.get('old', '?')} → {r.get('name')}\n"
        for c in cs:
            out += f"// note: {c}\n"
        return out

    def _callgraph_line(self, f: dict) -> str:
        callers = f.get("callers") or []
        callees = f.get("callees") or []
        return (f"callers: {', '.join(callers[:12]) or '-'}{' …' if len(callers) > 12 else ''}\n"
                f"callees: {', '.join(callees[:16]) or '-'}{' …' if len(callees) > 16 else ''}")


# ---------------------------------------------------------------------------
# Entry point used by the tool
# ---------------------------------------------------------------------------

def run_action(target: str, action: str, **kw: Any) -> str:
    action = (action or "overview").strip().lower()
    if action == "capabilities":
        return capabilities_report()
    if action not in ACTIONS:
        return f"unknown action {action!r}. Valid: {', '.join(ACTIONS)}"
    if not target:
        return "target is required (path to the binary/artifact)."
    try:
        eng = REEngine(target, backend=str(kw.get("backend") or "auto"))
    except FileNotFoundError:
        return f"target not found: {target}"
    except (ValueError, OSError) as exc:
        return f"cannot open target: {exc}"

    spec = str(kw.get("function") or kw.get("address") or "").strip()
    query = str(kw.get("query") or "").strip()
    limit = max(1, min(int(kw.get("limit") or 200), 5000))
    offset = max(0, int(kw.get("offset") or 0))
    length = int(kw.get("length") or 0)

    try:
        if action == "overview":
            return eng.overview()
        if action == "functions":
            return eng.functions(query, limit, offset, str(kw.get("sort") or "addr"))
        if action == "decompile":
            return eng.decompile(spec)
        if action == "disassemble":
            return eng.disassemble(spec, length)
        if action == "xrefs":
            return eng.xrefs(spec or query, limit)
        if action == "callgraph":
            return eng.callgraph(spec, max(1, min(int(kw.get("depth") or 2), 5)), limit)
        if action == "strings":
            return eng.strings(query, limit, offset, max(3, int(kw.get("min_length") or 4)),
                               bool(kw.get("with_refs")))
        if action == "imports":
            return eng.imports(query, limit, offset)
        if action == "exports":
            return eng.exports(query, limit, offset)
        if action == "symbols":
            return eng.symbols(query, limit, offset)
        if action == "sections":
            return eng.sections()
        if action == "search":
            return eng.search(query, limit)
        if action == "read":
            return eng.read(spec, length)
        if action == "entropy":
            return eng.entropy()
        if action == "security":
            return eng.security()
        if action == "hashes":
            return eng.hashes()
        if action == "rename":
            return eng.rename(spec, str(kw.get("new_name") or "").strip())
        if action == "comment":
            return eng.comment(spec, str(kw.get("text") or "").strip())
        if action == "note":
            return eng.note(str(kw.get("text") or "").strip())
        if action == "notes":
            return eng.notes_report()
        if action == "analyze":
            return eng.analyze()
        if action == "workspace":
            return eng.workspace()
    except BackendError as exc:
        return f"# reverse_engineer · {action}\nbackend error: {exc}\n(action=capabilities shows what is installed; backend=python always works for structural queries)"
    except re.error as exc:
        return f"invalid regex in query: {exc}"
    return f"action {action!r} is not implemented"
