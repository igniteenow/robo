#!/usr/bin/env bash
# Move every dependency flagged by Dependabot to its patched version and
# regenerate the lockfiles. Copyright (c) 2026 Ignitee Now.
#
# Run from the repository root, on a machine with internet:
#     bash scripts/security-update.sh
# Then review `git diff --stat`, commit, and push.
#
# What it does:
#   1. Python: cryptography 48.0.1 -> 50.0.0 (GHSA-g6cj-pr64-35w5, CVE-2026-69247)
#              anyio       4.12.1 -> >= 4.14.2 (GHSA-82r6-8w77-94w6, CVE-2026-63374, critical)
#              then regenerates uv.lock with hashes.
#   2. npm: runs `npm audit fix` in every folder Dependabot flagged
#           (root, website, scripts/whatsapp-bridge) and reports what remains.
#   3. Verifies with pip-audit and npm audit.
set -euo pipefail
cd "$(dirname "$0")/.."

need() { command -v "$1" >/dev/null 2>&1 || { echo "ERROR: '$1' is not installed. $2" >&2; exit 1; }; }
need uv  "Install: curl -LsSf https://astral.sh/uv/install.sh | sh   (or: pip install uv)"
need npm "Install Node 22 from https://nodejs.org or run: bash scripts/install.sh --ensure node"

echo "== 1/3  Python dependencies"
# Raise the exact pin for the direct dependency.
python3 - <<'PY'
import re
p = "pyproject.toml"; s = open(p, encoding="utf-8").read()
s2 = re.sub(r'"cryptography==48\.0\.1"', '"cryptography==50.0.0"', s)
if s2 == s and '"cryptography==50.0.0"' not in s:
    raise SystemExit("cryptography pin not found in pyproject.toml; edit it by hand to ==50.0.0")
# anyio is transitive (via httpx / mcp). Constrain it so uv cannot resolve a vulnerable version.
if "constraint-dependencies" not in s2:
    if "[tool.uv]" in s2:
        s2 = s2.replace("[tool.uv]\n", '[tool.uv]\nconstraint-dependencies = ["anyio>=4.14.2"]\n', 1)
    else:
        s2 = s2.rstrip("\n") + '\n\n[tool.uv]\nconstraint-dependencies = ["anyio>=4.14.2"]\n'
elif "anyio>=4.14.2" not in s2:
    s2 = re.sub(r'constraint-dependencies = \[', 'constraint-dependencies = ["anyio>=4.14.2", ', s2, count=1)
open(p, "w", encoding="utf-8").write(s2)
print("   pyproject.toml: cryptography==50.0.0, anyio constrained to >=4.14.2")
PY
# --upgrade moves every transitive package to its newest allowed version, which
# is what clears the pip advisories Dependabot lists beyond anyio/cryptography.
uv lock --upgrade
echo "   uv.lock regenerated:"
for pkg in anyio cryptography; do
  v=$(grep -A1 "^name = \"$pkg\"$" uv.lock | grep version | head -1 | sed 's/.*= //')
  echo "     $pkg -> $v"
done

echo
echo "== 2/3  npm dependencies"
for lock in $(find . -name package-lock.json -not -path '*/node_modules/*'); do
  dir=$(dirname "$lock")
  echo "   -- $dir"
  ( cd "$dir"
    npm audit fix --package-lock-only --no-audit-level --ignore-scripts >/dev/null 2>&1 || true
    # A second pass picks up fixes that only become possible after the first.
    npm audit fix --package-lock-only --ignore-scripts >/dev/null 2>&1 || true
    if npm audit --audit-level=high --omit=dev >/dev/null 2>&1; then
      echo "      production dependencies: no high/critical advisories remain"
    else
      echo "      production dependencies still flagged (see below); consider 'overrides' in package.json"
      npm audit --audit-level=high --omit=dev 2>/dev/null | head -40 || true
    fi
    if ! npm audit --audit-level=high >/dev/null 2>&1; then
      echo "      dev-only advisories remain (build tooling; not shipped to users):"
      npm audit --audit-level=high 2>/dev/null | grep -E "^(#|Severity|Package|Dependency of)" | head -20 || true
    fi
  )
done

echo
echo "== 3/3  verification"
if uv export --format requirements-txt --no-hashes > /tmp/robo-reqs.txt 2>/dev/null; then
  uvx pip-audit -r /tmp/robo-reqs.txt --strict 2>/dev/null && echo "   pip-audit: clean" || echo "   pip-audit: findings above (transitive packages may need 'uv lock --upgrade')"
fi
echo
echo "Done. Review, then:"
echo "   git add pyproject.toml uv.lock package-lock.json website/package-lock.json scripts/whatsapp-bridge/package-lock.json"
echo "   git commit -m 'deps: patch Dependabot advisories (anyio, cryptography, npm audit fix)'"
echo "   git push"
