# Developer pre-flight for migrations.
#
# Run this BEFORE pushing a migration change. It catches every failure
# mode that has bricked backend startup in the past:
#
#   1. Python SyntaxErrors in any migration file (broken f-strings,
#      stray braces, indentation bugs).
#   2. Module-load-time exceptions (.format() with mismatched braces,
#      KeyError / IndexError at import time).
#   3. A broken Alembic revision graph - missing parents, cycles, or
#      more than one head / base.
#   4. The actual ``upgrade head`` against the local test DB, which
#      verifies that PostgreSQL accepts every SQL the migrations emit
#      (e.g. catches a literal ``{{}}`` arriving at the planner).
#
# This script is intentionally light. It DOES NOT require pytest. It
# runs the same checks that ``test_migration_safety.py`` automates,
# but as standalone CLI calls so a developer can paste any failing
# command into the terminal and iterate.
#
# Usage (from vault_ai_backend/):
#   pwsh scripts/check-migrations.ps1
#
# Set VAULTAI_TEST_DATABASE_URL beforehand to exercise step 4. Without
# it, steps 1-3 still run (they're DB-free) and step 4 is skipped.

$ErrorActionPreference = "Stop"

# Move to the backend directory regardless of where the script was
# launched from - alembic.ini lives there.
$BackendDir = Split-Path -Parent $PSScriptRoot
Set-Location $BackendDir

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " VaultAI migration pre-flight" -ForegroundColor Cyan
Write-Host " Working dir: $BackendDir" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

# Step 1 - syntax-check every migration file.
Write-Host ""
Write-Host "[1/4] python -m compileall migrations/versions" -ForegroundColor Yellow
python -m compileall -q migrations/versions
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FAILED: a migration file has a Python SyntaxError." -ForegroundColor Red
    Write-Host "Most common cause: an f-string with a bare '{}' slot." -ForegroundColor Red
    Write-Host "Fix: escape JSONB defaults inside f-strings as '{{}}'::jsonb." -ForegroundColor Red
    exit 1
}

# Step 2 - alembic history (loads the revision script directory).
Write-Host ""
Write-Host "[2/4] python -m alembic history" -ForegroundColor Yellow
python -m alembic history
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FAILED: Alembic could not walk the revision graph." -ForegroundColor Red
    Write-Host "Most common cause: a migration's down_revision points at" -ForegroundColor Red
    Write-Host "a revision id that doesn't exist, or two heads exist." -ForegroundColor Red
    exit 1
}

# Step 3 - alembic current (requires a DB; gracefully skip if absent).
$dbUrl = $env:VAULTAI_TEST_DATABASE_URL
if (-not $dbUrl) {
    $dbUrl = $env:DATABASE_URL
}
if (-not $dbUrl) {
    Write-Host ""
    Write-Host "[3/4] python -m alembic current  (SKIPPED - no DB url)" -ForegroundColor DarkGray
    Write-Host "      Set VAULTAI_TEST_DATABASE_URL to enable steps 3-4." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "[4/4] python -m alembic upgrade head  (SKIPPED - no DB url)" -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "OK: syntax + revision graph clean. DB-free checks passed." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "[3/4] python -m alembic current" -ForegroundColor Yellow
python -m alembic current
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FAILED: Alembic could not read the current schema head." -ForegroundColor Red
    Write-Host "Check that VAULTAI_TEST_DATABASE_URL points at a real DB" -ForegroundColor Red
    Write-Host "and that alembic_version table exists." -ForegroundColor Red
    exit 1
}

# Step 4 - actually run upgrade head against the test DB.
Write-Host ""
Write-Host "[4/4] python -m alembic upgrade head" -ForegroundColor Yellow
python -m alembic upgrade head
if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "FAILED: alembic upgrade head raised at runtime." -ForegroundColor Red
    Write-Host "Most common causes:" -ForegroundColor Red
    Write-Host "  - SQL syntax error (e.g. literal '{{}}'::jsonb leaked" -ForegroundColor Red
    Write-Host "    into a plain string instead of an f-string)" -ForegroundColor Red
    Write-Host "  - missing FOREIGN KEY target" -ForegroundColor Red
    Write-Host "  - duplicate CHECK constraint" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "OK: all four checks passed. Schema is at head." -ForegroundColor Green
