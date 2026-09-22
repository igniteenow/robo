"""Regression tests for local terminal initial cwd normalization."""

from pathlib import Path

from tools.environments.local import LocalEnvironment, _resolve_local_initial_cwd


def test_relative_initial_cwd_resolves_from_parent(tmp_path, monkeypatch):
    project = tmp_path / "robo-engineer"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    assert _resolve_local_initial_cwd("robo-engineer") == str(project)


def test_local_environment_keeps_existing_relative_child_cwd(tmp_path, monkeypatch):
    project = tmp_path / "robo-engineer"
    project.mkdir()
    monkeypatch.chdir(tmp_path)

    env = LocalEnvironment(cwd="robo-engineer", timeout=5)
    try:
        result = env.execute("pwd", timeout=5)
    finally:
        env.cleanup()

    assert result["returncode"] == 0
    assert result["output"].strip() == str(project)
