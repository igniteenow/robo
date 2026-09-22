# Move every dependency flagged by Dependabot to its patched version and
# regenerate the lockfiles. Copyright (c) 2026 Ignitee Now.
#
# Run from the repository root, on a machine with internet:
#     Set-ExecutionPolicy -Scope Process Bypass
#     .\scripts\security-update.ps1
# Then review `git diff --stat`, commit, and push.
#
# What it does:
#   1. Python: cryptography 48.0.1 -> 50.0.0 (GHSA-g6cj-pr64-35w5, CVE-2026-69247)
#              anyio       4.12.1 -> >= 4.14.2 (GHSA-82r6-8w77-94w6, CVE-2026-63374, critical)
#              then regenerates uv.lock with hashes.
#   2. npm: runs `npm audit fix` in every folder Dependabot flagged
#           (root, website, scripts\whatsapp-bridge) and reports what remains.
#   3. Verifies with pip-audit and npm audit.
$ErrorActionPreference = 'Continue'
Set-Location (Join-Path $PSScriptRoot '..')

function Need($cmd, $hint) {
    if (-not (Get-Command $cmd -ErrorAction SilentlyContinue)) {
        Write-Host "ERROR: '$cmd' is not installed. $hint" -ForegroundColor Red
        exit 1
    }
}
Need uv  'Install it with:  powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"   then open a NEW PowerShell window.'
Need npm 'Install Node 22 from https://nodejs.org then open a NEW PowerShell window.'

Write-Host "== 1/3  Python dependencies" -ForegroundColor Cyan
$p = 'pyproject.toml'
$s = Get-Content $p -Raw -Encoding UTF8
$s2 = $s -replace '"cryptography==48\.0\.1"', '"cryptography==50.0.0"'
if (($s2 -eq $s) -and ($s -notmatch '"cryptography==50\.0\.0"')) {
    Write-Host "ERROR: cryptography pin not found in pyproject.toml; edit it by hand to ==50.0.0" -ForegroundColor Red
    exit 1
}
# anyio is transitive (via httpx / mcp). Constrain it so uv cannot resolve a vulnerable version.
if ($s2 -notmatch 'constraint-dependencies') {
    if ($s2 -match '\[tool\.uv\]') {
        $s2 = $s2 -replace '\[tool\.uv\]\r?\n', "[tool.uv]`nconstraint-dependencies = [`"anyio>=4.14.2`"]`n"
    } else {
        $s2 = $s2.TrimEnd() + "`n`n[tool.uv]`nconstraint-dependencies = [`"anyio>=4.14.2`"]`n"
    }
} elseif ($s2 -notmatch 'anyio>=4\.14\.2') {
    $s2 = $s2 -replace 'constraint-dependencies = \[', 'constraint-dependencies = ["anyio>=4.14.2", '
}
[System.IO.File]::WriteAllText((Resolve-Path $p).Path, $s2, (New-Object System.Text.UTF8Encoding($false)))
Write-Host "   pyproject.toml: cryptography==50.0.0, anyio constrained to >=4.14.2"

# --upgrade moves every transitive package to its newest allowed version, which
# is what clears the pip advisories Dependabot lists beyond anyio/cryptography.
uv lock --upgrade
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: 'uv lock' failed. Fix the error above, then re-run." -ForegroundColor Red
    exit 1
}
Write-Host "   uv.lock regenerated:"
foreach ($pkg in @('anyio', 'cryptography')) {
    $hit = Select-String -Path uv.lock -Pattern ('^name = "' + $pkg + '"$') -Context 0, 1 | Select-Object -First 1
    if ($hit) { $ver = ($hit.Context.PostContext[0] -replace '^version = ', ''); Write-Host "     $pkg -> $ver" }
}

Write-Host ""
Write-Host "== 2/3  npm dependencies" -ForegroundColor Cyan
$lockfiles = Get-ChildItem -Recurse -Filter package-lock.json | Where-Object { $_.FullName -notmatch '\\node_modules\\' }
foreach ($dir in ($lockfiles | ForEach-Object { $_.DirectoryName })) {
    Write-Host "   -- $dir"
    Push-Location $dir
    try {
        npm audit fix --package-lock-only --ignore-scripts 2>$null | Out-Null
        # A second pass picks up fixes that only become possible after the first.
        npm audit fix --package-lock-only --ignore-scripts 2>$null | Out-Null
        npm audit --audit-level=high --omit=dev 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) {
            Write-Host "      production dependencies: no high/critical advisories remain" -ForegroundColor Green
        } else {
            Write-Host "      production dependencies still flagged (see below); consider 'overrides' in package.json" -ForegroundColor Yellow
            npm audit --audit-level=high --omit=dev 2>$null | Select-Object -First 40
        }
        npm audit --audit-level=high 2>$null | Out-Null
        if ($LASTEXITCODE -ne 0) {
            Write-Host "      dev-only advisories remain (build tooling; not shipped to users):" -ForegroundColor Yellow
            npm audit --audit-level=high 2>$null | Select-String '^(#|Severity|Package|Dependency of)' | Select-Object -First 20
        }
    } finally { Pop-Location }
}

Write-Host ""
Write-Host "== 3/3  verification" -ForegroundColor Cyan
$reqs = Join-Path $env:TEMP 'robo-reqs.txt'
uv export --format requirements-txt --no-hashes -o $reqs 2>$null | Out-Null
if (Test-Path $reqs) {
    uvx pip-audit -r $reqs --strict 2>$null
    if ($LASTEXITCODE -eq 0) { Write-Host "   pip-audit: clean" -ForegroundColor Green }
    else { Write-Host "   pip-audit: findings above (transitive packages may need 'uv lock --upgrade')" -ForegroundColor Yellow }
}

Write-Host ""
Write-Host "Done. Review, then:" -ForegroundColor Cyan
Write-Host '   git add pyproject.toml uv.lock package-lock.json website/package-lock.json scripts/whatsapp-bridge/package-lock.json scripts/security-update.ps1'
Write-Host '   git commit -m "deps: patch Dependabot advisories (anyio, cryptography, npm audit fix)"'
Write-Host '   git push'
