from __future__ import annotations

from robo_cli._parser import build_top_level_parser


def test_robo_environment_brands_top_level_help(monkeypatch) -> None:
    monkeypatch.setenv("ROBO_CLI_NAME", "robo")
    monkeypatch.setenv("ROBO_PRODUCT_NAME", "Robo")

    parser, _, _ = build_top_level_parser()
    help_text = parser.format_help()

    assert help_text.startswith("usage: robo")
    assert "Robo — autonomous engineering runtime (Ignitee Now)" in help_text
    assert "robo model" in help_text
