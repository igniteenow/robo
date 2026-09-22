from pathlib import Path
from unittest.mock import MagicMock


def test_default_config_exposes_vacuum_interval():
    from robo_cli.config import DEFAULT_CONFIG

    assert DEFAULT_CONFIG["sessions"]["min_vacuum_interval_days"] == 30


def test_cli_auto_maintenance_forwards_vacuum_interval(monkeypatch, tmp_path: Path):
    import cli
    import robo_cli.config
    import robo_constants

    session_db = MagicMock()
    session_db.get_meta.return_value = "already-done"
    monkeypatch.setattr(
        robo_cli.config,
        "load_config",
        lambda: {
            "sessions": {
                "auto_prune": True,
                "retention_days": 90,
                "vacuum_after_prune": True,
                "min_interval_hours": 24,
                "min_vacuum_interval_days": 17,
            }
        },
    )
    monkeypatch.setattr(robo_constants, "get_robo_home", lambda: tmp_path)

    cli._run_state_db_auto_maintenance(session_db)

    session_db.maybe_auto_prune_and_vacuum.assert_called_once_with(
        retention_days=90,
        min_interval_hours=24,
        min_vacuum_interval_days=17,
        vacuum=True,
        sessions_dir=tmp_path / "sessions",
    )
