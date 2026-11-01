"""Judgment: deterministic checks that keep Robo's edits and claims tied to evidence.

Robo already has several layers that make it harder to trust the model
blindly: the "verify before you claim" prompt guidance, the mid-turn claim
check (``agent/claim_verification.py``), the end-of-turn fact check against
sources (``agent/fact_check.py``), the verify-on-stop gate for edited code
(``agent/verification_stop.py``) and the smart-approval reviewer for risky
commands (``tools/approval.py``). This module adds the two cheap,
deterministic pieces that were still missing — no model calls, no new tools:

* **Read before edit.** ``patch`` / ``write_file`` on a file that exists but
  was never read in this task is stopped once with a plain instruction to
  read it first. The second attempt on the same path goes through, so the
  guard can never wedge a task; it only costs one round-trip the first time
  the model tries to edit something it has not looked at.

* **Evidence for completion claims.** When the final answer says a test,
  lint, type check or build *passed* but no such command ran successfully in
  this turn, the model gets one follow-up asking it to run the check or to
  restate exactly what it did and did not verify. Evidence is read from the
  turn's own tool results, so a quoted summary of an earlier run or a made-up
  "12 passed" cannot stand in for a real one.

Both are config-gated under ``agent.judgment`` (``read_before_edit``,
``evidence_claims``; default on) and fail open: any error inside this module
leaves the turn exactly as it would have been without it.
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Iterable, Optional

logger = logging.getLogger(__name__)

_DEFAULTS: dict[str, bool] = {
    "read_before_edit": True,
    "evidence_claims": True,
}

# Environment overrides (tests pin these off; operators can too).
_ENV_OVERRIDES: dict[str, str] = {
    "read_before_edit": "ROBO_READ_BEFORE_EDIT",
    "evidence_claims": "ROBO_EVIDENCE_CLAIMS",
}

_FALSE_TOKENS = frozenset({"0", "false", "no", "off"})


def judgment_enabled(feature: str, config: Optional[dict] = None) -> bool:
    """Whether one judgment feature is on.

    The env var (``ROBO_READ_BEFORE_EDIT`` / ``ROBO_EVIDENCE_CLAIMS``) wins,
    then ``agent.judgment.<feature>`` in config.yaml, then the default (on).
    Unknown features are off. Never raises.
    """
    if feature not in _DEFAULTS:
        return False
    env_name = _ENV_OVERRIDES.get(feature)
    if env_name:
        env = os.environ.get(env_name)
        if env is not None:
            return env.strip().lower() not in _FALSE_TOKENS
    try:
        if config is None:
            from robo_cli.config import load_config_readonly

            config = load_config_readonly()
        agent_cfg = (config or {}).get("agent") if isinstance(config, dict) else None
        section = agent_cfg.get("judgment") if isinstance(agent_cfg, dict) else None
        if isinstance(section, bool):
            return section
        if isinstance(section, dict):
            value = section.get(feature)
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.strip().lower() not in _FALSE_TOKENS
    except Exception:
        logger.debug("judgment config read failed; using default", exc_info=True)
    return _DEFAULTS[feature]


def on_messaging_surface() -> bool:
    """Whether this turn is delivered over a human chat channel (Telegram, …).

    The evidence-claims follow-up is an internal loop turn; on a messaging
    surface its narrative would reach a person as chat noise, so the gate
    stays off there — the same surface rule verify-on-stop uses, but not its
    on/off switch (which many installs have turned off for being noisy; this
    gate is far narrower). Never raises.
    """
    try:
        from gateway.session_context import session_is_messaging_surface

        return bool(session_is_messaging_surface())
    except Exception:
        return False


def evidence_claims_active(config: Optional[dict] = None) -> bool:
    """Whether the evidence-claims gate should run for the current turn."""
    return judgment_enabled("evidence_claims", config) and not on_messaging_surface()


# ---------------------------------------------------------------------------
# Read before edit
# ---------------------------------------------------------------------------


def read_before_edit_message(path: str, tool_name: str) -> str:
    """The one-time message returned when an unread existing file is edited."""
    return (
        f"Read {path} before changing it: it exists and has not been read in "
        f"this task, so a {tool_name} based on remembered or assumed contents "
        "can corrupt it. Call read_file on it (the relevant region is enough), "
        "then make the change against what is actually there. If you have "
        "already seen the current contents another way, repeat this exact "
        "call and it will proceed."
    )


# ---------------------------------------------------------------------------
# Evidence for completion claims
# ---------------------------------------------------------------------------

_CHECK_WORDS = (
    r"(?:unit |integration |e2e |end-to-end |regression |smoke |full |whole |entire )?"
    r"(?:tests?|test suites?|suites?|specs?|checks?|lint(?:ing|er)?|type ?check(?:ing|er|s)?|"
    r"typecheck|builds?|compilation|ci)"
)

# Sentences that state a check succeeded. Deliberately narrow: a false
# negative costs nothing (the other verification layers still apply), a
# false positive costs the model one extra round-trip.
_CLAIM_PATTERNS = [
    re.compile(
        r"\b(?:all|every|the|both|these|those|its|our|my|remaining|existing|new|\d+)\s+"
        + _CHECK_WORDS
        + r"\s+(?:is|are|now|still|were|was|all|also)?\s*(?:pass(?:es|ed|ing)?|green|clean|"
        r"succeed(?:s|ed)?|successful(?:ly)?|ok|fine)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b" + _CHECK_WORDS + r"\s+(?:is|are|now|still|also)?\s*(?:pass(?:es|ed|ing)?|green|"
        r"clean|succeed(?:s|ed)|successful)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b\d+\s+(?:tests?\s+)?passed\b", re.IGNORECASE),
    re.compile(
        r"\b(?:i|robo|we)\s+(?:have\s+|'ve\s+|just\s+|also\s+|then\s+)?(?:ran|run|re-?ran|"
        r"executed)\s+(?:the\s+|all\s+|every\s+|a\s+)?(?:full\s+|whole\s+|complete\s+)?"
        + _CHECK_WORDS
        + r"\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:verified|confirmed|validated|made sure)\s+(?:that\s+)?(?:it|this|everything|"
        r"the\s+(?:fix|change|changes|patch|code|refactor))\s+(?:still\s+|now\s+)?"
        r"(?:works?|passes|builds?|compiles?|is\s+working|runs?\s+(?:fine|correctly|clean(?:ly)?))\b",
        re.IGNORECASE,
    ),
]

# A sentence with any of these is not a completed-check claim: a failure
# report, a hedge, an instruction to the person, or a hypothetical.
_NOT_A_CLAIM = re.compile(
    r"\b(?:do|does|did|have|has|had|is|are|was|were|wo|would|should|could|ca|must|need|ai)n'?t\b|"
    r"\b(?:fail(?:s|ed|ing|ures?)?|error(?:s|ed)?|broke|broken|not|never|"
    r"no\s+longer|cannot|unable|"
    r"should|would|could|might|may|expect(?:ed|s|ing)?|hopefully|presumably|likely|"
    r"once\s+you|when\s+you|if\s+you|after\s+you|you\s+(?:can|should|could|may|will|need)|"
    r"please|let\s+me|going\s+to|will\s+(?:run|now)|next\s+step|todo|to\s+do|"
    r"need\s+to|needs?\s+to|in\s+order\s+to|so\s+that|make\s+(?:sure|the|all|them|it)|"
    r"ensure|ensuring|try(?:ing)?\s+to|want|goal|aim|"
    r"earlier|previous(?:ly)?|before\s+(?:this|my|the)|last\s+(?:turn|time|run|session)|"
    r"until|unless|before\s+merging|skipped|skip|pending|in\s+progress|still\s+need|"
    r"re-?run\s+(?:them|it|the)|run\s+(?:them|it)\s+(?:yourself|locally))\b",
    re.IGNORECASE,
)

_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+|\n+")
_MAX_CLAIM_CHARS = 220

# Commands whose successful foreground run counts as evidence for a
# test/lint/typecheck/build claim. A command is split into its top-level
# segments (``cd x && pytest``), leading environment assignments and common
# wrappers are dropped, and the segment must START with a known runner —
# ``grep -rn pytest .`` or ``pip install pytest`` never count.
_SEGMENT_SPLIT_RE = re.compile(r"\s*(?:&&|\|\||;|\||\n|\(|\))\s*")
_ENV_ASSIGN_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=(?:\"[^\"]*\"|'[^']*'|\S*)\s+")
_WRAPPER_RE = re.compile(
    r"^(?:sudo(?:\s+-\S+)*|time|env|nice|nohup|exec|command|timeout\s+\S+|"
    r"xvfb-run(?:\s+-\S+)*|stdbuf\s+-\S+|unbuffer|script\s+-q\s+\S+)\s+",
    re.IGNORECASE,
)
_RUNNER_HEAD_RE = re.compile(
    r"^(?:"
    r"(?:python[0-9.]*|py|uv|uvx|poetry|pipenv|pdm|hatch|pipx)\s+(?:run\s+)?(?:-m\s+)?"
    r"(?:pytest|unittest|nose2?|tox|nox|ruff(?:@\S+)?|mypy|pyright|flake8|pylint|black|isort|bandit)\b"
    r"|(?:pytest|py\.test|tox|nox|ruff|mypy|pyright|flake8|pylint|bandit)\b"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:test|tests|check|lint|typecheck|type-check|build|ci|verify|coverage|e2e)\b"
    r"|(?:npx|pnpm\s+exec|pnpx|bunx)\s+(?:vitest|jest|mocha|tsc|eslint|playwright|cypress|ava|tap|biome|prettier\s+--check)\b"
    r"|(?:vitest|jest|mocha|tsc|eslint|biome|karma|ava)\b"
    r"|cargo\s+(?:test|check|build|clippy|nextest)\b"
    r"|go\s+(?:test|vet|build)\b"
    r"|make\s+(?:test|tests|check|lint|build|ci|verify)\b"
    r"|(?:\./)?(?:scripts/)?run_tests(?:\.sh|\.py)?\b"
    r"|dotnet\s+(?:test|build)\b"
    r"|(?:\./)?gradlew?\s+(?:test|check|build)\b"
    r"|mvn\s+(?:test|verify|package|install)\b"
    r"|(?:bundle\s+exec\s+)?(?:rspec|rake\s+test|rubocop)\b"
    r"|(?:phpunit|pest|composer\s+test)\b"
    r"|(?:mix|swift|deno|elixir|flutter|dart|stack|cabal|sbt)\s+test\b"
    r"|zig\s+(?:test|build)\b|ctest\b"
    r")",
    re.IGNORECASE,
)

_RUNNER_TOOLS = frozenset({"terminal"})


def find_completion_claim(final_response: str) -> Optional[str]:
    """Return the first sentence that asserts a check passed, else ``None``."""
    text = (final_response or "").strip()
    if not text:
        return None
    text = _FENCE_RE.sub(" ", text)
    for raw in _SENTENCE_SPLIT_RE.split(text):
        sentence = raw.strip()
        if not sentence or len(sentence) > 600:
            continue
        if _NOT_A_CLAIM.search(sentence):
            continue
        for pattern in _CLAIM_PATTERNS:
            if pattern.search(sentence):
                return sentence[:_MAX_CLAIM_CHARS]
    return None


def is_runner_command(command: str) -> bool:
    """Whether a shell command runs a test / lint / typecheck / build step."""
    if not command or not isinstance(command, str):
        return False
    for raw in _SEGMENT_SPLIT_RE.split(command.strip()):
        segment = raw.strip()
        if not segment:
            continue
        for _ in range(8):
            stripped = _ENV_ASSIGN_RE.sub("", segment, count=1)
            stripped = _WRAPPER_RE.sub("", stripped, count=1)
            if stripped == segment:
                break
            segment = stripped
        if _RUNNER_HEAD_RE.match(segment):
            return True
    return False


def _message_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for part in content:
            if isinstance(part, dict):
                parts.append(str(part.get("text") or part.get("content") or ""))
        return "\n".join(parts)
    return ""


def _parse_json_object(text: str) -> Optional[dict]:
    text = (text or "").strip()
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except (TypeError, ValueError):
        return None
    return obj if isinstance(obj, dict) else None


def _tool_call_items(message: dict) -> Iterable[tuple[str, str, dict]]:
    """Yield ``(call_id, tool_name, args)`` for an assistant message."""
    calls = message.get("tool_calls")
    if not isinstance(calls, list):
        return
    for call in calls:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        name = str(fn.get("name") or call.get("name") or "")
        raw_args = fn.get("arguments", call.get("arguments"))
        args: dict = {}
        if isinstance(raw_args, dict):
            args = raw_args
        elif isinstance(raw_args, str):
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    args = parsed
            except (TypeError, ValueError):
                args = {}
        yield str(call.get("id") or ""), name, args


def turn_start_index(messages: list) -> int:
    """Index of the last human user message in *messages* (0 when unknown)."""
    try:
        from agent.conversation_compression import _is_real_user_message
    except Exception:  # pragma: no cover - defensive import guard
        _is_real_user_message = lambda m: isinstance(m, dict) and m.get("role") == "user"  # noqa: E731
    for idx in range(len(messages) - 1, -1, -1):
        if _is_real_user_message(messages[idx]):
            return idx
    return 0


def turn_evidence(messages: list, start: Optional[int] = None) -> dict[str, Any]:
    """Summarize what this turn actually ran.

    Returns ``{"tool_calls": int, "runner_passed": int, "runner_failed": int,
    "ledger_passed": bool, "runner_commands": [...]}``. A runner run counts as
    passed when its foreground result reports ``exit_code == 0``; background
    launches (a ``pid`` in the result) never count. ``ledger_passed`` is set
    when any tool result carries a ``passed`` verification-evidence record.
    """
    if start is None:
        start = turn_start_index(messages)
    summary: dict[str, Any] = {
        "tool_calls": 0,
        "runner_passed": 0,
        "runner_failed": 0,
        "ledger_passed": False,
        "runner_commands": [],
    }
    pending: dict[str, tuple[str, dict]] = {}
    for message in messages[start:]:
        if not isinstance(message, dict):
            continue
        role = message.get("role")
        if role == "assistant":
            for call_id, name, args in _tool_call_items(message):
                summary["tool_calls"] += 1
                if call_id:
                    pending[call_id] = (name, args)
            continue
        if role != "tool":
            continue
        call_id = str(message.get("tool_call_id") or "")
        name, args = pending.pop(call_id, ("", {}))
        result = _parse_json_object(_message_text(message.get("content")))
        if result is None:
            continue
        evidence = result.get("verification_evidence")
        if isinstance(evidence, dict) and str(evidence.get("status") or "") == "passed":
            summary["ledger_passed"] = True
        if name not in _RUNNER_TOOLS:
            continue
        command = str(args.get("command") or "")
        if not is_runner_command(command):
            continue
        if "pid" in result:
            continue  # background launch — nothing finished yet
        summary["runner_commands"].append(command[:120])
        exit_code = result.get("exit_code")
        if exit_code == 0 and not result.get("error"):
            summary["runner_passed"] += 1
        else:
            summary["runner_failed"] += 1
    return summary


def build_evidence_claim_nudge(final_response: str, messages: list) -> Optional[str]:
    """Return the synthetic follow-up when a completion claim has no evidence.

    ``None`` when the answer makes no such claim, when the turn used no tools
    at all (a plain conversational answer is not a work report), or when a
    test/lint/typecheck/build command succeeded in this turn.
    """
    claim = find_completion_claim(final_response)
    if not claim:
        return None
    evidence = turn_evidence(messages)
    if evidence["tool_calls"] == 0:
        return None
    if evidence["runner_passed"] > 0 or evidence["ledger_passed"]:
        return None
    if evidence["runner_failed"] > 0:
        ran = evidence["runner_commands"][-1]
        situation = (
            f"the only such command that ran in this turn (`{ran}`) did not exit "
            "successfully"
        )
    else:
        situation = "no test, lint, type-check or build command ran in this turn"
    return (
        "[System: Your answer states \"" + claim.replace('"', "'") + "\", but "
        + situation
        + ". Robo reports only what it has evidence for. Either run the "
        "relevant check now and report its real output, or rewrite that part "
        "of the answer to say exactly what you did and did not verify. Do not "
        "present an unverified result as verified.]"
    )


__all__ = [
    "build_evidence_claim_nudge",
    "evidence_claims_active",
    "find_completion_claim",
    "is_runner_command",
    "judgment_enabled",
    "on_messaging_surface",
    "read_before_edit_message",
    "turn_evidence",
    "turn_start_index",
]
