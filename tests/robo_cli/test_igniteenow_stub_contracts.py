"""The fork's Ignitee Now stubs must keep the return SHAPES their callers expect.

``apply_igniteenow_managed_defaults`` returned ``False`` in the first fork
stub; ``robo tools`` (and therefore the first-run setup wizard) iterates its
result, so every fresh install crashed with ``TypeError: 'bool' object is not
iterable`` right after tool selection.
"""
from robo_cli import igniteenow_subscription as sub


def test_apply_managed_defaults_returns_an_iterable_set():
    result = sub.apply_igniteenow_managed_defaults({}, enabled_toolsets={"web"}, force_fresh=True)
    assert isinstance(result, set) and result == set()
    assert sorted(result) == []          # the exact expression tools_command uses
    assert "web" not in result


def test_other_stubs_keep_their_shapes():
    assert sub.ensure_igniteenow_portal_access(capability="x") is False
    assert sub.prompt_enable_tool_gateway() is None
    feats = sub.get_igniteenow_subscription_features({})
    assert hasattr(feats, "features") and hasattr(feats, "account_info")
    assert isinstance(sub.MANAGED_FEATURE_COVERAGE_CATEGORY, dict)
