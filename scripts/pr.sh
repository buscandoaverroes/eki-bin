#!/usr/bin/env bash
# Push the current branch and open (or find) its PR against dev.
#
#   make pr                          # body from .pr-body.md, else from commits
#   make pr BODY=path/to/body.md     # explicit body file
#   make pr TITLE="feat: ..."        # explicit title (default: newest commit subject)
#   make pr BASE=main DRAFT=1
#   make pr YES=1                    # skip the confirmation (non-interactive)
#
# This is the USER's script: CLAUDE.md forbids Claude from pushing, so Claude
# drafts the body (to .pr-body.md, gitignored) and you run this.
#
# WHY IT ASKS: this repo is PUBLIC. A PR body is indexed and permanent, and a
# push is outward-facing. So it shows exactly what will be published and waits
# for a yes — and, on success, deletes the default .pr-body.md so a stale
# draft can never be silently reused for the NEXT branch's PR.
#
# Threat note: running this executes repo code with your `gh` credentials.
# Read any diff touching scripts/ or the Makefile before you do.
# bash 3.2 compatible (macOS default).
set -euo pipefail

BASE="${BASE:-dev}"
TITLE="${TITLE:-}"
BODY="${BODY:-.pr-body.md}"
DRAFT="${DRAFT:-}"
YES="${YES:-}"
DEFAULT_BODY=".pr-body.md"

branch="$(git rev-parse --abbrev-ref HEAD)"
case "$branch" in
  dev|main) echo "✗ on '$branch' — cut a feature/<name> branch first." >&2; exit 1 ;;
esac

if ! command -v gh >/dev/null 2>&1; then
  echo "✗ gh not installed (brew install gh, then gh auth login)." >&2; exit 1
fi

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  echo "✗ uncommitted changes to tracked files — commit or stash first." >&2; exit 1
fi

[ -n "$TITLE" ] || TITLE="$(git log -1 --format=%s)"

# Already open? A push still updates it; no new PR, no body to show.
existing="$(gh pr view "$branch" --json url,state -q 'select(.state=="OPEN") | .url' 2>/dev/null || true)"

tmp=""
cleanup() { [ -z "$tmp" ] || rm -f "$tmp"; }
trap cleanup EXIT

if [ ! -f "$BODY" ]; then
  # Throwaway body: the commits on this branch, nothing more.
  tmp="$(mktemp)"
  BODY="$tmp"
  {
    echo "## Commits"
    git log --reverse --format='- %s' "origin/$BASE..HEAD" 2>/dev/null \
      || git log --reverse --format='- %s' "$BASE..HEAD"
  } > "$BODY"
  body_note="(no body file — the commit list)"
else
  body_note="($BODY)"
fi

echo "──────────────────────────────────────────────"
echo " repo    $(git remote get-url origin)"
echo " branch  $branch  →  $BASE${DRAFT:+  [draft]}"
if [ -n "$existing" ]; then
  echo " action  PUSH ONLY — a PR is already open: $existing"
else
  echo " title   $TITLE"
  echo " body    $body_note, $(wc -l < "$BODY" | tr -d ' ') lines — first 15:"
  sed -n '1,15p' "$BODY" | sed 's/^/           | /'
fi
echo "──────────────────────────────────────────────"

# The repo is PUBLIC and a PR body is permanent. Scan what would be published
# (outgoing diff + commit messages + this title/body) BEFORE asking for a yes.
# LEAKCHECK_SKIP=1 exists for a reviewed false positive; prefer marking the
# line `leakcheck:ok`.
if [ -z "${LEAKCHECK_SKIP:-}" ]; then
  if [ -n "$existing" ]; then
    scripts/leakcheck.sh --range "origin/$BASE..HEAD" || exit 1
  else
    scripts/leakcheck.sh --range "origin/$BASE..HEAD" --title "$TITLE" --body "$BODY" || exit 1
  fi
else
  echo "⚠ LEAKCHECK_SKIP set — scan skipped." >&2
fi

if [ -z "$YES" ]; then
  if [ ! -t 0 ]; then
    echo "✗ not a terminal — re-run interactively, or set YES=1." >&2; exit 1
  fi
  printf "Push and continue? [y/N] "
  read -r reply
  case "$reply" in y|Y|yes|YES) ;; *) echo "aborted — nothing pushed."; exit 1 ;; esac
fi

echo "→ pushing $branch"
git push -u origin "$branch"

if [ -n "$existing" ]; then
  echo "✓ push updated the open PR: $existing"
  exit 0
fi

args=(--base "$BASE" --head "$branch" --title "$TITLE" --body-file "$BODY")
[ -n "$DRAFT" ] && args+=(--draft)
gh pr create "${args[@]}"

# Consume the draft so it cannot leak into the next PR. Only the default
# path — a body file you named yourself is yours to keep.
if [ "$BODY" = "$DEFAULT_BODY" ]; then
  rm -f "$DEFAULT_BODY"
  echo "  (removed $DEFAULT_BODY — drafts are single-use)"
fi
