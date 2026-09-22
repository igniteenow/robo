"""Every place that reports the product version must agree.

``robo_cli.__version__`` is what ``robo --version``, the dashboard ``/version``
probe and provider User-Agents print; ``ROBO_VERSION`` (repo root) and
``robo_runtime.version.ROBO_VERSION`` are what the release checklist bumps.
They drifted once (0.20.0 vs 3.0.0-alpha.5) — keep them pinned together.
"""

from pathlib import Path

import robo_cli
from robo_runtime.version import ROBO_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_runtime_and_cli_versions_agree():
    assert robo_cli.__version__ == ROBO_VERSION


def test_robo_version_file_matches_runtime():
    assert (ROOT / "ROBO_VERSION").read_text().strip() == ROBO_VERSION


def test_pyproject_version_is_pep440_form_of_runtime_version():
    import re

    text = (ROOT / "pyproject.toml").read_text()
    m = re.search(r'^version\s*=\s*"([^"]+)"', text, re.M)
    assert m, "pyproject.toml has no version"
    # 3.0.0-alpha.5 (semver, ROBO_VERSION/package.json) <-> 3.0.0a5 (PEP 440)
    pep440 = re.sub(r"-alpha\.(\d+)$", r"a\1", ROBO_VERSION)
    pep440 = re.sub(r"-beta\.(\d+)$", r"b\1", pep440)
    pep440 = re.sub(r"-rc\.(\d+)$", r"rc\1", pep440)
    assert m.group(1) == pep440


def test_root_package_json_version_matches_runtime():
    import json

    pkg = json.loads((ROOT / "package.json").read_text())
    assert pkg["version"] == ROBO_VERSION
