#!/usr/bin/env bash
# Mirror the current repository to configured secondary forges.
#
#   GitLab  — push mirror (needs GITLAB_TOKEN + GITLAB_PATH [+ GITLAB_HOST])
#   Radicle — local `rad sync` (needs a `rad auth` identity on THIS machine)
#
# Each target is skipped unless configured, so this is safe to run anywhere
# (locally, on the node, or from CI — though the radicle key must NEVER be put
# into CI: a leaked node key is exactly what the PLS burn-on-exposure rule
# punishes). Run from inside a git working tree.
set -euo pipefail

BRANCH="${MIRROR_BRANCH:-main}"
git rev-parse --is-inside-work-tree >/dev/null 2>&1 || { echo "not a git repo"; exit 1; }
git fetch origin "$BRANCH" --quiet 2>/dev/null || true

# ── GitLab ────────────────────────────────────────────────────────────────
if [ -n "${GITLAB_TOKEN:-}" ] && [ -n "${GITLAB_PATH:-}" ]; then
  host="${GITLAB_HOST:-gitlab.com}"
  url="https://oauth2:${GITLAB_TOKEN}@${host}/${GITLAB_PATH}.git"
  echo "→ GitLab: mirroring ${BRANCH} to ${host}/${GITLAB_PATH}"
  git push --force "$url" "HEAD:refs/heads/${BRANCH}"
  git push --force --tags "$url" 2>/dev/null || true
else
  echo "· GitLab: skipped (set GITLAB_TOKEN + GITLAB_PATH)"
fi

# ── Radicle (local identity only) ───────────────────────────────────────────
if command -v rad >/dev/null 2>&1 && rad self >/dev/null 2>&1; then
  if rad inspect >/dev/null 2>&1; then
    echo "→ Radicle: syncing to seeds"
    rad sync 2>&1 | tail -2 || true
  else
    echo "· Radicle: this repo is not initialised — run: rad init --public"
  fi
else
  echo "· Radicle: skipped (no rad identity here — run 'rad auth' on the node)"
fi

echo "mirror-remotes: done"
