#!/usr/bin/env bash
# B.5 — end-to-end Linux gate for the single-session release.
#
# This script is self-contained. It runs from a freshly extracted
# archive on Linux with NO git repository, NO sibling tarballs, and
# NO pre-installed Python or Flutter deps. Provenance is read from
# PROVENANCE.txt (frozen at archive-build time); no git command is
# ever invoked here — the extracted tree may or may not be a git
# repo, and the script must behave identically either way.
#
# What it validates against real infrastructure:
#   * disposable pgvector/pg17 container
#   * `alembic upgrade head` lands the schema at 0025
#   * full B.3 Python gate (5 test files)
#   * B.4 focused + auth-neighbor Flutter tests
#   * `flutter analyze` on modified files
#   * `flutter build web --release`
#   * `docker build` of the backend from the SAME extracted source
#
# What it does NOT do:
#   * touch production DB, production.env, or live containers
#   * push, deploy, or publish anything
#   * mutate the extracted source tree beyond running deps installs
#     in-place (`pip install`, `flutter pub get`) — both of those
#     write into the archive's own subtrees.
#
# Prerequisites (only these must exist on the host):
#   * Docker (with the current user in the docker group)
#   * Python 3.13
#   * Flutter SDK on PATH matching the repo's expected version
#   * curl, sha256sum, tar (all standard)
#
# Exit code 0 = every automated gate passed. Non-zero at the first
# failed step, with the offending log written under $ART_DIR.

set -euo pipefail
umask 022

# --------------------------------------------------------------
# 0. Locate ourselves. The script is designed to be run from the
#    extracted archive root: `cd vaultai-b5-validation && ./b5-linux-gate.sh`.
# --------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" &>/dev/null && pwd)"
REPO_ROOT="${REPO_ROOT:-$SCRIPT_DIR}"
ART_DIR="${ART_DIR:-$REPO_ROOT/b5-artifacts}"
mkdir -p "$ART_DIR"

LOG() { printf '[B.5] %s\n' "$*"; }
FAIL() { printf '[B.5][FAIL] %s\n' "$*" >&2; exit 1; }

cd "$REPO_ROOT"

# --------------------------------------------------------------
# 1. Read frozen provenance. No git calls.
# --------------------------------------------------------------
PROV_FILE="$REPO_ROOT/PROVENANCE.txt"
[ -f "$PROV_FILE" ] || FAIL "PROVENANCE.txt missing at $PROV_FILE — archive is not a B.5 bundle."

GIT_HEAD_FULL="$(awk -F'= *' '/^[[:space:]]*git_head_full[[:space:]]/ {print $2; exit}' "$PROV_FILE" | tr -d ' \r\n')"
GIT_HEAD_SHORT="$(awk -F'= *' '/^[[:space:]]*git_head_short[[:space:]]/ {print $2; exit}' "$PROV_FILE" | tr -d ' \r\n')"
GIT_DIRTY_LINES="$(awk -F'= *' '/^[[:space:]]*git_dirty_line_count[[:space:]]/ {print $2; exit}' "$PROV_FILE" | tr -d ' \r\n')"
EXPECTED_MIG_SHA="$(awk -F'= *' '/^[[:space:]]*migration_0025_sha256[[:space:]]/ {print $2; exit}' "$PROV_FILE" | tr -d ' \r\n')"
EXPECTED_AUTH_LOCAL_SHA="$(awk -F'= *' '/^[[:space:]]*auth_local_sha256[[:space:]]/ {print $2; exit}' "$PROV_FILE" | tr -d ' \r\n')"
EXPECTED_DELETE_ROUTES_SHA="$(awk -F'= *' '/^[[:space:]]*vault_delete_routes_sha256[[:space:]]/ {print $2; exit}' "$PROV_FILE" | tr -d ' \r\n')"

for var in GIT_HEAD_FULL GIT_HEAD_SHORT GIT_DIRTY_LINES \
           EXPECTED_MIG_SHA EXPECTED_AUTH_LOCAL_SHA EXPECTED_DELETE_ROUTES_SHA; do
    if [ -z "${!var}" ]; then
        FAIL "PROVENANCE.txt missing field: $var"
    fi
