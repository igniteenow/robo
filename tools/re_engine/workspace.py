"""Per-target workspace for the reverse-engineering engine.

Every analyzed file gets a directory under ``$ROBO_HOME/re/<sha256[:16]>/``
holding:

* ``target.json``     — path, size, hashes, format summary (from the parsers)
* ``analysis.json``   — the backend snapshot (functions, xrefs, strings …)
* ``decomp/<addr>.c`` — decompiled functions, one file each
* ``disasm/<addr>.txt``
* ``annotations.json``— renames / comments the agent made (applied on top of
                         every backend's output, and pushed into the Ghidra
                         project when that backend is active)
* ``ghidra/``         — the persistent Ghidra project (so re-analysis is never
                         needed; follow-up queries only run a post-script)
* ``notes.md``        — free-form analysis notes the agent keeps

Keyed by content hash, so re-analyzing a rebuilt binary starts a fresh
workspace automatically while a renamed copy of the same bytes reuses one.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _robo_home() -> Path:
    try:
        from robo_constants import get_robo_home
        return Path(get_robo_home())
    except Exception:
        return Path(os.environ.get("ROBO_HOME") or (Path.home() / ".robo"))


def re_root() -> Path:
    return _robo_home() / "re"


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


class Workspace:
    """Cache + annotation store for one target file."""

    def __init__(self, target: str, digest: Optional[str] = None):
        self.target = os.path.abspath(target)
        self.digest = digest or sha256_file(self.target)
        self.dir = re_root() / self.digest[:16]
        self.dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "decomp").mkdir(exist_ok=True)
        (self.dir / "disasm").mkdir(exist_ok=True)
        self._annotations: Optional[Dict[str, Any]] = None

    # -- generic JSON blobs -------------------------------------------------
    def _path(self, name: str) -> Path:
        return self.dir / name

    def read_json(self, name: str) -> Optional[Any]:
        p = self._path(name)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None

    def write_json(self, name: str, obj: Any) -> None:
        p = self._path(name)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
        os.replace(tmp, p)

    def read_text(self, name: str) -> Optional[str]:
        p = self._path(name)
        return p.read_text(encoding="utf-8", errors="replace") if p.exists() else None

    def write_text(self, name: str, text: str) -> Path:
        p = self._path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    # -- analysis snapshot ----------------------------------------------------
    @property
    def analysis(self) -> Optional[dict]:
        return self.read_json("analysis.json")

    def save_analysis(self, backend: str, snapshot: dict) -> None:
        snapshot = dict(snapshot)
        snapshot["backend"] = backend
        snapshot["saved_at"] = time.time()
        self.write_json("analysis.json", snapshot)

    def analysis_backend(self) -> str:
        a = self.analysis
        return str(a.get("backend", "")) if isinstance(a, dict) else ""

    # -- decompiled / disassembled function cache -----------------------------
    @staticmethod
    def _addr_key(addr: int) -> str:
        return f"{addr:x}"

    def cached_decomp(self, addr: int, backend: str) -> Optional[str]:
        return self.read_text(f"decomp/{backend}_{self._addr_key(addr)}.c")

    def save_decomp(self, addr: int, backend: str, text: str) -> None:
        self.write_text(f"decomp/{backend}_{self._addr_key(addr)}.c", text)

    def cached_disasm(self, addr: int, backend: str) -> Optional[str]:
        return self.read_text(f"disasm/{backend}_{self._addr_key(addr)}.txt")

    def save_disasm(self, addr: int, backend: str, text: str) -> None:
        self.write_text(f"disasm/{backend}_{self._addr_key(addr)}.txt", text)

    def invalidate_function_cache(self) -> None:
        for sub in ("decomp", "disasm"):
            d = self.dir / sub
            for f in d.glob("*"):
                try:
                    f.unlink()
                except OSError:
                    pass

    # -- annotations (renames + comments) -------------------------------------
    @property
    def annotations(self) -> Dict[str, Any]:
        if self._annotations is None:
            self._annotations = self.read_json("annotations.json") or {"renames": {}, "comments": {}}
            self._annotations.setdefault("renames", {})
            self._annotations.setdefault("comments", {})
        return self._annotations

    def save_annotations(self) -> None:
        self.write_json("annotations.json", self.annotations)

    def rename(self, addr: int, new_name: str, old_name: str = "") -> None:
        self.annotations["renames"][self._addr_key(addr)] = {
            "name": new_name, "old": old_name, "at": time.time(),
        }
        self.save_annotations()

    def comment(self, addr: int, text: str) -> None:
        key = self._addr_key(addr)
        entry = self.annotations["comments"].setdefault(key, [])
        entry.append({"text": text, "at": time.time()})
        self.save_annotations()

    def display_name(self, addr: int, default: str) -> str:
        r = self.annotations["renames"].get(self._addr_key(addr))
        return str(r["name"]) if r else default

    def comments_for(self, addr: int) -> list:
        return [c["text"] for c in self.annotations["comments"].get(self._addr_key(addr), [])]

    def resolve_renamed(self, name: str) -> Optional[int]:
        """Map a user-assigned name back to its address."""
        for key, r in self.annotations["renames"].items():
            if r.get("name") == name:
                try:
                    return int(key, 16)
                except ValueError:
                    continue
        return None

    # -- notes ------------------------------------------------------------------
    def append_note(self, text: str) -> None:
        p = self._path("notes.md")
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(p, "a", encoding="utf-8") as fh:
            fh.write(f"\n## {stamp}\n{text.rstrip()}\n")

    def notes(self) -> str:
        return self.read_text("notes.md") or ""

    # -- ghidra project -----------------------------------------------------------
    @property
    def ghidra_dir(self) -> Path:
        d = self.dir / "ghidra"
        d.mkdir(exist_ok=True)
        return d

    def summary(self) -> dict:
        a = self.analysis or {}
        return {
            "workspace": str(self.dir),
            "backend": a.get("backend", ""),
            "functions": len(a.get("functions", []) or []),
            "strings": len(a.get("strings", []) or []),
            "renames": len(self.annotations["renames"]),
            "comments": sum(len(v) for v in self.annotations["comments"].values()),
            "decompiled_cached": len(list((self.dir / "decomp").glob("*.c"))),
        }


_HEX_RE = re.compile(r"^(?:0x)?([0-9a-fA-F]+)$")


def parse_address(text: Any) -> Optional[int]:
    """Parse ``0x401000`` / ``401000`` / ``4198400`` style addresses."""
    if text is None:
        return None
    if isinstance(text, int):
        return text
    t = str(text).strip()
    if not t:
        return None
    if t.lower().startswith("0x"):
        try:
            return int(t, 16)
        except ValueError:
            return None
    if t.isdigit():
        # Ambiguous: prefer hex when it looks like an address (>= 4 digits and
        # contains a-f is impossible for pure digits), so decimal here.
        return int(t, 10)
    m = _HEX_RE.match(t)
    if m:
        try:
            return int(m.group(1), 16)
        except ValueError:
            return None
    return None
