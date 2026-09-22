"""Content policy for Robo's persistent files.

Robo keeps four kinds of persistent text that shape every future turn:

* ``MEMORY.md``  — durable facts about the environment and the work
* ``USER.md``    — durable facts about the person Robo works with
* ``SOUL.md``    — identity, values and working style (seeded per install)
* ``AGENTS.md`` / ``.cursorrules`` — project conventions

Because these files are injected into the system prompt of *every* session,
they must never hold secrets, transient state, raw tool output, or text
that tries to relax Robo's safety posture. This module is the single place
that decides what may be written to each of them and what is scrubbed or
refused. It is deliberately conservative and explains every decision so the
agent can rewrite the entry rather than fight the gate.

Two entry points:

``evaluate(target, content)``
    Called by the memory tool before ``add``/``replace``. Returns a
    :class:`Verdict` — ``allow`` (possibly with a scrubbed ``content``),
    ``reject`` with a human-readable ``reason`` and a ``hint`` on how to
    rewrite the entry.

``sanitize_context_file(name, text)``
    Called when SOUL.md / AGENTS.md are loaded into the prompt. Secrets are
    replaced by ``[redacted]`` and safety-override lines are dropped; the
    rest is returned unchanged. Findings are logged once per file so an
    operator notices a bad edit without the prompt ever carrying the secret.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

MEMORY_TARGETS = ("memory", "user")
CONTEXT_FILES = ("SOUL.md", "AGENTS.md", ".cursorrules", "USER.md", "MEMORY.md")

# ── Secrets ──────────────────────────────────────────────────────────────────
_SECRET_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("OpenAI-style key", re.compile(r"\bsk-(?:proj-|ant-|or-v1-)?[A-Za-z0-9_\-]{16,}")),
    ("Anthropic key", re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{16,}")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9]{20,}")),
    ("GitHub fine-grained token", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}")),
    ("AWS access key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("Slack token", re.compile(r"\bxox[abprs]-[A-Za-z0-9\-]{10,}")),
    ("Telegram bot token", re.compile(r"\b\d{8,10}:[A-Za-z0-9_\-]{30,}\b")),
    ("Discord token", re.compile(r"\b[MN][A-Za-z\d]{23,}\.[\w-]{6}\.[\w-]{27,}\b")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}")),
    ("Stripe key", re.compile(r"\b[sr]k_(?:live|test)_[A-Za-z0-9]{16,}")),
    ("bearer token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9_\-\.=]{20,}")),
    ("password assignment", re.compile(r"(?i)\b(?:password|passwd|pwd|secret|api[_\- ]?key|token|client[_\- ]?secret)\s*[:=]\s*['\"]?[^\s'\"]{6,}")),
    ("connection string", re.compile(r"(?i)\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp)://[^:\s/]+:[^@\s]+@")),
]

# ── Text that tries to change how Robo behaves around safety ───────────────
_OVERRIDE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("approval bypass", re.compile(r"(?i)\b(?:always|auto|automatically)\s+(?:approve|allow)\b|\bskip\s+(?:the\s+)?approval|\bnever\s+ask\s+(?:for\s+)?(?:permission|approval|confirmation)|\byolo\s+mode\b|\bwithout\s+asking\b.*\b(?:rm|delete|force|push)")),
    ("instruction hijack", re.compile(r"(?i)\bignore\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions|rules|prompts?)")),
    ("secrecy from operator", re.compile(r"(?i)\b(?:do not|don't|never)\s+(?:tell|show|reveal|mention)\s+(?:this|it)\s+to\s+the\s+(?:user|operator|owner)")),
    ("identity override", re.compile(r"(?i)\byou\s+are\s+(?:now|no longer)\s+(?:robo|an?\s+ai|claude|gpt|hermes)|\bpretend\s+(?:you\s+are|to\s+be)\b")),
]

# ── Transient / session-bound state that should not be persisted ───────────
_TRANSIENT_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("clock time", re.compile(r"\b(?:[01]?\d|2[0-3]):[0-5]\d(?::[0-5]\d)?\s*(?:am|pm|AM|PM|UTC|GMT)?\b")),
    ("'currently/right now' state", re.compile(r"(?i)\b(?:right now|currently|at the moment|for now|is running|is still running|in progress|temporarily)\b")),
    ("process id / port snapshot", re.compile(r"(?i)\b(?:pid|process id)\s*[:=]?\s*\d{2,}|\blistening on (?:port )?\d{2,5}\b")),
    ("one-off todo", re.compile(r"(?i)^\s*(?:todo|next step|remember to)\b.*\b(?:today|tomorrow|this session|after this)\b")),
]

_TOOL_DUMP_MARKERS = (
    re.compile(r"(?m)^\s*Traceback \(most recent call last\)"),
    re.compile(r"(?m)^\s*(?:\$|>|#)\s*\S+.*\n(?:.*\n){4,}"),           # shell transcript
    re.compile(r"(?m)^\s*(?:\[\d{4}-\d\d-\d\d[ T]\d\d:\d\d|\d{4}-\d\d-\d\dT\d\d:\d\d).*\n(?:.*\n){3,}"),  # log lines
    re.compile(r"(?m)^\s*(?:ERROR|WARN(?:ING)?|INFO|DEBUG)\b.*\n(?:.*\n){3,}"),
)

_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s\-.]?)?(?:\(?\d{3}\)?[\s\-.]?)\d{3}[\s\-.]?\d{4}(?!\d)")
_ADDRESS_HINT = re.compile(r"(?i)\b\d{1,5}\s+[A-Za-z]+\s+(?:street|st\.|avenue|ave\.|road|rd\.|lane|ln\.|drive|dr\.|blvd)\b")

MAX_ENTRY_CHARS = 600
MAX_ENTRY_LINES = 8


@dataclass
class Verdict:
    ok: bool
    content: str
    reason: str = ""
    hint: str = ""
    findings: List[str] = field(default_factory=list)

    def as_error(self) -> str:
        parts = [f"Not saved: {self.reason}."]
        if self.hint:
            parts.append(self.hint)
        return " ".join(parts)


def _find(patterns: List[Tuple[str, re.Pattern]], text: str) -> List[str]:
    return [label for label, rx in patterns if rx.search(text)]


def redact_secrets(text: str) -> Tuple[str, List[str]]:
    """Replace every secret-shaped token with ``[redacted]``."""
    found: List[str] = []
    for label, rx in _SECRET_PATTERNS:
        if rx.search(text):
            found.append(label)
            text = rx.sub("[redacted]", text)
    return text, found


def evaluate(target: str, content: str) -> Verdict:
    """Decide whether *content* may be stored in the memory file *target*.

    ``target`` is ``"memory"`` (MEMORY.md — environment/work facts) or
    ``"user"`` (USER.md — facts about the operator). The rules, in order:

    1. Secrets are never stored, even redacted — a memory that used to hold
       a key is a memory the agent will try to "recover".
    2. Text that relaxes approvals, hijacks instructions, or asks Robo to
       hide things from its operator is refused.
    3. Raw tool output (tracebacks, logs, shell transcripts) is refused —
       memory holds *conclusions*, not evidence dumps.
    4. Session-bound state (clock times, "currently running", pids/ports)
       is refused — it will be wrong by the next session.
    5. Third-party personal data (other people's emails, phone numbers,
       street addresses) is refused in MEMORY.md. USER.md may hold the
       operator's own contact details.
    6. Entries are short: one durable fact each (≤ 600 chars, ≤ 8 lines).
    """
    text = (content or "").strip()
    if not text:
        return Verdict(False, text, "the entry is empty")
    target = (target or "memory").strip().lower()

    secrets = _find(_SECRET_PATTERNS, text)
    if secrets:
        return Verdict(False, text, f"it contains a secret ({', '.join(secrets)})",
                       "Secrets belong in ~/.robo/.env or a secret manager, never in memory. "
                       "Store *where* the credential lives (e.g. 'GitHub token is in .env as GITHUB_TOKEN'), not its value.",
                       secrets)

    overrides = _find(_OVERRIDE_PATTERNS, text)
    if overrides:
        return Verdict(False, text, f"it would change Robo's safety behaviour ({', '.join(overrides)})",
                       "Memory records facts and preferences; approval and safety policy lives in config.yaml "
                       "(`approvals:`), where the operator sets it deliberately.", overrides)

    if any(rx.search(text + "\n") for rx in _TOOL_DUMP_MARKERS):
        return Verdict(False, text, "it looks like raw tool output (log lines, a traceback, or a shell transcript)",
                       "Write the conclusion instead: what failed, why, and what fixed it — one or two sentences.",
                       ["tool output"])

    transient = _find(_TRANSIENT_PATTERNS, text)
    if transient:
        return Verdict(False, text, f"it describes session-bound state ({', '.join(transient)})",
                       "Memory must still be true next week. Keep the durable part (a path, a preference, a "
                       "decision) and drop what is only true right now.", transient)

    if target == "memory":
        pii = []
        if _EMAIL_RE.search(text):
            pii.append("email address")
        if _PHONE_RE.search(text):
            pii.append("phone number")
        if _ADDRESS_HINT.search(text):
            pii.append("street address")
        if pii:
            return Verdict(False, text, f"it contains personal contact data ({', '.join(pii)})",
                           "MEMORY.md is for the environment and the work. Facts about the operator go to "
                           "USER.md (target='user'); other people's contact details should not be stored at all.",
                           pii)

    lines = text.count("\n") + 1
    if len(text) > MAX_ENTRY_CHARS or lines > MAX_ENTRY_LINES:
        return Verdict(False, text, f"it is too long for one entry ({len(text)} chars, {lines} lines)",
                       f"Keep each entry to one durable fact (≤ {MAX_ENTRY_CHARS} chars, ≤ {MAX_ENTRY_LINES} lines). "
                       "Split it, or keep only the part you will need again.", ["length"])

    return Verdict(True, text)


def sanitize_context_file(name: str, text: str) -> Tuple[str, List[str]]:
    """Scrub SOUL.md / AGENTS.md / .cursorrules before they enter the prompt.

    Secrets become ``[redacted]``; lines that try to relax approvals or
    hijack instructions are dropped. Everything else passes through
    unchanged. Returns ``(clean_text, findings)``.
    """
    if not text:
        return text, []
    clean, findings = redact_secrets(text)
    kept: List[str] = []
    dropped = 0
    for line in clean.split("\n"):
        if _find(_OVERRIDE_PATTERNS, line):
            dropped += 1
            continue
        kept.append(line)
    if dropped:
        findings.append(f"{dropped} safety-override line(s) dropped")
    if findings:
        logger.warning("%s: content policy scrubbed %s — edit the file to remove them", name, ", ".join(findings))
    return "\n".join(kept), findings


def describe_policy(target: str = "memory") -> str:
    """Short, prompt-friendly summary of what belongs in a memory file."""
    if target == "user":
        return ("USER.md holds durable facts about the operator: name, role, preferences, working hours, "
                "how they like answers. Never secrets, never session state, never other people's data.")
    if target == "soul":
        return ("SOUL.md holds identity, values and working style only — no project facts, no secrets, "
                "no operational state, nothing that changes approval or safety behaviour.")
    return ("MEMORY.md holds durable facts about the environment and the work: paths, conventions, decisions, "
            "gotchas and their fixes. Never secrets (say where a credential lives, not its value), never raw "
            "tool output, never session-bound state, never third-party personal data. One fact per entry.")
