from __future__ import annotations

import hashlib
from pathlib import Path

import yaml

from robo_runtime.bootstrap import bootstrap_robo_home, resolve_robo_home


def test_resolve_robo_home_defaults_to_dot_robo(tmp_path: Path) -> None:
    assert resolve_robo_home({}, user_home=tmp_path) == (tmp_path / ".robo").resolve()


def test_resolve_robo_home_honors_override(tmp_path: Path) -> None:
    expected = (tmp_path / "robot-data").resolve()
    assert resolve_robo_home({"ROBO_HOME": str(expected)}) == expected


def test_bootstrap_seeds_valid_config_and_assets(tmp_path: Path) -> None:
    home = bootstrap_robo_home(tmp_path / "home")
    config = yaml.safe_load((home / "config.yaml").read_text(encoding="utf-8"))

    assert config["display"]["interface"] == "tui"
    assert config["display"]["skin"] == "robo"
    assert config["agent"]["intent_ack_continuation"] is True
    assert config["terminal"]["timeout"] == 21600
    assert config["approvals"]["mode"] == "smart"
    assert config["security"]["allow_private_urls"] is True
    # Phonetic on purpose: for the open-vocabulary engine this text IS what is
    # detected, and "roh boh" tokenises better than "robo".
    assert config["wake_word"]["phrase"] == "hey roh boh"

    face = home / "assets" / "face" / "cute-face.html"
    onnx = home / "assets" / "wake_word" / "hey_roh_boh.onnx"
    tflite = home / "assets" / "wake_word" / "hey_roh_boh.tflite"
    assert face.stat().st_size > 10_000
    assert "cdnjs.cloudflare.com" not in face.read_text(encoding="utf-8")
    assert (home / "assets" / "face" / "three.r128.min.js").stat().st_size > 500_000
    assert hashlib.sha256(onnx.read_bytes()).hexdigest() == (
        "ca54d37ac3f7a7479e8166df08645bac34a39a42a6bf1bee81fb0652e2d4461a"
    )
    assert hashlib.sha256(tflite.read_bytes()).hexdigest() == (
        "c37eac295ea7a62bb0c31a77631712be01b7869ead5b6f5f04b458ffa01910f6"
    )


def test_bootstrap_never_overwrites_operator_files(tmp_path: Path) -> None:
    home = tmp_path / "home"
    home.mkdir()
    (home / "config.yaml").write_text("operator: true\n", encoding="utf-8")
    (home / "SOUL.md").write_text("my robot\n", encoding="utf-8")

    bootstrap_robo_home(home)

    assert (home / "config.yaml").read_text(encoding="utf-8") == "operator: true\n"
    assert (home / "SOUL.md").read_text(encoding="utf-8") == "my robot\n"
