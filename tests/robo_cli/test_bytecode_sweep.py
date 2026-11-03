"""Tests for the launch-time stale-bytecode sweep (checkout fingerprint guard).

Bug class: the checkout's ``.py`` files change (``robo update``, manual
``git pull``, ZIP update) while ``__pycache__`` retains bytecode compiled
from the previous revision; the next process to import trusts the stale
``.pyc`` and dies with ``cannot import name ...`` (#6207, #60242).

The launch-time guard compares the current checkout fingerprint against the
last-validated stamp and sweeps ``__pycache__`` once when they diverge —
covering paths no update-time clear can reach (manual pulls, pre-hardening
updaters).
"""

from pathlib import Path

from robo_cli import main as robo_main


def _make_repo(tmp_path: Path, sha: str = "a" * 40) -> Path:
    """Minimal git checkout layout that _read_git_revision_fingerprint groks."""
    repo = tmp_path / "repo"
    git_dir = repo / ".git"
    (git_dir / "refs" / "heads").mkdir(parents=True)
    (git_dir / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (git_dir / "refs" / "heads" / "main").write_text(sha + "\n", encoding="utf-8")
    return repo


def _make_pycache(repo: Path, subdir: str = "robo_cli") -> Path:
    cache = repo / subdir / "__pycache__"
    cache.mkdir(parents=True)
    (cache / "main.cpython-311.pyc").write_bytes(b"stale")
    return cache


def test_sweep_clears_pycache_when_checkout_changed(monkeypatch, tmp_path):
    repo = _make_repo(tmp_path, sha="b" * 40)
    cache = _make_pycache(repo)
    monkeypatch.setattr(robo_main, "PROJECT_ROOT", repo)
    # Stamp records a different (older) fingerprint.
    (repo / robo_main._BYTECODE_FINGERPRINT_FILE).write_text(
        "git:refs/heads/main:" + "a" * 40, encoding="utf-8"
    )

    robo_main._sweep_stale_bytecode_if_checkout_changed()

    assert not cache.exists()
    # Stamp updated to the current fingerprint.
    recorded = (repo / robo_main._BYTECODE_FINGERPRINT_FILE).read_text(encoding="utf-8")
    assert recorded.strip().endswith("b" * 40)

# ---------------------------------------------------------------------------
# The managed runtime store is not the checkout's source
# ---------------------------------------------------------------------------

def test_clear_leaves_the_managed_runtime_store_alone(tmp_path):
    repo = _make_repo(tmp_path)
    own = _make_pycache(repo)
    stdlib = _make_pycache(repo, ".robo-runtime/python/generation-1/Lib/asyncio")
    venv = _make_pycache(repo, "venv/Lib/site-packages/yaml")

    removed = robo_main._clear_bytecode_cache(repo)

    assert removed == 1
    assert not own.exists()
    assert stdlib.exists()
    assert venv.exists()


# ---------------------------------------------------------------------------
# Post-update precompile: the first launch after an update must not compile
# ---------------------------------------------------------------------------

def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def _has_bytecode(source: Path) -> bool:
    cache = source.parent / "__pycache__"
    return cache.is_dir() and any(p.name.startswith(source.stem + ".") for p in cache.iterdir())


def test_precompile_builds_the_checkout_and_skips_what_the_sweep_skips(tmp_path):
    import sys

    repo = _make_repo(tmp_path)
    own = _write(repo / "robo_cli" / "thing.py", "VALUE = 1\n")
    top = _write(repo / "run_agent.py", "X = 2\n")
    test = _write(repo / "tests" / "test_thing.py", "def test_x():\n    pass\n")
    runtime = _write(repo / ".robo-runtime" / "python" / "lib" / "mod.py", "Y = 3\n")
    venv = _write(repo / "venv" / "lib" / "pkg.py", "Z = 4\n")
    node = _write(repo / "web" / "node_modules" / "gyp" / "x.py", "W = 5\n")

    assert robo_main._precompile_bytecode(repo, python=sys.executable) is True

    assert _has_bytecode(own)
    assert _has_bytecode(top)
    for skipped in (test, runtime, venv, node):
        assert not _has_bytecode(skipped), skipped


def test_precompile_works_for_a_checkout_under_a_folder_named_like_a_skipped_one(tmp_path):
    import sys

    repo = _make_repo(tmp_path / "tests" / ".venv")
    own = _write(repo / "robo_cli" / "thing.py", "VALUE = 1\n")

    assert robo_main._precompile_bytecode(repo, python=sys.executable) is True
    assert _has_bytecode(own)


def test_precompile_still_builds_the_rest_when_one_file_is_broken(tmp_path):
    import sys

    repo = _make_repo(tmp_path)
    good = _write(repo / "agent" / "good.py", "A = 1\n")
    _write(repo / "skills" / "old" / "py2.py", "print 'no'\n")

    assert robo_main._precompile_bytecode(repo, python=sys.executable) is False
    assert _has_bytecode(good)


def test_precompile_never_raises_without_an_interpreter(tmp_path):
    repo = _make_repo(tmp_path)
    _write(repo / "robo_cli" / "thing.py", "VALUE = 1\n")

    assert robo_main._precompile_bytecode(repo, python=str(tmp_path / "no-python")) is False


def test_update_precompiles_with_the_checkout_venv_python(monkeypatch, tmp_path, capsys):
    from robo_cli import update_cmd
    from robo_constants import venv_python_path

    repo = _make_repo(tmp_path)
    venv_dir = repo / "venv"
    python = venv_python_path(venv_dir)
    _write(python, "")
    calls = []
    monkeypatch.setattr(robo_main, "PROJECT_ROOT", repo)
    monkeypatch.setattr(robo_main, "_project_venv_dir", lambda: venv_dir)
    monkeypatch.setattr(
        robo_main, "_precompile_bytecode", lambda root, python=None: calls.append((root, python)) or True
    )

    update_cmd._precompile_after_update()

    assert calls == [(repo, str(python))]
    assert "Python files prepared" in capsys.readouterr().out


def test_update_carries_on_when_the_precompile_fails(monkeypatch, tmp_path):
    from robo_cli import update_cmd

    repo = _make_repo(tmp_path)
    monkeypatch.setattr(robo_main, "PROJECT_ROOT", repo)
    monkeypatch.setattr(robo_main, "_project_venv_dir", lambda: repo / "venv")

    def boom(root, python=None):
        raise RuntimeError("disk full")

    monkeypatch.setattr(robo_main, "_precompile_bytecode", boom)

    update_cmd._precompile_after_update()  # must not raise


# ---------------------------------------------------------------------------
# Plugin-update sibling site: __pycache__ under ~/.robo/plugins/<name>
# ---------------------------------------------------------------------------

def test_clear_plugin_bytecode_removes_nested_caches(tmp_path):
    from robo_cli import plugins_cmd

    plugin = tmp_path / "myplugin"
    top = plugin / "__pycache__"
    nested = plugin / "sub" / "__pycache__"
    top.mkdir(parents=True)
    nested.mkdir(parents=True)
    (top / "a.pyc").write_bytes(b"stale")
    (nested / "b.pyc").write_bytes(b"stale")

    removed = plugins_cmd._clear_plugin_bytecode(plugin)

    assert removed == 2
    assert not top.exists()
    assert not nested.exists()


