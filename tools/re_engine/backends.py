"""Backends for the reverse-engineering engine.

Each backend exposes the same small surface (``export``, ``decompile``,
``disasm``, ``xrefs``, ``search``, ``rename``, ``comment``) on top of whatever
RE software is actually installed. The engine picks the strongest one that
is available and says which one produced each answer.

Priority (strongest first):

1. **Ghidra headless** — full analysis + real decompiler. Uses the bundled
   ``RoboRE.java`` post-script and keeps a persistent project per target so
   only the first call pays for auto-analysis. Found via ``GHIDRA_INSTALL_DIR``
   / ``GHIDRA_HOME``, ``analyzeHeadless`` on PATH, or well-known install dirs
   (``/usr/share/ghidra`` on Kali, ``/opt/ghidra*``, ``~/ghidra*``,
   ``/Applications/ghidra*``).
2. **radare2 / rizin** — analysis, disassembly, xrefs, strings, pseudo-C
   decompilation (``pdc``) or real Ghidra decompilation through the
   ``r2ghidra`` / ``rz-ghidra`` plugin (``pdg``) when installed.
3. **binutils** (``objdump``/``nm``/``readelf``) + the pure-Python parsers —
   disassembly per function, a call graph and string references mined from
   the listing. No decompiler.
4. **python** — parser-only fallback that always works (headers, sections,
   symbols, imports/exports, strings, entropy, byte search, hexdump).

None of these executes the target.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .formats import BinaryInfo, extract_strings, classify_string
from .workspace import Workspace, parse_address

logger = logging.getLogger(__name__)

_SCRIPT_DIR = Path(__file__).resolve().parents[2] / "robo_runtime" / "resources" / "re" / "ghidra"


def _cfg() -> dict:
    try:
        from robo_cli.config import load_config_readonly
        cfg = load_config_readonly() or {}
        block = cfg.get("reverse_engineering")
        return dict(block) if isinstance(block, dict) else {}
    except Exception:
        return {}


def _run(cmd: List[str], *, timeout: float, cwd: Optional[str] = None,
         env: Optional[dict] = None) -> Tuple[int, str, str]:
    """Run *cmd* (argv list, never a shell) and return (rc, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            timeout=timeout, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return 124, out, err + f"\n[timed out after {timeout:.0f}s]"
    except FileNotFoundError as exc:
        return 127, "", str(exc)
    return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")


# ---------------------------------------------------------------------------
# Tool detection
# ---------------------------------------------------------------------------

def find_ghidra_headless() -> Optional[str]:
    cfg = _cfg()
    candidates: List[str] = []
    for key in ("ghidra_path", "ghidra_headless"):
        v = cfg.get(key)
        if isinstance(v, str) and v.strip():
            candidates.append(os.path.expanduser(v.strip()))
    for var in ("GHIDRA_HEADLESS", "GHIDRA_INSTALL_DIR", "GHIDRA_HOME", "GHIDRA_ROOT"):
        v = os.environ.get(var)
        if v:
            candidates.append(os.path.expanduser(v))
    for name in ("analyzeHeadless", "ghidra-analyzeHeadless", "ghidra_analyzeHeadless", "analyzeHeadless.bat"):
        p = shutil.which(name)
        if p:
            candidates.append(p)
    patterns = [
        "/usr/share/ghidra", "/usr/lib/ghidra", "/usr/local/ghidra*", "/opt/ghidra*", "/opt/homebrew/opt/ghidra/libexec",
        "/usr/local/opt/ghidra/libexec", "/snap/ghidra/current/ghidra*", "/Applications/ghidra*",
        os.path.expanduser("~/ghidra*"), os.path.expanduser("~/tools/ghidra*"), os.path.expanduser("~/opt/ghidra*"),
        "C:/ghidra*", "C:/Program Files/ghidra*", "C:/tools/ghidra*",
    ]
    for pat in patterns:
        candidates.extend(sorted(glob.glob(pat), reverse=True))
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        p = Path(c)
        if p.is_file() and os.access(p, os.X_OK) and p.name.lower().startswith("analyzeheadless"):
            return str(p)
        if p.is_dir():
            for rel in ("support/analyzeHeadless", "support/analyzeHeadless.bat", "analyzeHeadless"):
                q = p / rel
                if q.is_file():
                    return str(q)
            # Homebrew style: <dir>/ghidra_*/support/analyzeHeadless
            for q in sorted(p.glob("ghidra_*/support/analyzeHeadless"), reverse=True):
                return str(q)
    return None


def detect_tools() -> Dict[str, Any]:
    tools: Dict[str, Any] = {}
    tools["ghidra"] = find_ghidra_headless()
    for name in ("r2", "radare2", "rizin", "objdump", "llvm-objdump", "nm", "readelf", "strings", "checksec",
                 "retdec-decompiler", "retdec-decompiler.py", "file", "ldd", "strace", "ltrace", "gdb", "upx"):
        tools[name] = shutil.which(name)
    if not tools.get("r2") and tools.get("radare2"):
        tools["r2"] = tools["radare2"]
    try:
        import capstone  # noqa: F401
        tools["capstone"] = getattr(capstone, "__version__", "yes")
    except Exception:
        tools["capstone"] = None
    tools["java"] = shutil.which("java")
    return tools


_INSTALL_HINTS = {
    "ghidra": "Ghidra: `sudo apt install ghidra` (Kali/Debian), `brew install --cask ghidra` (macOS), or download from https://ghidra-sre.org and set GHIDRA_INSTALL_DIR",
    "r2": "radare2: `sudo apt install radare2` or https://radare.org; add `r2pm -ci r2ghidra` for a real decompiler",
    "rizin": "rizin: `sudo apt install rizin` or https://rizin.re; `rz-pm install rz-ghidra` adds a decompiler",
    "objdump": "binutils: `sudo apt install binutils`",
    "capstone": "capstone (optional, in-process disassembly): `pip install capstone`",
    "checksec": "checksec: `sudo apt install checksec`",
}


def capabilities_report() -> str:
    tools = detect_tools()
    lines = ["# reverse_engineer · capabilities", ""]
    order = [
        ("ghidra", "Ghidra headless (analysis + decompiler + persistent project)"),
        ("r2", "radare2 (analysis, disasm, xrefs, pseudo-C / r2ghidra decompiler)"),
        ("rizin", "rizin (analysis, disasm, xrefs, pseudo-C / rz-ghidra decompiler)"),
        ("objdump", "binutils objdump/nm/readelf (disassembly, symbols)"),
        ("capstone", "capstone (in-process disassembly)"),
        ("checksec", "checksec (hardening report)"),
        ("retdec-decompiler", "RetDec decompiler"),
        ("strace", "strace (dynamic, opt-in only)"),
        ("upx", "upx (unpacking)"),
    ]
    for key, desc in order:
        v = tools.get(key)
        mark = "✓" if v else "✗"
        lines.append(f"{mark} {desc}: {v if v else 'not installed'}")
        if not v and key in _INSTALL_HINTS:
            lines.append(f"    → {_INSTALL_HINTS[key]}")
    lines.append("✓ pure-Python ELF/PE/Mach-O parser (always available)")
    lines.append("")
    best = "ghidra" if tools.get("ghidra") else "radare2" if tools.get("r2") else "rizin" if tools.get("rizin") else "binutils" if tools.get("objdump") else "python"
    lines.append(f"Preferred backend right now: {best}")
    lines.append("Workspaces: " + str(Path(os.environ.get("ROBO_HOME") or Path.home() / ".robo") / "re"))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------

class BackendError(RuntimeError):
    pass


class Backend:
    name = "base"
    has_decompiler = False

    def __init__(self, ws: Workspace, info: BinaryInfo, data: bytes):
        self.ws = ws
        self.info = info
        self.data = data
        self.target = ws.target

    # Every backend produces the same snapshot shape:
    # {"functions": [{"name","addr","size","signature","callers","callees"}],
    #  "imports": [...], "exports": [...], "symbols": [...],
    #  "strings": [{"addr","value","refs":[{"from","func"}]}], "blocks": [...]}
    def export(self) -> dict:
        raise NotImplementedError

    def decompile(self, addr: int, name: str) -> str:
        raise BackendError(f"{self.name} has no decompiler")

    def disasm(self, addr: int, count: int, whole_function: bool) -> str:
        raise NotImplementedError

    def xrefs(self, addr: int) -> dict:
        raise NotImplementedError

    def search(self, pattern_hex: str, limit: int) -> List[dict]:
        return python_search(self.data, self.info, pattern_hex, limit)

    def rename(self, addr: int, new_name: str) -> str:
        return "recorded in workspace annotations (backend has no persistent database)"

    def comment(self, addr: int, text: str) -> str:
        return "recorded in workspace annotations (backend has no persistent database)"


# ---------------------------------------------------------------------------
# Pure-Python backend (always available)
# ---------------------------------------------------------------------------

def python_search(data: bytes, info: BinaryInfo, pattern: str, limit: int) -> List[dict]:
    """Search raw bytes (hex, `??` wildcards) or a literal/regex string."""
    hits: List[dict] = []
    clean = re.sub(r"[\s,]", "", pattern)
    is_hex = bool(re.fullmatch(r"(?:[0-9a-fA-F?]{2})+", clean)) and len(clean) >= 4
    if is_hex:
        parts = []
        for i in range(0, len(clean), 2):
            pair = clean[i:i + 2]
            parts.append(b"." if "?" in pair else re.escape(bytes([int(pair, 16)])))
        rx = re.compile(b"".join(parts), re.DOTALL)
    else:
        try:
            rx = re.compile(pattern.encode("utf-8"), re.IGNORECASE)
        except re.error:
            rx = re.compile(re.escape(pattern.encode("utf-8")), re.IGNORECASE)
    for m in rx.finditer(data):
        off = m.start()
        sec = info.section_for_offset(off)
        va = info.offset_to_vaddr(off)
        hits.append({
            "offset": off, "addr": va, "section": sec.name if sec else "",
            "preview": data[off:off + 32].hex(),
        })
        if len(hits) >= limit:
            break
    return hits


def _function_symbols(info: BinaryInfo) -> List[dict]:
    funcs = []
    for s in info.symbols:
        if s.defined and (s.kind == "func" or (s.kind == "" and s.section and (s.section.startswith(".text") or "text" in s.section))):
            funcs.append({"name": s.name, "addr": s.addr, "size": s.size, "signature": f"{s.name}()",
                          "callers": [], "callees": [], "section": s.section, "bind": s.bind})
    if info.entry and not any(f["addr"] == info.entry for f in funcs):
        funcs.append({"name": "_entry", "addr": info.entry, "size": 0, "signature": "_entry()",
                      "callers": [], "callees": [], "section": "", "bind": ""})
    funcs.sort(key=lambda f: f["addr"])
    return funcs


class PythonBackend(Backend):
    name = "python"

    def export(self) -> dict:
        strings = []
        for off, enc, text in extract_strings(self.data, 4, limit=50_000):
            sec = self.info.section_for_offset(off)
            va = self.info.offset_to_vaddr(off)
            strings.append({"addr": va if va is not None else None, "offset": off, "value": text, "enc": enc,
                            "section": sec.name if sec else "", "refs": [], "tags": classify_string(text)})
        return {
            "functions": _function_symbols(self.info),
            "imports": [{"name": i.name, "library": i.library, "addr": i.addr} for i in self.info.imports],
            "exports": [{"name": e.name, "addr": e.addr} for e in self.info.exports],
            "symbols": [{"name": s.name, "addr": s.addr, "type": s.kind, "bind": s.bind, "section": s.section}
                        for s in self.info.symbols if s.kind != "func"],
            "strings": strings,
            "blocks": [{"name": s.name, "start": s.vaddr, "size": max(s.vsize, s.size), "perms": s.flags,
                        "kind": s.kind} for s in self.info.sections],
        }

    def disasm(self, addr: int, count: int, whole_function: bool) -> str:
        try:
            import capstone
        except Exception:
            raise BackendError("no disassembler available (install capstone: pip install capstone, or binutils)")
        from .formats import quick_arch_for_capstone
        spec = quick_arch_for_capstone(self.info)
        if spec is None:
            raise BackendError(f"capstone: unsupported architecture {self.info.arch}")
        arch = getattr(capstone, spec[0])
        mode = 0
        for part in spec[1].split("|"):
            mode |= getattr(capstone, part)
        md = capstone.Cs(arch, mode)
        off = self.info.vaddr_to_offset(addr)
        if off is None:
            raise BackendError(f"address 0x{addr:x} is not mapped from the file")
        size = 0
        if whole_function:
            for s in self.info.symbols:
                if s.addr == addr and s.size:
                    size = s.size
                    break
        chunk = self.data[off: off + (size or count * 16)]
        lines = []
        n = 0
        for ins in md.disasm(chunk, addr):
            lines.append(f"0x{ins.address:x}  {ins.bytes.hex():<20}  {ins.mnemonic} {ins.op_str}")
            n += 1
            if not size and n >= count:
                break
        return "\n".join(lines) or "(no instructions decoded)"

    def xrefs(self, addr: int) -> dict:
        # Byte-level: find little/big-endian pointers to addr in the file.
        hits = []
        for width in (self.info.bits // 8,) if self.info.bits else (4, 8):
            needle = addr.to_bytes(width, "little" if self.info.endian != "big" else "big", signed=False) if addr < (1 << (width * 8)) else None
            if not needle:
                continue
            start = 0
            while True:
                i = self.data.find(needle, start)
                if i < 0 or len(hits) >= 200:
                    break
                sec = self.info.section_for_offset(i)
                hits.append({"from": self.info.offset_to_vaddr(i), "offset": i, "func": "", "type": f"pointer{width * 8}",
                             "section": sec.name if sec else ""})
                start = i + 1
        return {"addr": addr, "name": "", "to": hits, "from": [],
                "note": "python backend: pointer-sized literal matches only (no code analysis)"}


# ---------------------------------------------------------------------------
# binutils backend (objdump / nm) with a mined call graph + string refs
# ---------------------------------------------------------------------------

_OBJDUMP_LINE = re.compile(r"^\s*([0-9a-f]+):\s+((?:[0-9a-f]{2}\s)+)\s*(.*)$")
_OBJDUMP_FUNC = re.compile(r"^([0-9a-f]+) <([^>]+)>:\s*$")
_CALL_RE = re.compile(r"\b(?:call[a-z]*|bl|blx|jal|jalr|bsr)\b.*?<([^>+]+)(?:\+0x[0-9a-f]+)?>")
_DATA_REF_RE = re.compile(r"#\s*(?:0x)?([0-9a-f]+)\b")


class BinutilsBackend(Backend):
    name = "binutils"

    def __init__(self, ws, info, data):
        super().__init__(ws, info, data)
        self.objdump = shutil.which("objdump") or shutil.which("llvm-objdump")
        if not self.objdump:
            raise BackendError("objdump not found")
        self._listing: Optional[str] = None

    def _full_listing(self) -> str:
        if self._listing is None:
            cached = self.ws.read_text("disasm/binutils_full.txt")
            if cached:
                self._listing = cached
            else:
                extra = ["-M", "intel"] if self.info.arch in ("x86", "x86_64") and "llvm" not in self.objdump else []
                rc, out, err = _run([self.objdump, "-d", "--no-show-raw-insn", *extra, self.target], timeout=600)
                if rc != 0 and not out:
                    raise BackendError(f"objdump failed: {err.strip()[:400]}")
                self._listing = out
                self.ws.write_text("disasm/binutils_full.txt", out)
        return self._listing

    # A stripped binary gives objdump almost no symbols, so function starts are
    # recovered from the listing itself: every direct call target is a function
    # entry, and so is a prologue that follows a ret/jmp/padding instruction.
    _PROLOGUE_X86 = re.compile(r"^\s*(?:endbr64|endbr32|push\s+(?:rbp|ebp)|sub\s+rsp,)")
    _TERMINATOR_X86 = re.compile(r"^\s*(?:ret|jmp|hlt|int3|nop|xchg\s+ax,ax|cs nop|data16|lea\s+esi,\[esi)")
    _PROLOGUE_ARM64 = re.compile(r"^\s*(?:stp\s+x29,\s*x30|paciasp|sub\s+sp,\s*sp)")
    _TERMINATOR_ARM64 = re.compile(r"^\s*(?:ret|b\s|br\s|nop|udf)")

    def _parse_listing(self) -> Tuple[List[Tuple[int, str, str]], List[int]]:
        """Return ([(addr, mnemonic_line, header_name)], call_target_addrs)."""
        lines: List[Tuple[int, str, str]] = []
        calls: List[int] = []
        header = ""
        for line in self._full_listing().splitlines():
            m = _OBJDUMP_FUNC.match(line)
            if m:
                header = m.group(2)
                lines.append((int(m.group(1), 16), "", header))
                continue
            mm = re.match(r"^\s*([0-9a-f]+):\s*(.*)$", line)
            if not mm:
                continue
            addr = int(mm.group(1), 16)
            text = mm.group(2)
            lines.append((addr, text, ""))
            mc = re.search(r"\b(?:call[a-z]*|bl|jal|bsr)\s+(?:0x)?([0-9a-f]+)\b", text)
            if mc:
                try:
                    calls.append(int(mc.group(1), 16))
                except ValueError:
                    pass
        return lines, calls

    def _synthesized_functions(self, lines, calls) -> Dict[int, dict]:
        """Recover function starts + boundaries when symbols are missing."""
        code = [s for s in self.info.sections if s.kind == "code"]

        def in_code(a: int) -> bool:
            return any(s.vaddr <= a < s.vaddr + max(s.vsize, s.size) for s in code) if code else True

        starts: Dict[int, str] = {}
        for sym in self.info.symbols:
            if sym.defined and sym.kind == "func" and sym.addr:
                starts[sym.addr] = sym.name
        for addr, text, header in lines:
            if header and not re.search(r"[+-]0x[0-9a-f]+>?$", header) and not header.startswith("."):
                starts.setdefault(addr, header)
        for tgt in calls:
            if in_code(tgt):
                starts.setdefault(tgt, "")
        prologue, terminator = (self._PROLOGUE_ARM64, self._TERMINATOR_ARM64) if self.info.arch == "aarch64" \
            else (self._PROLOGUE_X86, self._TERMINATOR_X86)
        if self.info.arch in ("x86", "x86_64", "aarch64"):
            prev_term = True
            for addr, text, header in lines:
                if header:
                    prev_term = True
                    continue
                if prev_term and prologue.match(text) and in_code(addr):
                    starts.setdefault(addr, "")
                prev_term = bool(terminator.match(text))
        if self.info.entry and in_code(self.info.entry):
            starts.setdefault(self.info.entry, "_start")
        ordered = sorted(starts)
        funcs: Dict[int, dict] = {}
        for i, a in enumerate(ordered):
            name = starts[a] or f"sub_{a:x}"
            nxt = ordered[i + 1] if i + 1 < len(ordered) else None
            sec_end = next((s.vaddr + max(s.vsize, s.size) for s in code if s.vaddr <= a < s.vaddr + max(s.vsize, s.size)), None)
            end = min(x for x in (nxt, sec_end) if x is not None) if (nxt or sec_end) else a
            funcs[a] = {"name": name, "addr": a, "size": max(0, end - a), "signature": f"{name}()",
                        "callers": [], "callees": [], "section": "", "bind": ""}
        return funcs

    def export(self) -> dict:
        base = PythonBackend(self.ws, self.info, self.data).export()
        lines, calls = self._parse_listing()
        funcs = self._synthesized_functions(lines, calls)
        for f in base["functions"]:
            if f["addr"] in funcs:
                funcs[f["addr"]].update({k: v for k, v in f.items() if v and k in ("name", "size", "section", "bind")})
                funcs[f["addr"]]["signature"] = f"{funcs[f['addr']]['name']}()"
        ordered_addrs = sorted(funcs)
        str_by_addr: Dict[int, dict] = {s["addr"]: s for s in base["strings"] if s.get("addr") is not None}
        callers: Dict[str, set] = {}
        cur: Optional[dict] = None
        idx = 0
        for addr, text, header in lines:
            if header:
                continue
            # advance current function
            while idx + 1 < len(ordered_addrs) and ordered_addrs[idx + 1] <= addr:
                idx += 1
            cand = funcs.get(ordered_addrs[idx]) if ordered_addrs else None
            cur = cand if cand and cand["addr"] <= addr < cand["addr"] + max(cand["size"], 1) else cur
            if cur is None:
                continue
            mc = re.search(r"\b(?:call[a-z]*|bl|jal|bsr)\s+(?:0x)?([0-9a-f]+)\b", text)
            if mc:
                try:
                    tgt_addr = int(mc.group(1), 16)
                except ValueError:
                    tgt_addr = None
                tgt = funcs[tgt_addr]["name"] if tgt_addr in funcs else None
                if tgt is None:
                    # Exact symbol only: `<sym+0x40>` is an offset into something
                    # else (a GOT slot, a data blob), not a callee.
                    ms = re.search(r"<([^>+-]+)>", text)
                    tgt = ms.group(1) if ms else (f"sub_{tgt_addr:x}" if tgt_addr is not None else None)
                if tgt and tgt != cur["name"] and tgt not in cur["callees"]:
                    cur["callees"].append(tgt)
                if tgt:
                    callers.setdefault(tgt, set()).add(cur["name"])
            elif re.search(r"\bcall[a-z]*\s+", text):
                # Indirect call (through a GOT/IAT slot or register).
                ms = re.search(r"<([^>+-]+)>", text)
                mg = re.search(r"#\s*(?:0x)?([0-9a-f]+)\s*<", text)
                if ms:
                    tgt = ms.group(1)
                elif mg:
                    tgt = f"*got_{mg.group(1)}"
                else:
                    tgt = None
                if tgt and tgt not in cur["callees"]:
                    cur["callees"].append(tgt)
                if tgt:
                    callers.setdefault(tgt, set()).add(cur["name"])
            for md in _DATA_REF_RE.finditer(text):
                try:
                    ref = int(md.group(1), 16)
                except ValueError:
                    continue
                s = str_by_addr.get(ref)
                if s is not None and len(s["refs"]) < 32:
                    s["refs"].append({"from": addr, "func": cur["name"]})
        for f in funcs.values():
            f["callers"] = sorted(callers.get(f["name"], set()))
        base["functions"] = [funcs[a] for a in ordered_addrs]
        base["note"] = ("binutils backend: function boundaries recovered from call targets and prologues "
                        "(sub_<addr> names); install Ghidra or radare2 for real analysis")
        return base

    def disasm(self, addr: int, count: int, whole_function: bool) -> str:
        lines, _ = self._parse_listing()
        snap = self.ws.analysis or {}
        size = 0
        for f in snap.get("functions", []) or []:
            if f.get("addr") == addr:
                size = f.get("size") or 0
                break
        out: List[str] = []
        started = False
        for a, text, header in lines:
            if header:
                if a == addr:
                    started = True
                    out.append(f"{a:x} <{header}>:")
                elif started and whole_function and not size:
                    break
                continue
            if not started and a == addr:
                started = True
            if not started:
                continue
            if whole_function and size and a >= addr + size:
                break
            out.append(f"  {a:x}:\t{text}")
            if not whole_function and len(out) >= count:
                break
        if not out:
            raise BackendError(f"0x{addr:x} not found in objdump listing (not a code address?)")
        return "\n".join(out)

    def xrefs(self, addr: int) -> dict:
        snap = self.ws.analysis or self.export()
        name = ""
        for f in snap.get("functions", []):
            if f["addr"] == addr:
                name = f["name"]
                break
        to: List[dict] = []
        if name:
            for f in snap.get("functions", []):
                if name in f.get("callees", []):
                    to.append({"from": f["addr"], "func": f["name"], "type": "call"})
        for s in snap.get("strings", []):
            if s.get("addr") == addr:
                name = name or f"string:{s['value'][:24]}"
                for r in s.get("refs", []):
                    to.append({"from": r.get("from"), "func": r.get("func"), "type": "data"})
        if not to:
            lines, _ = self._parse_listing()
            hexaddr = f"{addr:x}"
            for a, text, header in lines:
                if header:
                    continue
                if re.search(rf"\b(?:0x)?{hexaddr}\b", text):
                    fn = ""
                    for f in snap.get("functions", []):
                        if f.get("size") and f["addr"] <= a < f["addr"] + f["size"]:
                            fn = f["name"]
                            break
                    to.append({"from": a, "func": fn, "type": "ref"})
                    if len(to) >= 200:
                        break
        frm: List[dict] = []
        if name:
            for f in snap.get("functions", []):
                if f["addr"] == addr:
                    frm = [{"from": addr, "to": None, "target": c, "type": "call"} for c in f.get("callees", [])]
        return {"addr": addr, "name": name, "to": to, "from": frm,
                "note": "binutils backend: call/data references mined from the objdump listing"}


# ---------------------------------------------------------------------------
# radare2 / rizin backend
# ---------------------------------------------------------------------------

class RadareBackend(Backend):
    has_decompiler = True  # pdc pseudo-C always; pdg when r2ghidra present

    def __init__(self, ws, info, data, binary: str = "r2"):
        super().__init__(ws, info, data)
        self.bin = shutil.which(binary) or (shutil.which("radare2") if binary == "r2" else None)
        if not self.bin:
            raise BackendError(f"{binary} not found")
        self.name = "rizin" if "rizin" in os.path.basename(self.bin) else "radare2"
        cfg = _cfg()
        self.level = str(cfg.get("radare_analysis", "aaa") or "aaa")
        self.timeout = float(cfg.get("analysis_timeout", 900) or 900)

    def _cmd(self, cmds: str, analyze: bool = True, timeout: Optional[float] = None) -> str:
        script = (f"{self.level}; " if analyze else "") + cmds
        argv = [self.bin, "-q", "-2", "-e", "scr.color=0", "-e", "scr.utf8=false", "-e", "scr.interactive=false",
                "-c", script, self.target]
        rc, out, err = _run(argv, timeout=timeout or self.timeout)
        if rc == 124:
            raise BackendError(f"{self.name} timed out ({self.timeout:.0f}s); set reverse_engineering.analysis_timeout or radare_analysis: aa")
        if rc != 0 and not out.strip():
            raise BackendError(f"{self.name} failed (rc={rc}): {err.strip()[:400]}")
        return out

    @staticmethod
    def _json(text: str):
        text = text.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # r2 sometimes prints warnings before JSON; take the last line that parses
            for line in reversed(text.splitlines()):
                line = line.strip()
                if line.startswith(("{", "[")):
                    try:
                        return json.loads(line)
                    except json.JSONDecodeError:
                        continue
        return None

    def export(self) -> dict:
        marks = ["FUNCS", "IMPORTS", "EXPORTS", "SYMBOLS", "STRINGS", "SECTIONS", "ENTRY"]
        cmds = "?e @@FUNCS; aflj; ?e @@IMPORTS; iij; ?e @@EXPORTS; iEj; ?e @@SYMBOLS; isj; ?e @@STRINGS; izzj; ?e @@SECTIONS; iSj; ?e @@ENTRY; iej; ?e @@END"
        out = self._cmd(cmds)
        parts: Dict[str, str] = {}
        cur = None
        buf: List[str] = []
        for line in out.splitlines():
            if line.startswith("@@"):
                if cur:
                    parts[cur] = "\n".join(buf)
                cur = line[2:].strip()
                buf = []
            else:
                buf.append(line)
        if cur:
            parts[cur] = "\n".join(buf)
        funcs_raw = self._json(parts.get("FUNCS", "")) or []
        funcs: List[dict] = []
        callers: Dict[str, set] = {}
        by_addr: Dict[int, str] = {}
        for f in funcs_raw:
            addr = int(f.get("offset", f.get("addr", 0)) or 0)
            by_addr[addr] = f.get("name", "")
        for f in funcs_raw:
            addr = int(f.get("offset", f.get("addr", 0)) or 0)
            callees = []
            for c in f.get("callrefs", []) or []:
                if str(c.get("type", "")).upper().startswith(("CALL", "C")):
                    tgt = by_addr.get(int(c.get("addr", 0) or 0), f"0x{int(c.get('addr', 0) or 0):x}")
                    if tgt not in callees:
                        callees.append(tgt)
                    callers.setdefault(tgt, set()).add(f.get("name", ""))
            funcs.append({"name": f.get("name", ""), "addr": addr, "size": int(f.get("size", f.get("realsz", 0)) or 0),
                          "signature": f.get("signature", f"{f.get('name', '')}()"), "callers": [], "callees": callees,
                          "nbbs": f.get("nbbs"), "cc": f.get("cc"), "ninstrs": f.get("ninstrs")})
        for f in funcs:
            f["callers"] = sorted(callers.get(f["name"], set()))
        funcs.sort(key=lambda f: f["addr"])
        imports = [{"name": i.get("name", ""), "library": i.get("libname", i.get("lib", "")), "addr": int(i.get("plt", i.get("vaddr", 0)) or 0)}
                   for i in (self._json(parts.get("IMPORTS", "")) or [])]
        exports = [{"name": e.get("name", ""), "addr": int(e.get("vaddr", 0) or 0)} for e in (self._json(parts.get("EXPORTS", "")) or [])]
        symbols = [{"name": s.get("name", ""), "addr": int(s.get("vaddr", 0) or 0), "type": s.get("type", ""), "bind": s.get("bind", ""),
                    "section": ""} for s in (self._json(parts.get("SYMBOLS", "")) or [])][:50_000]
        strings = []
        for s in (self._json(parts.get("STRINGS", "")) or [])[:20_000]:
            val = s.get("string", "")
            strings.append({"addr": int(s.get("vaddr", 0) or 0), "offset": int(s.get("paddr", 0) or 0), "value": val,
                            "enc": s.get("type", ""), "section": s.get("section", ""), "refs": [], "tags": classify_string(val)})
        blocks = [{"name": b.get("name", ""), "start": int(b.get("vaddr", 0) or 0), "size": int(b.get("vsize", b.get("size", 0)) or 0),
                   "perms": b.get("perm", ""), "kind": ""} for b in (self._json(parts.get("SECTIONS", "")) or [])]
        entry = [int(e.get("vaddr", 0) or 0) for e in (self._json(parts.get("ENTRY", "")) or [])]
        return {"functions": funcs, "imports": imports, "exports": exports, "symbols": symbols, "strings": strings,
                "blocks": blocks, "entry_points": entry}

    def decompile(self, addr: int, name: str) -> str:
        cfg = _cfg()
        prefer = str(cfg.get("decompiler", "auto") or "auto")
        out = ""
        if prefer in ("auto", "ghidra", "pdg"):
            out = self._cmd(f"pdg @ 0x{addr:x}")
            low = out.lower()
            if not out.strip() or "unknown command" in low or "cannot find" in low or "not found" in low or "error" in low[:200]:
                out = ""
        if not out:
            out = self._cmd(f"pdc @ 0x{addr:x}")
            kind = "pseudo-C (pdc). Install r2ghidra / rz-ghidra for real decompilation."
        else:
            kind = "Ghidra decompiler via r2ghidra/rz-ghidra (pdg)"
        return f"// {name} @ 0x{addr:x} — {self.name} {kind}\n{out.rstrip()}\n"

    def disasm(self, addr: int, count: int, whole_function: bool) -> str:
        cmd = f"pdf @ 0x{addr:x}" if whole_function else f"pd {count} @ 0x{addr:x}"
        out = self._cmd(cmd)
        if whole_function and ("Cannot find function" in out or not out.strip()):
            out = self._cmd(f"pd {count} @ 0x{addr:x}")
        return out.rstrip()

    def xrefs(self, addr: int) -> dict:
        out = self._cmd(f"?e @@TO; axtj @ 0x{addr:x}; ?e @@FROM; axfj @ 0x{addr:x}; ?e @@NAME; fd 0x{addr:x}")
        to_raw, from_raw, name = [], [], ""
        cur, buf = None, []
        for line in out.splitlines() + ["@@END"]:
            if line.startswith("@@"):
                if cur == "TO":
                    to_raw = self._json("\n".join(buf)) or []
                elif cur == "FROM":
                    from_raw = self._json("\n".join(buf)) or []
                elif cur == "NAME":
                    name = "\n".join(buf).strip()
                cur, buf = line[2:].strip(), []
            else:
                buf.append(line)
        to = [{"from": int(r.get("from", 0) or 0), "func": r.get("fcn_name", r.get("refname", "")), "type": r.get("type", ""),
               "opcode": r.get("opcode", "")} for r in to_raw]
        frm = [{"from": int(r.get("from", 0) or 0), "to": int(r.get("to", r.get("addr", 0)) or 0), "target": r.get("name", r.get("refname", "")),
                "type": r.get("type", "")} for r in from_raw]
        return {"addr": addr, "name": name, "to": to, "from": frm}

    def search(self, pattern_hex: str, limit: int) -> List[dict]:
        clean = re.sub(r"[\s,]", "", pattern_hex)
        if re.fullmatch(r"(?:[0-9a-fA-F?]{2})+", clean) and len(clean) >= 4:
            out = self._cmd(f"/xj {clean.replace('?', '.')}", analyze=False)
        else:
            out = self._cmd(f"/j {pattern_hex}", analyze=False)
        res = self._json(out) or []
        hits = []
        for r in res[:limit]:
            va = int(r.get("offset", r.get("addr", 0)) or 0)
            hits.append({"addr": va, "offset": self.info.vaddr_to_offset(va), "section": "", "preview": r.get("data", "")})
        return hits


# ---------------------------------------------------------------------------
# Ghidra headless backend
# ---------------------------------------------------------------------------

class GhidraBackend(Backend):
    name = "ghidra"
    has_decompiler = True

    def __init__(self, ws, info, data):
        super().__init__(ws, info, data)
        self.headless = find_ghidra_headless()
        if not self.headless:
            raise BackendError("Ghidra analyzeHeadless not found")
        cfg = _cfg()
        self.import_timeout = float(cfg.get("analysis_timeout", 1800) or 1800)
        self.query_timeout = float(cfg.get("query_timeout", 600) or 600)
        self.project_dir = self.ws.ghidra_dir
        self.project_name = "RoboRE"
        self.program_name = os.path.basename(self.target)
        self.script_dir = str(_SCRIPT_DIR)
        if not (Path(self.script_dir) / "RoboRE.java").exists():
            raise BackendError(f"bundled Ghidra script missing: {self.script_dir}/RoboRE.java")

    def _project_exists(self) -> bool:
        return (self.project_dir / f"{self.project_name}.gpr").exists()

    def _headless(self, script_args: List[str], *, first_import: bool, timeout: float) -> str:
        argv = [self.headless, str(self.project_dir), self.project_name]
        if first_import:
            argv += ["-import", self.target]
        else:
            argv += ["-process", self.program_name, "-noanalysis"]
        argv += ["-scriptPath", self.script_dir, "-postScript", "RoboRE.java", str(self.ws.dir), *script_args]
        env = dict(os.environ)
        env.setdefault("JAVA_TOOL_OPTIONS", "-Djava.awt.headless=true")
        rc, out, err = _run(argv, timeout=timeout, env=env)
        combined = out + "\n" + err
        if rc == 124:
            raise BackendError(f"Ghidra headless timed out after {timeout:.0f}s (reverse_engineering.analysis_timeout)")
        if "ROBO_RE_OK" not in combined:
            tail = "\n".join(combined.strip().splitlines()[-25:])
            if "already exists" in combined and first_import:
                # Project has the program but no analysis.json (interrupted run): retry as process.
                return self._headless(script_args, first_import=False, timeout=timeout)
            raise BackendError(f"Ghidra headless did not complete (rc={rc}). Last output:\n{tail}")
        return combined

    def _ensure_analyzed(self) -> None:
        if self.ws.analysis_backend() == "ghidra" and self._project_exists():
            return
        first = not self._project_exists()
        self._headless(["export"], first_import=first, timeout=self.import_timeout)
        snap = self.ws.read_json("analysis.json")
        if not isinstance(snap, dict) or "functions" not in snap:
            raise BackendError("Ghidra export produced no analysis.json")
        self.ws.save_analysis("ghidra", self._normalize(snap))

    @staticmethod
    def _hex(v) -> int:
        try:
            return int(str(v), 16) if isinstance(v, str) else int(v or 0)
        except ValueError:
            return 0

    def _normalize(self, snap: dict) -> dict:
        funcs = []
        for f in snap.get("functions", []):
            funcs.append({"name": f.get("name", ""), "addr": self._hex(f.get("addr")), "size": int(f.get("size", 0) or 0),
                          "signature": f.get("signature", ""), "callers": f.get("callers", []), "callees": f.get("callees", []),
                          "thunk": f.get("thunk", False), "external": f.get("external", False), "params": f.get("params", 0)})
        funcs.sort(key=lambda f: f["addr"])
        strings = []
        for s in snap.get("strings", []):
            val = s.get("value", "")
            strings.append({"addr": self._hex(s.get("addr")), "offset": None, "value": val, "enc": s.get("type", ""), "section": "",
                            "refs": [{"from": self._hex(r.get("from")), "func": r.get("func", "")} for r in s.get("refs", [])],
                            "tags": classify_string(val)})
        return {
            "program": snap.get("program", {}),
            "functions": funcs,
            "imports": [{"name": i.get("name", ""), "library": i.get("library", ""), "addr": self._hex(i.get("addr"))} for i in snap.get("imports", [])],
            "exports": [{"name": e.get("name", ""), "addr": self._hex(e.get("addr"))} for e in snap.get("exports", [])],
            "symbols": [{"name": s.get("name", ""), "addr": self._hex(s.get("addr")), "type": s.get("type", ""), "bind": "", "section": ""}
                        for s in snap.get("symbols", [])],
            "strings": strings,
            "blocks": [{"name": b.get("name", ""), "start": self._hex(b.get("start")), "size": int(b.get("size", 0) or 0),
                        "perms": b.get("perms", ""), "kind": ""} for b in snap.get("blocks", [])],
            "entry_points": [self._hex(e) for e in snap.get("program", {}).get("entry_points", [])],
        }

    def export(self) -> dict:
        self._ensure_analyzed()
        return self.ws.analysis or {}

    def decompile(self, addr: int, name: str) -> str:
        self._ensure_analyzed()
        self._headless(["decompile", f"0x{addr:x}"], first_import=False, timeout=self.query_timeout)
        text = self.ws.read_text(f"decomp/ghidra_{addr:x}.c")
        if not text:
            raise BackendError(f"Ghidra did not produce decompilation for 0x{addr:x} (no function there?)")
        return text

    def disasm(self, addr: int, count: int, whole_function: bool) -> str:
        self._ensure_analyzed()
        self._headless(["disasm", f"0x{addr:x}", str(count if not whole_function else max(count, 100000))],
                       first_import=False, timeout=self.query_timeout)
        text = self.ws.read_text(f"disasm/ghidra_{addr:x}.txt")
        if not text:
            raise BackendError(f"Ghidra produced no listing for 0x{addr:x}")
        return text

    def xrefs(self, addr: int) -> dict:
        self._ensure_analyzed()
        self._headless(["xrefs", f"0x{addr:x}"], first_import=False, timeout=self.query_timeout)
        raw = self.ws.read_json(f"xrefs_{addr:x}.json") or {}
        return {
            "addr": addr,
            "name": raw.get("name", ""),
            "to": [{"from": self._hex(r.get("from")), "func": r.get("func", ""), "type": r.get("type", "")} for r in raw.get("to", [])],
            "from": [{"from": self._hex(r.get("from")), "to": self._hex(r.get("to")), "target": r.get("target", ""), "type": r.get("type", "")}
                     for r in raw.get("from", [])],
        }

    def search(self, pattern_hex: str, limit: int) -> List[dict]:
        clean = re.sub(r"[\s,]", "", pattern_hex)
        if not (re.fullmatch(r"(?:[0-9a-fA-F?]{2})+", clean) and len(clean) >= 4):
            return python_search(self.data, self.info, pattern_hex, limit)
        self._ensure_analyzed()
        self._headless(["search", clean, str(limit)], first_import=False, timeout=self.query_timeout)
        raw = self.ws.read_json("search.json") or {}
        return [{"addr": self._hex(h.get("addr")), "offset": self.info.vaddr_to_offset(self._hex(h.get("addr"))),
                 "section": h.get("block", ""), "func": h.get("func", ""), "preview": ""} for h in raw.get("hits", [])]

    def rename(self, addr: int, new_name: str) -> str:
        self._ensure_analyzed()
        out = self._headless(["rename", f"0x{addr:x}", new_name], first_import=False, timeout=self.query_timeout)
        m = re.search(r"ROBO_RE_RENAMED.*", out)
        # Keep the cached snapshot in sync so the next `functions` shows the new name.
        snap = self.ws.analysis
        if isinstance(snap, dict):
            for f in snap.get("functions", []):
                if f.get("addr") == addr:
                    f["name"] = new_name
            self.ws.save_analysis("ghidra", snap)
        self.ws.invalidate_function_cache()
        return (m.group(0) if m else "renamed") + " (persisted in the Ghidra project)"

    def comment(self, addr: int, text: str) -> str:
        self._ensure_analyzed()
        note = self.ws.write_text("comment.txt", text)
        self._headless(["comment", f"0x{addr:x}", f"@{note}"], first_import=False, timeout=self.query_timeout)
        self.ws.invalidate_function_cache()
        return "comment persisted in the Ghidra project (shows in decompile/disasm output)"


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

BACKEND_ORDER = ("ghidra", "radare2", "rizin", "binutils", "python")


def make_backend(kind: str, ws: Workspace, info: BinaryInfo, data: bytes) -> Backend:
    if kind == "ghidra":
        return GhidraBackend(ws, info, data)
    if kind in ("radare2", "r2"):
        return RadareBackend(ws, info, data, "r2")
    if kind == "rizin":
        return RadareBackend(ws, info, data, "rizin")
    if kind == "binutils":
        return BinutilsBackend(ws, info, data)
    if kind == "python":
        return PythonBackend(ws, info, data)
    raise BackendError(f"unknown backend {kind!r}; pick one of {', '.join(BACKEND_ORDER)}")


def select_backend(preferred: str, ws: Workspace, info: BinaryInfo, data: bytes,
                   *, need_decompiler: bool = False) -> Tuple[Backend, List[str]]:
    """Return the strongest available backend (and notes about skipped ones).

    ``preferred`` is ``auto`` or a backend name (config
    ``reverse_engineering.backend`` or the tool's ``backend`` argument). An
    explicit choice that isn't installed falls back with a note rather than
    failing, so the agent always gets *some* answer.
    """
    notes: List[str] = []
    order = list(BACKEND_ORDER)
    pref = (preferred or _cfg().get("backend") or "auto")
    pref = str(pref).strip().lower()
    if pref and pref != "auto":
        if pref in ("r2",):
            pref = "radare2"
        if pref in order:
            order.remove(pref)
            order.insert(0, pref)
        else:
            notes.append(f"unknown backend {pref!r}; using auto")
    for kind in order:
        try:
            be = make_backend(kind, ws, info, data)
        except BackendError as exc:
            if pref == kind:
                notes.append(f"{kind} unavailable ({exc}); falling back")
            continue
        if need_decompiler and not be.has_decompiler:
            continue
        return be, notes
    return PythonBackend(ws, info, data), notes
