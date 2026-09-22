"""The dashboard's UI kit must be Ignitee Now's own workspace package.
Copyright (c) 2026 Ignitee Now.

Guards against a registry alias or a third-party package being reintroduced
under the ``@igniteenow/ui`` name (for example by an upstream merge)."""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KIT = "@igniteenow/ui"


def _load(rel):
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_the_kit_is_a_workspace_package_with_no_runtime_dependencies():
    manifest = _load("packages/ui/package.json")
    assert manifest["name"] == KIT
    assert manifest.get("author") == "Ignitee Now"
    assert not manifest.get("dependencies"), "the kit must depend on nothing but its React peer"
    assert "packages/*" in _load("package.json")["workspaces"]
    assert "Ignitee Now" in (ROOT / "packages/ui/LICENSE").read_text(encoding="utf-8")


def test_no_manifest_aliases_the_kit_to_a_registry_package():
    for manifest in sorted(ROOT.glob("**/package.json")):
        if "node_modules" in manifest.parts:
            continue
        data = json.loads(manifest.read_text(encoding="utf-8"))
        for field in ("dependencies", "devDependencies", "peerDependencies", "optionalDependencies"):
            spec = (data.get(field) or {}).get(KIT)
            assert spec is None or not str(spec).startswith(("npm:", "http", "git", "github:")), f"{manifest}: {KIT} -> {spec}"


def test_the_lockfile_links_the_kit_to_this_repository():
    packages = _load("package-lock.json")["packages"]
    assert packages[f"node_modules/{KIT}"] == {"resolved": "packages/ui", "link": True}
    assert packages["packages/ui"]["name"] == KIT
    for path, entry in packages.items():
        resolved = str(entry.get("resolved", ""))
        assert not (path.endswith(f"/{KIT}") and resolved.startswith("http")), f"{path} resolves to {resolved}"
