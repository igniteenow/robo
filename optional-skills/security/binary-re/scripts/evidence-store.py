#!/usr/bin/env python3
"""
Binary RE Evidence & Coverage Store
Tracks findings (evidence) and per-function analysis status (coverage) for a
reverse-engineering investigation, in a single JSON file that survives
session restarts. Adapted from the oss-forensics evidence-store pattern,
with fields specific to disassembly/binary analysis rather than git/GitHub
forensics.

Evidence commands:
  add        - Log a finding, tied to tool output
  list       - List evidence (filter by type/status/function)
  verify     - Re-check SHA-256 hashes for integrity
  query      - Search evidence by keyword
  export     - Export evidence as a Markdown table
  summary    - Print investigation statistics (evidence + coverage)

Coverage commands:
  cov-init   - Seed the coverage checklist from a list of function addresses
  cov-set    - Mark a function's coverage status
  cov-next   - Print the next pending function (for resuming a session)
  cov-list   - List coverage entries (filter by status)

Usage:
  python3 evidence-store.py --store re.json add \\
    --type static_disasm --function 0x4011a0 --tool "objdump -d" \\
    --content "prologue + single memcmp call against a fixed 4-byte magic; no branches" \\
    --status confirmed

  python3 evidence-store.py --store re.json cov-init --functions 0x4011a0,0x401220,0x401340
  python3 evidence-store.py --store re.json cov-set --function 0x4011a0 --status covered
  python3 evidence-store.py --store re.json cov-next
  python3 evidence-store.py --store re.json summary
"""

import argparse
import datetime
import hashlib
import json
import os
import sys

EVIDENCE_TYPES = [
    "static_disasm",   # Disassembler output (objdump/readelf/r2/ghidra/etc.)
    "dynamic_trace",   # Debugger/tracer observation (gdb, strace, ltrace, dtrace)
    "string_xref",     # String or constant cross-reference
    "symbol",          # Symbol table / import / export table entry
    "analysis",        # Derived conclusion from combining other evidence
    "manual",          # Manually noted observation
]

EVIDENCE_STATUSES = ["hypothesis", "confirmed", "disproved", "unresolved"]
COVERAGE_STATUSES = ["pending", "covered", "unresolved", "skipped_trivial"]


def _now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds") + "Z"


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class REStore:
    def __init__(self, filepath: str):
        self.filepath = filepath
        self.data = self._load()

    def _load(self):
        if os.path.exists(self.filepath):
            with open(self.filepath, "r", encoding="utf-8") as f:
                return json.load(f)
        return {"evidence": [], "coverage": [], "next_evidence_id": 1}

    def _save(self):
        tmp = self.filepath + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2, sort_keys=False)
        os.replace(tmp, self.filepath)

    # ── Evidence ──────────────────────────────────────────────────────

    def add_evidence(self, *, ev_type, tool, content, function=None, status="hypothesis"):
        if ev_type not in EVIDENCE_TYPES:
            raise ValueError(f"Unknown evidence type: {ev_type!r} (expected one of {EVIDENCE_TYPES})")
        if status not in EVIDENCE_STATUSES:
            raise ValueError(f"Unknown status: {status!r} (expected one of {EVIDENCE_STATUSES})")

        eid = f"EV-{self.data['next_evidence_id']:04d}"
        self.data["next_evidence_id"] += 1
        entry = {
            "id": eid,
            "timestamp": _now_iso(),
            "type": ev_type,
            "function": function,
            "tool": tool,
            "content": content,
            "content_sha256": _sha256(content),
            "status": status,
        }
        self.data["evidence"].append(entry)
        self._save()
        return entry

    def list_evidence(self, ev_type=None, status=None, function=None):
        rows = self.data["evidence"]
        if ev_type:
            rows = [r for r in rows if r["type"] == ev_type]
        if status:
            rows = [r for r in rows if r["status"] == status]
        if function:
            rows = [r for r in rows if r["function"] == function]
        return rows

    def verify(self):
        bad = []
        for r in self.data["evidence"]:
            if _sha256(r["content"]) != r["content_sha256"]:
                bad.append(r["id"])
        return bad

    def query(self, keyword):
        kw = keyword.lower()
        return [
            r
            for r in self.data["evidence"]
            if kw in r["content"].lower() or kw in (r["function"] or "").lower() or kw in r["tool"].lower()
        ]

    # ── Coverage ──────────────────────────────────────────────────────

    def cov_init(self, functions):
        existing = {c["function"] for c in self.data["coverage"]}
        added = 0
        for fn in functions:
            fn = fn.strip()
            if fn and fn not in existing:
                self.data["coverage"].append({"function": fn, "status": "pending", "evidence_ids": []})
                existing.add(fn)
                added += 1
        self._save()
        return added

    def cov_set(self, function, status, evidence_id=None):
        if status not in COVERAGE_STATUSES:
            raise ValueError(f"Unknown coverage status: {status!r} (expected one of {COVERAGE_STATUSES})")
        for c in self.data["coverage"]:
            if c["function"] == function:
                c["status"] = status
                if evidence_id and evidence_id not in c["evidence_ids"]:
                    c["evidence_ids"].append(evidence_id)
                self._save()
                return c
        # Not seeded yet — add it directly rather than forcing a separate init step.
        entry = {"function": function, "status": status, "evidence_ids": [evidence_id] if evidence_id else []}
        self.data["coverage"].append(entry)
        self._save()
        return entry

    def cov_list(self, status=None):
        rows = self.data["coverage"]
        if status:
            rows = [r for r in rows if r["status"] == status]
        return rows

    def cov_next(self):
        for c in self.data["coverage"]:
            if c["status"] == "pending":
                return c
        return None

    def summary(self):
        ev = self.data["evidence"]
        cov = self.data["coverage"]
        by_status = {s: sum(1 for e in ev if e["status"] == s) for s in EVIDENCE_STATUSES}
        cov_by_status = {s: sum(1 for c in cov if c["status"] == s) for s in COVERAGE_STATUSES}
        total_cov = len(cov)
        done = cov_by_status["covered"] + cov_by_status["skipped_trivial"]
        return {
            "evidence_total": len(ev),
            "evidence_by_status": by_status,
            "coverage_total": total_cov,
            "coverage_by_status": cov_by_status,
            "coverage_pct": round(100 * done / total_cov, 1) if total_cov else None,
        }