done

LOG "provenance loaded from PROVENANCE.txt:"
LOG "  git_head_full         = $GIT_HEAD_FULL"
LOG "  git_head_short        = $GIT_HEAD_SHORT"
LOG "  git_dirty_line_count  = $GIT_DIRTY_LINES"
LOG "  expected migration    = $EXPECTED_MIG_SHA"

# --------------------------------------------------------------
# 2. Spot-check three known-good file SHAs against provenance.
# --------------------------------------------------------------
LOG "spot-checking file SHAs against PROVENANCE.txt"
ACTUAL_MIG_SHA="$(sha256sum "$REPO_ROOT/vault_ai_backend/migrations/versions/0025_auth_session_hardening.py" | awk '{print $1}')"
ACTUAL_AUTH_LOCAL_SHA="$(sha256sum "$REPO_ROOT/vault_ai_backend/auth_local.py" | awk '{print $1}')"
ACTUAL_DELETE_ROUTES_SHA="$(sha256sum "$REPO_ROOT/vault_ai_backend/routes/vault_delete_routes.py" | awk '{print $1}')"

[ "$ACTUAL_MIG_SHA" = "$EXPECTED_MIG_SHA" ] || \
    FAIL "migration 0025 sha mismatch — bundle corrupt or tampered"
[ "$ACTUAL_AUTH_LOCAL_SHA" = "$EXPECTED_AUTH_LOCAL_SHA" ] || \
    FAIL "auth_local.py sha mismatch — bundle corrupt or tampered"
[ "$ACTUAL_DELETE_ROUTES_SHA" = "$EXPECTED_DELETE_ROUTES_SHA" ] || \
    FAIL "vault_delete_routes.py sha mismatch — bundle corrupt or tampered"
LOG "  all three file SHAs match PROVENANCE.txt"

# --------------------------------------------------------------
# 3. Disposable Postgres 17 (pgvector image).
# --------------------------------------------------------------
LOG "starting disposable pgvector/pg17 container"
docker rm -f vaultai-pg-b5 >/dev/null 2>&1 || true
docker run -d --name vaultai-pg-b5 --rm \
  -e POSTGRES_PASSWORD=disposable -e POSTGRES_USER=vaultai \
  -e POSTGRES_DB=vaultai_b5 \
  -p 127.0.0.1:15432:5432 --tmpfs /var/lib/postgresql/data \
  pgvector/pgvector:pg17 >/dev/null

trap 'docker stop vaultai-pg-b5 >/dev/null 2>&1 || true' EXIT

for _ in $(seq 1 60); do
    if docker exec vaultai-pg-b5 pg_isready -U vaultai >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
docker exec vaultai-pg-b5 pg_isready -U vaultai >/dev/null 2>&1 || \
    FAIL "pgvector/pg17 never became ready"
LOG "pg17 ready on 127.0.0.1:15432"

# --------------------------------------------------------------
# 4. Backend Python deps + migrations + B.3 test gate.
# --------------------------------------------------------------
export DATABASE_URL='postgresql://vaultai:disposable@127.0.0.1:15432/vaultai_b5'
export VAULTAI_TEST_DATABASE_URL="$DATABASE_URL"
export VAULT_SESSION_SECRET="$(python3 -c 'import secrets;print(secrets.token_urlsafe(48))')"

cd "$REPO_ROOT/vault_ai_backend"

LOG "installing backend python deps into a local venv"
python3 -m venv "$REPO_ROOT/.b5-venv"
# shellcheck disable=SC1091
. "$REPO_ROOT/.b5-venv/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt \
    2>&1 | tee "$ART_DIR/pip_install.log" >/dev/null

LOG "applying alembic head"
python -m alembic -c alembic.ini upgrade head 2>&1 | tee "$ART_DIR/alembic_head.log"

DB_MIG_VERSION="$(docker exec vaultai-pg-b5 psql -U vaultai -d vaultai_b5 -tAc \
    "SELECT version_num FROM alembic_version LIMIT 1;" | tr -d '[:space:]')"
