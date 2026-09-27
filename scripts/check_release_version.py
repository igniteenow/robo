#!/usr/bin/env python3
"""Check that a release tag matches the version written in the code.

Usage: scripts/check_release_version.py v3.0.2 [--root DIR]

The version lives in four files, and each is read by something different:
pyproject.toml (the Python package), robo_runtime/version.py (`robo --version`),
package.json and apps/desktop/package.json (the desktop app's About screen).
A release tagged v3.0.2 while any of them still says 3.0.1 would publish one
version under another's name, so the release workflow runs this first.
Exits 0 when every file agrees with the tag, 1 otherwise, naming each mismatch.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

TAG = re.compile(r"^v(\d+\.\d+\.\d+(?:\.\d+)?)$")
RUNTIME_VERSION = re.compile(r'^ROBO_VERSION\s*=\s*"([^"]+)"', re.MULTILINE)


def versions_in_code(root: Path) -> dict[str, str | None]:
    """The version each file declares, or None when it can't be read."""
    found: dict[str, str | None] = {}

    try:
        found["pyproject.toml"] = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]["version"]
    except (OSError, KeyError, tomllib.TOMLDecodeError):
        found["pyproject.toml"] = None

    try:
        match = RUNTIME_VERSION.search((root / "robo_runtime" / "version.py").read_text(encoding="utf-8"))
        found["robo_runtime/version.py"] = match.group(1) if match else None
    except OSError:
        found["robo_runtime/version.py"] = None

    for name in ("package.json", "apps/desktop/package.json"):
        try:
            found[name] = json.loads((root / name).read_text(encoding="utf-8")).get("version")
        except (OSError, ValueError):
            found[name] = None

    return found


def mismatches(tag: str, root: Path) -> list[str]:
    """Human-readable problems with releasing *tag* from *root*; empty when fine."""
    match = TAG.match(tag)
    if not match:
        return [f"{tag!r} is not a release tag; use v<major>.<minor>.<patch>, e.g. v3.0.2"]
    wanted = match.group(1)
    return [
        f"{name} says {found or 'nothing readable'}, the tag says {wanted}"
        for name, found in versions_in_code(root).items()
        if found != wanted
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("tag")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args(argv)

    problems = mismatches(args.tag, args.root)
    for problem in problems:
        print(f"✗ {problem}", file=sys.stderr)
    if problems:
        print("Bump every file above to the tag's version, merge that, then tag again.", file=sys.stderr)
        return 1
    print(f"✓ {args.tag} matches the version in the code")
    return 0


if __name__ == "__main__":
    sys.exit(main())
