#!/usr/bin/env bash
# scripts/leakcheck.sh — scan what is about to be PUBLISHED for things that
# should not be. Called by: make leakcheck, scripts/pr.sh, .githooks/pre-push
#
# This repo is PUBLIC. .gitignore stops known secret FILES; it cannot stop a
# secret or a personal detail from being typed into a tracked file, a commit
# message, or a PR body — and none of those can be un-published afterwards.
#
# What it scans (only what is being published, not the whole tree):
#   • the ADDED lines of the outgoing diff   (git diff RANGE)
#   • the outgoing commit messages           (git log RANGE)
#   • a PR body and title, if given          (--body FILE, --title TEXT)
#
# Two rule sets:
#   1. GENERIC patterns below — credentials, private keys, home-directory
#      paths, non-noreply emails, coordinates. Safe to live in the repo.
#   2. PERSONAL terms in .leakcheck-terms (gitignored, one per line, '#'
#      comments) — your station names, street, SSID, employer. These must
#      NEVER be committed, which is exactly why this check runs LOCALLY and
#      not as a hosted CI job: a CI runner would need the list, and the list
#      is the very thing being protected.
#
# Suppress a deliberate false positive by putting  leakcheck:ok  on that line.
# Exit 0 clean, 1 findings, 2 usage error. bash 3.2 compatible.
# NB: under pipefail a grep with NO match returns 1, so every scan line below
# ends in `|| true` — a clean result must not look like a failure.
set -euo pipefail

BASE="${BASE:-dev}"
RANGE=""; BODY=""; TITLE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --range) RANGE="$2"; shift 2 ;;
    --body)  BODY="$2";  shift 2 ;;
    --title) TITLE="$2"; shift 2 ;;
    *) echo "usage: leakcheck.sh [--range A..B] [--body FILE] [--title TEXT]" >&2; exit 2 ;;
  esac
done

if [ -z "$RANGE" ]; then
  if git rev-parse --verify -q "origin/$BASE" >/dev/null; then RANGE="origin/$BASE..HEAD"
  elif git rev-parse --verify -q "$BASE" >/dev/null;       then RANGE="$BASE..HEAD"
  else RANGE="HEAD~1..HEAD"; fi
fi

STREAM="$(mktemp)"; TERMS="$(mktemp)"
HIT="$STREAM.hit"
trap 'rm -f "$STREAM" "$STREAM.f" "$TERMS" "$HIT"' EXIT

# ── build one stream of  source:line: text  records ──────────────────────
# Added lines only, tagged with file and NEW line number (parsed from @@).
git diff -U0 --no-color --diff-filter=AM "$RANGE" | awk '
  /^\+\+\+ b\// { file = substr($0, 7); next }
  /^\+\+\+ /    { file = ""; next }
  /^@@/ { match($0, /\+[0-9]+/); n = substr($0, RSTART + 1, RLENGTH - 1) + 0; next }
  /^\+/ && file != "" { print file ":" n ": " substr($0, 2); n++ }
' >> "$STREAM"
git log --format='%B' "$RANGE" | awk 'NF { print "commit-message:" NR ": " $0 }' >> "$STREAM"
[ -z "$TITLE" ] || echo "pr-title:1: $TITLE" >> "$STREAM"
[ -z "$BODY" ] || [ ! -f "$BODY" ] || awk '{ print "pr-body:" NR ": " $0 }' "$BODY" >> "$STREAM"

# Never let a deliberate marker or this file's own pattern table trip itself.
grep -v 'leakcheck:ok' "$STREAM" | grep -v '^scripts/leakcheck.sh:' > "$STREAM.f" || true
mv "$STREAM.f" "$STREAM"

# report() runs at the end of a pipeline, i.e. in a SUBSHELL — a variable set
# there is lost. A flag file is how it tells the parent something was found.
report() {  # report LABEL  (reads matching lines on stdin)
  local label="$1" hits
  hits="$(cat)"
  [ -n "$hits" ] || return 0
  : > "$HIT"
  echo "✗ $label" >&2
  echo "$hits" | cut -c1-160 | sed 's/^/    /' >&2
}

# ── 1. generic patterns ──────────────────────────────────────────────────
PLACEHOLDER='test|your_|example|changeme|xxxx|placeholder|<[a-z_ -]+>|\$\{?[A-Z_]+'

grep -E -e '-----BEGIN [A-Z ]*PRIVATE KEY-----' "$STREAM" | report "private key material" || true
grep -E -e 'gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{20,}' "$STREAM" | report "GitHub token" || true
grep -E -e 'AKIA[0-9A-Z]{16}' "$STREAM" | report "AWS access key id" || true
grep -Ei -e '(wifi_?pass|passw(or)?d|passwd|secret|token|api_?key)[A-Za-z_]*[[:space:]]*[=:][[:space:]]*["'"'"'][^"'"'"']{6,}["'"'"']' "$STREAM" \
  | grep -Eiv "$PLACEHOLDER" | report "credential-looking assignment" || true
grep -E -e '/Users/[A-Za-z0-9._-]+/|/home/[A-Za-z0-9._-]+/|C:\\Users\\' "$STREAM" | report "absolute home-directory path (reveals your username)" || true
grep -E -e '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$STREAM" \
  | grep -Eiv 'noreply|example\.(com|org)|@localhost' | report "email address" || true
grep -E -e '\b-?[0-9]{1,2}\.[0-9]{4,}[, ]+-?[0-9]{1,3}\.[0-9]{4,}\b' "$STREAM" | report "latitude/longitude pair" || true
grep -E -e '〒[0-9]{3}-?[0-9]{4}' "$STREAM" | report "Japanese postal code" || true

# ── 2. personal terms (local only, never committed) ──────────────────────
if [ -f .leakcheck-terms ]; then
  sed -e 's/#.*//' -e 's/[[:space:]]*$//' .leakcheck-terms | grep -v '^$' > "$TERMS" || true
  if [ -s "$TERMS" ]; then
    grep -F -i -f "$TERMS" "$STREAM" | report "personal term from .leakcheck-terms" || true
  fi
else
  echo "… no .leakcheck-terms — only generic patterns ran. Put your station" >&2
  echo "  names, street, SSID etc. in it (one per line; it is gitignored)." >&2
fi

if [ -e "$HIT" ]; then
  echo "" >&2
  echo "Nothing was pushed. Fix it, or mark a deliberate false positive with" >&2
  echo "'leakcheck:ok' on that line. (History already pushed cannot be recalled.)" >&2
  exit 1
fi
echo "✓ leakcheck: nothing to flag in $RANGE"