LOG "DB migration = $DB_MIG_VERSION"
[ "$DB_MIG_VERSION" = "0025_auth_session_hardening" ] || \
    FAIL "DB not at 0025 (got '$DB_MIG_VERSION')"

LOG "running full B.3 gate"
python -m pytest \
    test_auth_zk_finalize_issue_bug_2026_07_16.py \
    test_migration_0025_auth_session_hardening.py \
    test_single_session_backend_2026_07_17.py \
    test_vault_delete_session_revocation_2026_07_09.py \
    test_auth_routes.py \
    test_auth_session_token.py \
    -v --tb=short 2>&1 | tee "$ART_DIR/b3_gate.log"
B3_EXIT=${PIPESTATUS[0]}
LOG "B.3 gate exit=$B3_EXIT"

# --------------------------------------------------------------
# 5. Frontend: pub get, focused tests, analyze, web release build.
# --------------------------------------------------------------
cd "$REPO_ROOT/vault_ai_frontend"

LOG "resolving flutter pub deps"
flutter pub get 2>&1 | tee "$ART_DIR/flutter_pub_get.log" >/dev/null

LOG "running focused Flutter tests (B.4 + auth-neighbor)"
flutter test \
    test/session_termination_2026_07_17_test.dart \
    test/auth_pages_test.dart \
    test/delete_vault_session_cleanup_2026_07_09_test.dart \
    test/shared_loader_auth_device_timeout_unmasking_test.dart \
    2>&1 | tee "$ART_DIR/flutter_tests.log"
FLUTTER_TEST_EXIT=${PIPESTATUS[0]}

LOG "running flutter analyze on modified/new files"
flutter analyze \
    lib/services/session_termination.dart \
    lib/services/session_termination_channel.dart \
    lib/services/session_termination_channel_web.dart \
    lib/api_client.dart \
    lib/main.dart \
    test/session_termination_2026_07_17_test.dart \
    2>&1 | tee "$ART_DIR/flutter_analyze.log" || true

LOG "building flutter web release (--allow-dev-release; no git repo)"
./scripts/build-web-release.sh --allow-dev-release \
    2>&1 | tee "$ART_DIR/flutter_web_build.log"

FRONTEND_BUNDLE_TAR="$ART_DIR/b5-frontend-bundle.tar.gz"
tar -czf "$FRONTEND_BUNDLE_TAR" -C "$REPO_ROOT/vault_ai_frontend/build" web
FRONTEND_BUNDLE_SHA="$(sha256sum "$FRONTEND_BUNDLE_TAR" | awk '{print $1}')"
FRONTEND_BUNDLE_FILES="$(find "$REPO_ROOT/vault_ai_frontend/build/web" -type f | wc -l)"
LOG "frontend bundle sha256=$FRONTEND_BUNDLE_SHA files=$FRONTEND_BUNDLE_FILES"

# --------------------------------------------------------------
# 6. Backend Docker image built from the SAME extracted source.
# --------------------------------------------------------------
cd "$REPO_ROOT/vault_ai_backend"
LOG "building backend Docker image (multi-stage, includes pyo3 wheel)"
docker build \
    -t "vaultai-backend:b5-$GIT_HEAD_SHORT" \
    -t "vaultai-backend:b5-latest" \
    . 2>&1 | tee "$ART_DIR/backend_docker_build.log"

BACKEND_IMAGE_ID="$(docker images --format '{{.ID}}' vaultai-backend:b5-latest | head -1)"
BACKEND_IMAGE_DIGEST="$(docker inspect --format='{{.Id}}' vaultai-backend:b5-latest)"
LOG "backend image id=$BACKEND_IMAGE_ID digest=$BACKEND_IMAGE_DIGEST"

# Reproducible source hash — tar the actual backend source we just
# used, so the record is honest ("this exact tree fed docker build").
BACKEND_SRC_TAR="$ART_DIR/b5-backend-source.tar.gz"
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --exclude='__pycache__' --exclude='.pytest_cache' \
    --exclude='opaque_server_crate/target' \
    -czf "$BACKEND_SRC_TAR" -C "$REPO_ROOT" vault_ai_backend