def _print_table(rows, columns):
    if not rows:
        print("(none)")
        return
    widths = [max(len(str(r.get(c, ""))) for r in rows + [dict(zip(columns, columns))]) for c in columns]
    header = "  ".join(c.ljust(w) for c, w in zip(columns, widths))
    print(header)
    print("  ".join("-" * w for w in widths))
    for r in rows:
        print("  ".join(str(r.get(c, "")).ljust(w) for c, w in zip(columns, widths)))


def main():
    parser = argparse.ArgumentParser(description="Binary RE evidence and coverage tracker")
    parser.add_argument("--store", required=True, help="Path to the JSON store file")
    sub = parser.add_subparsers(dest="command", required=True)

    p_add = sub.add_parser("add", help="Log a finding")
    p_add.add_argument("--type", required=True, choices=EVIDENCE_TYPES)
    p_add.add_argument("--tool", required=True, help="Tool that produced this, e.g. 'objdump -d'")
    p_add.add_argument("--content", required=True, help="The finding, in your own words, tied to the tool output")
    p_add.add_argument("--function", default=None, help="Function address/name this evidence is about")
    p_add.add_argument("--status", default="hypothesis", choices=EVIDENCE_STATUSES)

    p_list = sub.add_parser("list", help="List evidence")
    p_list.add_argument("--type", default=None, choices=EVIDENCE_TYPES)
    p_list.add_argument("--status", default=None, choices=EVIDENCE_STATUSES)
    p_list.add_argument("--function", default=None)

    sub.add_parser("verify", help="Re-check evidence integrity hashes")

    p_query = sub.add_parser("query", help="Search evidence by keyword")
    p_query.add_argument("keyword")

    sub.add_parser("export", help="Export evidence as a Markdown table")
    sub.add_parser("summary", help="Print evidence + coverage statistics")

    p_cov_init = sub.add_parser("cov-init", help="Seed the coverage checklist")
    p_cov_init.add_argument("--functions", required=True, help="Comma-separated function addresses/names")

    p_cov_set = sub.add_parser("cov-set", help="Set a function's coverage status")
    p_cov_set.add_argument("--function", required=True)
    p_cov_set.add_argument("--status", required=True, choices=COVERAGE_STATUSES)
    p_cov_set.add_argument("--evidence-id", default=None)

    p_cov_list = sub.add_parser("cov-list", help="List coverage entries")
    p_cov_list.add_argument("--status", default=None, choices=COVERAGE_STATUSES)

    sub.add_parser("cov-next", help="Print the next pending function")

    args = parser.parse_args()
    store = REStore(args.store)

    if args.command == "add":
        entry = store.add_evidence(
            ev_type=args.type, tool=args.tool, content=args.content, function=args.function, status=args.status
        )
        print(f"Added {entry['id']} ({entry['type']}, {entry['status']})")

    elif args.command == "list":
        rows = store.list_evidence(ev_type=args.type, status=args.status, function=args.function)
        _print_table(rows, ["id", "type", "function", "status", "tool"])

    elif args.command == "verify":
        bad = store.verify()
        if bad:
            print(f"INTEGRITY FAILURE on: {', '.join(bad)}", file=sys.stderr)
            sys.exit(1)
        print(f"All {len(store.data['evidence'])} evidence entries verified OK.")

    elif args.command == "query":
        rows = store.query(args.keyword)
        _print_table(rows, ["id", "type", "function", "status", "content"])

    elif args.command == "export":
        print("| ID | Type | Function | Status | Tool | Finding |")
        print("|---|---|---|---|---|---|")
        for r in store.data["evidence"]:
            content = r["content"].replace("|", "\\|").replace("\n", " ")
            print(f"| {r['id']} | {r['type']} | {r['function'] or ''} | {r['status']} | {r['tool']} | {content} |")

    elif args.command == "summary":
        s = store.summary()
        print(json.dumps(s, indent=2))

    elif args.command == "cov-init":
        added = store.cov_init(args.functions.split(","))
        print(f"Seeded {added} new function(s) into the coverage checklist.")

    elif args.command == "cov-set":
        entry = store.cov_set(args.function, args.status, args.evidence_id)
        print(f"{entry['function']} -> {entry['status']}")

    elif args.command == "cov-list":
        rows = store.cov_list(status=args.status)
        _print_table(rows, ["function", "status"])

    elif args.command == "cov-next":
        entry = store.cov_next()
        if entry is None:
            print("No pending functions — coverage checklist is fully resolved.")
        else:
            print(entry["function"])


if __name__ == "__main__":
    main()
