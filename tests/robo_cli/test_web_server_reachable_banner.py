"""The startup banner names URLs a person can actually type on another machine.

``--host 0.0.0.0`` binds every interface, but "http://0.0.0.0:9119" is not an
address anyone can open from a phone or a second PC. Under an all-interfaces
bind the banner lists this machine's LAN addresses and says where each URL
goes (browser vs. the desktop app's Remote gateway setting). Loopback and
specific-address binds print nothing extra — the bind line already says it.
"""

from unittest.mock import patch

from robo_cli import web_server


def test_loopback_bind_adds_nothing():
    assert web_server._reachable_address_lines("127.0.0.1", 9119, headless=False) == []
    assert web_server._reachable_address_lines("192.168.1.20", 9119, headless=True) == []


def test_all_interfaces_bind_lists_lan_urls_for_the_dashboard():
    with patch.object(web_server, "_lan_addresses", return_value=["192.168.1.20", "100.64.0.7"]):
        lines = web_server._reachable_address_lines("0.0.0.0", 9119, headless=False)

    assert "http://192.168.1.20:9119" in "\n".join(lines)
    assert "http://100.64.0.7:9119" in "\n".join(lines)
    assert any("Browser" in line and "Remote gateway" in line for line in lines)


def test_headless_serve_points_at_the_desktop_setting_only():
    with patch.object(web_server, "_lan_addresses", return_value=["10.0.0.5"]):
        lines = web_server._reachable_address_lines("::", 8080, headless=True)

    joined = "\n".join(lines)
    assert "http://10.0.0.5:8080" in joined
    assert "Remote gateway" in joined
    assert "Browser" not in joined


def test_no_addresses_means_no_hint():
    with patch.object(web_server, "_lan_addresses", return_value=[]):
        assert web_server._reachable_address_lines("0.0.0.0", 9119, headless=False) == []


def test_lan_addresses_never_raises_and_skips_loopback():
    addrs = web_server._lan_addresses()

    assert isinstance(addrs, list)
    assert all(not a.startswith("127.") for a in addrs)