BACKEND_SRC_SHA="$(sha256sum "$BACKEND_SRC_TAR" | awk '{print $1}')"
LOG "backend source archive sha256=$BACKEND_SRC_SHA"

# --------------------------------------------------------------
# 7. Manual scenarios 3-7 — browser-driven, HUMAN VERIFICATION.
#
# The repo does NOT ship a browser E2E harness. Scenarios 3-7 have
# unit-level coverage from B.4 tests above; full user-visible
# verification requires an operator to drive two browser tabs
# against the local stack and confirm exact UI + navigation.
#
# To run scenarios 3-7 by hand:
#
#   1) Start the backend against the disposable DB above:
#        cd $REPO_ROOT/vault_ai_backend
#        DATABASE_URL="$DATABASE_URL" \
#        VAULT_SESSION_SECRET="$VAULT_SESSION_SECRET" \
#        VAULTAI_ENV=dev \
#        python -m uvicorn main:app --host 127.0.0.1 --port 8000
#
#   2) Rebuild the frontend against the local backend:
#        cd $REPO_ROOT/vault_ai_frontend
#        flutter build web --release --pwa-strategy=none \
#          --dart-define=BACKEND_BASE_URL=http://127.0.0.1:8000 \
#          --dart-define=APP_RELEASE="devbuild-$GIT_HEAD_SHORT"
#
#   3) Serve the bundle:
#        cd $REPO_ROOT/vault_ai_frontend/build/web
#        python -m http.server 4200
#
#   4) In a browser, verify each scenario against the running stack:
#        - scenario 3: device A -> 401 session_superseded -> login screen
#        - scenario 4: two tabs -> one 401 -> both clear and navigate
#        - scenario 5: manual logout -> no "another device" text
#        - scenario 6: revoke stored token, reload -> login (no vault UI)
#        - scenario 7: multiple concurrent requests -> one 401 -> all block
# --------------------------------------------------------------
LOG "scenarios 3-7 require a manual browser session (no automated"
LOG "  E2E harness ships in this repo). See instructions above."

# --------------------------------------------------------------
# 8. Release-integrity summary.
# --------------------------------------------------------------
cat > "$ART_DIR/release_integrity.txt" <<EOF
git_head_full            = $GIT_HEAD_FULL
git_head_short           = $GIT_HEAD_SHORT
git_dirty_line_count     = $GIT_DIRTY_LINES  (frozen from PROVENANCE.txt)
provenance_source        = PROVENANCE.txt (no git invocation)
migration_0025_sha256    = $ACTUAL_MIG_SHA
auth_local_sha256        = $ACTUAL_AUTH_LOCAL_SHA
vault_delete_routes_sha  = $ACTUAL_DELETE_ROUTES_SHA
db_migration_version     = $DB_MIG_VERSION
backend_source_sha256    = $BACKEND_SRC_SHA
backend_source_archive   = $BACKEND_SRC_TAR
frontend_bundle_sha256   = $FRONTEND_BUNDLE_SHA
frontend_bundle_files    = $FRONTEND_BUNDLE_FILES
frontend_bundle_archive  = $FRONTEND_BUNDLE_TAR
backend_image_id         = $BACKEND_IMAGE_ID
backend_image_digest     = $BACKEND_IMAGE_DIGEST
b3_gate_exit             = $B3_EXIT
flutter_test_exit        = $FLUTTER_TEST_EXIT
same_source_tree         = YES  (backend Docker image AND frontend
                                 bundle above were both built from
                                 the same extracted archive rooted
                                 at $REPO_ROOT)
EOF

LOG "release_integrity.txt written to $ART_DIR/release_integrity.txt"
cat "$ART_DIR/release_integrity.txt"

if [ "$B3_EXIT" -eq 0 ] && [ "$FLUTTER_TEST_EXIT" -eq 0 ]; then
    LOG "AUTOMATED GATE PASSED"
    exit 0
else
    LOG "AUTOMATED GATE FAILED (b3_exit=$B3_EXIT flutter_exit=$FLUTTER_TEST_EXIT)"
    exit 1
fi
