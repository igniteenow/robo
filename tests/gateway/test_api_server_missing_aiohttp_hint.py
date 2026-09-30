"""`robo gateway` with API_SERVER_KEY set but no aiohttp says how to install it.

The install-robo.* installers don't add the messaging extras, which is where
aiohttp comes from, so a user following the README's HTTP API steps got a bare
"aiohttp not installed" and no API. The warning now names the command, for the
Python the gateway runs on.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace

import gateway.platforms.api_server as api_server_mod
from gateway.config import Platform, PlatformConfig
from gateway.run import GatewayRunner


def test_missing_aiohttp_warning_names_the_install_command(monkeypatch, caplog):
    monkeypatch.setattr(api_server_mod, "check_api_server_requirements", lambda: False)
    runner = object.__new__(GatewayRunner)
    runner.config = SimpleNamespace(group_sessions_per_user=True, thread_sessions_per_user=False)

    with caplog.at_level(logging.WARNING, logger="gateway.run"):
        adapter = runner._create_adapter(Platform.API_SERVER, PlatformConfig())

    assert adapter is None
    text = "\n".join(r.getMessage() for r in caplog.records)
    assert "aiohttp is not installed" in text
    assert "-m pip install" in text
    assert "aiohttp>=3.14.3,<4" in text
