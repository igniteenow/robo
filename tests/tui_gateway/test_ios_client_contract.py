"""Wire contract between the Robo iOS app (apps/ios) and the gateway.

The Swift client (GatewayClient.swift) calls a fixed set of JSON-RPC methods
and consumes a fixed set of events. This test pins that set on the Python
side so a rename here fails CI instead of breaking phones in the field.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLIENT = ROOT / "apps" / "ios" / "Robo" / "GatewayClient.swift"

METHODS = ["session.create", "session.list", "session.resume", "session.interrupt", "prompt.submit", "approval.respond"]
EVENTS = ["message.start", "message.delta", "message.complete", "reasoning.delta", "tool.start", "tool.complete",
          "status.update", "approval.request", "message.user", "session.info"]


def _gateway_methods() -> set:
    names = set()
    for f in (ROOT / "tui_gateway").glob("methods_*.py"):
        names |= set(re.findall(r'@method\("([a-z_.]+)"\)', f.read_text(encoding="utf-8")))
    return names


def test_every_method_the_ios_client_calls_exists():
    have = _gateway_methods()
    missing = [m for m in METHODS if m not in have]
    assert not missing, f"gateway lacks methods the iOS client calls: {missing}"


def test_every_event_the_ios_client_consumes_is_emitted():
    src = "\n".join(p.read_text(encoding="utf-8") for p in [ROOT / "tui_gateway" / "server.py", ROOT / "tui_gateway" / "methods_prompt.py"])
    missing = [e for e in EVENTS if f'"{e}"' not in src]
    assert not missing, f"gateway never emits events the iOS client handles: {missing}"


def test_swift_client_and_python_agree():
    swift = CLIENT.read_text(encoding="utf-8")
    for m in METHODS:
        assert f'"{m}"' in swift, f"Swift client does not call {m}"
    for e in EVENTS:
        assert f'"{e}"' in swift, f"Swift client does not parse {e}"


def test_pairing_string_shape():
    from urllib.parse import parse_qs, urlparse
    s = "robo://pair?url=https%3A%2F%2Frobo.example.com%3A8642&token=abc"
    u = urlparse(s)
    assert u.scheme == "robo" and u.netloc == "pair"
    q = parse_qs(u.query)
    assert q["url"] == ["https://robo.example.com:8642"] and q["token"] == ["abc"]


def test_serve_pair_flag_registered():
    src = (ROOT / "robo_cli" / "subcommands" / "dashboard.py").read_text(encoding="utf-8")
    assert '"--pair"' in src
    assert "_print_mobile_pairing" in (ROOT / "robo_cli" / "main.py").read_text(encoding="utf-8")


def test_approval_choices_match_gateway():
    """The sheet sends once / session / deny — the values approval.respond accepts."""
    src = (ROOT / "tools" / "approval.py").read_text(encoding="utf-8")
    for choice in ("once", "session", "deny"):
        assert f'"{choice}"' in src
