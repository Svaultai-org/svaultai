#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_dir="$(cd "$script_dir/../.." && pwd)"
cd "$repo_dir"

candidate="${1:-${RELEASE_SHA:-HEAD}}"
base_ref="${RELEASE_BASE_REF:-origin/main}"

fail() {
  echo "[release-baseline] ERROR: $*" >&2
  exit 2
}

git rev-parse --is-inside-work-tree >/dev/null 2>&1 ||
  fail "release source is not a Git worktree"

# A production release must be compared with the current GitHub main, not a
# possibly stale remote-tracking ref left by an earlier task. Local/offline
# tests may explicitly skip the refresh; release wrappers never do.
if [[ "${RELEASE_BASELINE_SKIP_REMOTE_REFRESH:-0}" != "1" ]]; then
  git fetch --quiet origin refs/heads/main:refs/remotes/origin/main ||
    fail "could not refresh origin/main"
fi

git rev-parse --verify "$base_ref^{commit}" >/dev/null 2>&1 ||
  fail "required baseline $base_ref is unavailable"
candidate_sha="$(git rev-parse --verify "$candidate^{commit}" 2>/dev/null)" ||
  fail "candidate $candidate is not a commit"
base_sha="$(git rev-parse --verify "$base_ref^{commit}")"

if ! git merge-base --is-ancestor "$base_sha" "$candidate_sha"; then
  echo "[release-baseline] candidate=$candidate_sha" >&2
  echo "[release-baseline] required_base=$base_sha" >&2
  fail "candidate does not contain the current main branch"
fi

# Prevent a correctly labelled SHA from being paired with different source.
# Untracked build/archive outputs are intentionally ignored.
if [[ "${RELEASE_BASELINE_ALLOW_DIRTY:-0}" != "1" ]] &&
   ! git diff --quiet "$candidate_sha" --; then
  fail "tracked files do not match candidate $candidate_sha"
fi

echo "[release-baseline] OK: $candidate_sha contains $base_sha"
