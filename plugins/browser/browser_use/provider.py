"""Browser Use cloud browser provider — plugin form.

Subclasses :class:`agent.browser_provider.BrowserProvider` (the plugin-facing
ABC introduced in PR #25214). The legacy in-tree module
``tools.browser_providers.browser_use`` was removed in the same PR; this file
is now the canonical implementation.

Config keys this provider responds to::

    browser:
      cloud_provider: "browser-use"   # explicit selection

Auth env vars::

    BROWSER_USE_API_KEY=...           # https://browser-use.com
"""

from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, Optional

import requests

from agent.browser_provider import BrowserProvider
from agent.secret_scope import get_secret

logger = logging.getLogger(__name__)

_BASE_URL = "https://api.browser-use.com/api/v3"


class BrowserUseBrowserProvider(BrowserProvider):
    """Browser Use (https://browser-use.com) cloud browser backend.

    Requires a direct BROWSER_USE_API_KEY.
    """

    @property
    def name(self) -> str:
        return "browser-use"

    @property
    def display_name(self) -> str:
        return "Browser Use"

    def is_available(self) -> bool:
        return self._get_config_or_none() is not None

    # ------------------------------------------------------------------
    # Config resolution
    # ------------------------------------------------------------------

    def _get_config_or_none(self) -> Optional[Dict[str, Any]]:
        api_key = get_secret("BROWSER_USE_API_KEY")
        if not api_key:
            return None
        return {
            "api_key": api_key,
            "base_url": _BASE_URL,
        }

    def _get_config(self) -> Dict[str, Any]:
        config = self._get_config_or_none()
        if config is None:
            raise ValueError(
                "Browser Use requires a direct BROWSER_USE_API_KEY credential."
            )
        return config

    # ------------------------------------------------------------------
    # Session lifecycle
    # ------------------------------------------------------------------

    def _headers(self, config: Dict[str, Any]) -> Dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Browser-Use-API-Key": config["api_key"],
        }

    def create_session(self, task_id: str) -> Dict[str, object]:
        config = self._get_config()

        headers = self._headers(config)

        try:
            response = requests.post(
                f"{config['base_url']}/browsers",
                headers=headers,
                json={},
                timeout=30,
            )
        except requests.RequestException as exc:
            raise RuntimeError(
                f"Browser Use API connection failed: {exc}"
            ) from exc

        if not response.ok:
            raise RuntimeError(
                f"Failed to create Browser Use session: "
                f"{response.status_code} {response.text}"
            )

        session_data = response.json()
        session_name = f"robo_{task_id}_{uuid.uuid4().hex[:8]}"
        external_call_id = None

        logger.info("Created Browser Use session %s", session_name)

        cdp_url = session_data.get("cdpUrl") or session_data.get("connectUrl") or ""

        return {
            "session_name": session_name,
            "bb_session_id": session_data["id"],
            "cdp_url": cdp_url,
            # Browser Use sessions have a fixed server-side lifetime. Preserve
            # the authority returned by the API so the dispatcher can retire an
            # expired CDP endpoint instead of reconnecting to it indefinitely.
            "expires_at": session_data.get("timeoutAt"),
            "features": {"browser_use": True},
            "external_call_id": external_call_id,
        }

    def close_session(self, session_id: str) -> bool:
        try:
            config = self._get_config()
        except ValueError:
            logger.warning(
                "Cannot close Browser Use session %s — missing credentials", session_id
            )
            return False

        try:
            response = requests.patch(
                f"{config['base_url']}/browsers/{session_id}",
                headers=self._headers(config),
                json={"action": "stop"},
                timeout=10,
            )
            if response.status_code in {200, 201, 204}:
                logger.debug("Successfully closed Browser Use session %s", session_id)
                return True
            else:
                logger.warning(
                    "Failed to close Browser Use session %s: HTTP %s - %s",
                    session_id,
                    response.status_code,
                    response.text[:200],
                )
                return False
        except Exception as e:
            logger.error("Exception closing Browser Use session %s: %s", session_id, e)
            return False

    def emergency_cleanup(self, session_id: str) -> None:
        config = self._get_config_or_none()
        if config is None:
            logger.warning(
                "Cannot emergency-cleanup Browser Use session %s — missing credentials",
                session_id,
            )
            return
        try:
            requests.patch(
                f"{config['base_url']}/browsers/{session_id}",
                headers=self._headers(config),
                json={"action": "stop"},
                timeout=5,
            )
        except Exception as e:
            logger.debug(
                "Emergency cleanup failed for Browser Use session %s: %s", session_id, e
            )

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "Browser Use",
            "badge": "paid",
            "tag": "Cloud browser with remote execution",
            "env_vars": [
                {
                    "key": "BROWSER_USE_API_KEY",
                    "prompt": "Browser Use API key",
                    "url": "https://browser-use.com",
                },
            ],
            # Cloud-scoped hook: installs the agent-browser CLI only (no
            # local Chromium — Browser Use hosts the browser).
            "post_setup": "browserbase",
        }
