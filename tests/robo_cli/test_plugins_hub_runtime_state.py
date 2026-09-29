"""The Plugins page reports what the runtime loader actually does.

Before: status came only from ``plugins.enabled``/``plugins.disabled``, so the
active LLM provider (e.g. ``deepseek-provider``) and every built-in backend or
channel adapter showed "inactive", Enable/Disable on a provider did nothing,
and same-named plugins (``image_gen/fal`` / ``video_gen/fal``) toggled together.
These tests use the real bundled plugin tree and an isolated ROBO_HOME.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from robo_cli import plugins_cmd, web_server


def _rows():
    web_server._invalidate_plugins_hub_cache()
    payload = web_server._merged_plugins_hub(force_refresh=True)
    return payload["plugins"]


def _row(rows, *, key=None, name=None):
    for row in rows:
        if (key is not None and row["key"] == key) or (name is not None and row["name"] == name):
            return row
    raise AssertionError(f"no row for key={key} name={name}")


def _set_lists(enabled=(), disabled=()):
    plugins_cmd._save_enabled_set(set(enabled))
    plugins_cmd._save_disabled_set(set(disabled))


@pytest.fixture(autouse=True)
def _clean(_isolate_robo_home):
    _set_lists()
    yield
    web_server._invalidate_plugins_hub_cache()


def test_every_row_says_how_the_loader_treats_it():
    rows = _rows()
    assert rows
    for row in rows:
        assert row["kind"] in {"model-provider", "backend", "platform", "standalone", "exclusive"}
        assert row["key"]
        assert isinstance(row["always_on"], bool)
        assert isinstance(row["toggleable"], bool)
    # Keys are unique even where manifest names collide.
    keys = [r["key"] for r in rows]
    assert len(keys) == len(set(keys))


def test_llm_provider_plugins_are_active_and_not_toggleable():
    providers = [r for r in _rows() if r["kind"] == "model-provider" and r["source"] == "bundled"]
    assert providers
    for row in providers:
        assert row["runtime_status"] == "enabled"
        assert row["always_on"] is True
        assert row["toggleable"] is False


def test_provider_listed_as_disabled_still_reports_active():
    # providers/ discovery ignores plugins.disabled, so claiming "disabled"
    # would be false.
    rows = _rows()
    provider = next(r for r in rows if r["kind"] == "model-provider")
    _set_lists(disabled={provider["name"], provider["key"]})
    assert _row(_rows(), key=provider["key"])["runtime_status"] == "enabled"


def test_builtin_backends_and_channels_are_active_until_disabled():
    rows = _rows()
    builtin = [r for r in rows if r["source"] == "bundled" and r["kind"] in {"backend", "platform"}]
    assert builtin
    for row in builtin:
        assert row["runtime_status"] == "enabled", row["key"]
        assert row["always_on"] is True and row["toggleable"] is True

    target = builtin[0]
    result = plugins_cmd.dashboard_set_agent_plugin_enabled(target["key"], enabled=False)
    assert result["ok"]
    assert _row(_rows(), key=target["key"])["runtime_status"] == "disabled"
    # ...and the runtime loader agrees.
    from robo_cli.plugins import _get_disabled_plugins

    assert target["key"] in _get_disabled_plugins()


def test_channel_adapter_toggles_under_the_key_the_loader_uses():
    rows = _rows()
    platform = next(r for r in rows if r["kind"] == "platform" and r["source"] == "bundled")
    # The loader knows bundled adapters by manifest name, not platforms/<dir>.
    assert platform["key"] == platform["name"]
    assert not platform["key"].startswith("platforms/")


def test_enable_clears_every_alias_the_loader_would_honor():
    rows = _rows()
    platform = next(r for r in rows if r["kind"] == "platform" and r["source"] == "bundled")
    listing_key = next(
        entry[5]
        for entry in plugins_cmd._discover_all_plugins()
        if entry[0] == platform["name"]
    )
    # A CLI `plugins disable` may have written the listing key.
    _set_lists(disabled={platform["name"], listing_key})
    assert _row(_rows(), key=platform["key"])["runtime_status"] == "disabled"

    assert plugins_cmd.dashboard_set_agent_plugin_enabled(platform["key"], enabled=True)["ok"]
    remaining = plugins_cmd._get_disabled_set()
    assert platform["name"] not in remaining and listing_key not in remaining
    assert _row(_rows(), key=platform["key"])["runtime_status"] == "enabled"


def test_same_named_plugins_toggle_independently():
    rows = _rows()
    by_name: dict = {}
    for row in rows:
        by_name.setdefault(row["name"], []).append(row)
    shared = [group for group in by_name.values() if len(group) > 1]
    if not shared:
        pytest.skip("no two bundled plugins share a manifest name")
    first, second = shared[0][:2]
    assert first["key"] != second["key"]

    assert plugins_cmd.dashboard_set_agent_plugin_enabled(first["key"], enabled=False)["ok"]
    rows = _rows()
    assert _row(rows, key=first["key"])["runtime_status"] == "disabled"
    assert _row(rows, key=second["key"])["runtime_status"] != "disabled"


def test_opt_in_plugins_follow_the_enabled_list():
    rows = _rows()
    opt_in = next(
        (r for r in rows if r["kind"] == "standalone" and not r["always_on"]), None
    )
    if opt_in is None:
        pytest.skip("no opt-in plugin available")
    assert opt_in["runtime_status"] == "inactive"
    assert plugins_cmd.dashboard_set_agent_plugin_enabled(opt_in["key"], enabled=True)["ok"]
    assert _row(_rows(), key=opt_in["key"])["runtime_status"] == "enabled"


def test_kind_heuristic_for_manifests_without_kind(tmp_path: Path):
    mp = tmp_path / "mp"
    mp.mkdir()
    (mp / "__init__.py").write_text(
        "from providers import register_provider, ProviderProfile\n"
    )
    assert web_server._effective_plugin_kind(mp, {}) == "model-provider"
    mem = tmp_path / "mem"
    mem.mkdir()
    (mem / "__init__.py").write_text("class X(MemoryProvider): pass\n")
    assert web_server._effective_plugin_kind(mem, {}) == "exclusive"
    plain = tmp_path / "plain"
    plain.mkdir()
    assert web_server._effective_plugin_kind(plain, {}) == "standalone"
    assert web_server._effective_plugin_kind(plain, {"kind": "Backend"}) == "backend"
    assert web_server._effective_plugin_kind(plain, {"kind": "weird"}) == "standalone"


def test_password_login_plugin_cannot_be_disabled_while_in_use():
    from starlette.testclient import TestClient

    from robo_cli.config import load_config, save_config

    cfg = load_config()
    cfg.setdefault("dashboard", {})["basic_auth"] = {
        "username": "admin",
        "password_hash": "x",
        "secret": "s" * 32,
    }
    save_config(cfg)
    client = TestClient(web_server.app)
    client.headers[web_server._SESSION_HEADER_NAME] = web_server._SESSION_TOKEN
    r = client.post("/api/dashboard/agent-plugins/dashboard_auth/basic/disable")
    assert r.status_code == 409
    assert "dashboard_auth/basic" not in plugins_cmd._get_disabled_set()


def test_plugin_dir_removal_handles_read_only_files(tmp_path: Path):
    import os
    import stat

    target = tmp_path / "plugin"
    objects = target / ".git" / "objects" / "ab"
    objects.mkdir(parents=True)
    packed = objects / "cdef"
    packed.write_text("x")
    os.chmod(packed, stat.S_IREAD)
    os.chmod(objects, stat.S_IREAD | stat.S_IEXEC)
    plugins_cmd._rmtree_plugin_dir(target)
    assert not target.exists()
