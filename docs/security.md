# Security posture — a public repo about a private commute

**Status: assessment, 2026-09-29.** Scope: the repo, the dev tooling, and the
gifted device. Not a threat model for a networked product — V2 has no radio.

## What is at stake

Nothing here is a high-value target. The real exposure is **personal**: a real
timetable or station name in a public repo says where the owner lives, and the
usage logs say when they are home. Credentials matter mostly at *gift* time —
a unit that carries the giver's WiFi password to someone else's shelf.

## Assessment

| area | finding | state |
|---|---|---|
| Secrets in tracked files and history | none found (WiFi creds, tokens, keys, private paths) | ✅ clean |
| `config.py`, real schedules, `data/`, firmware | gitignored | ✅ |
| Per-unit configs | the old rule named **one** file (`config_friend1.py`); a second unit's creds would have been tracked | ✅ fixed: `micropython/config_*.py` |
| Commit identity | GitHub noreply address on every commit | ✅ |
| Nothing published is checked | `.gitignore` covers *files*, not text typed into a tracked file, commit message or PR body | ✅ fixed: `scripts/leakcheck.sh` |
| GitHub-side protection | secret scanning, push protection, Dependabot, branch protection all **disabled** on `main` | ⚠ open — see below |
| Host dependencies | `pyyaml>=`, `esptool>=`, `ruff`, `pytest` unpinned — `make setup` runs pip as you | ✅ fixed: exact pins |
| Dev scripts | no `curl|sh`, no `sudo`, no `eval` of remote content | ✅ |
| Credentials on a gifted device | `config.py` is copied to flash in plaintext | ⚠ mitigated: `make upload` warns; blank `WIFI_*` before gifting |
| Device physical access | USB REPL is unauthenticated | accepted — it is a jar; no secrets should live on it |
| Example schedule | had comments naming a real corridor and real-looking first/last trains, narrowing a location | ✅ fixed: generated, synthetic round-number times (`make example-schedule`; a test keeps the committed file identical to the generator's output). The old text remains in git history — a corridor, not an address; rewriting public history judged not worth it |

## The local leak check

`make leakcheck` (also run by `make pr`, and by a pre-push hook after
`make hooks`/`make setup`) scans **only what is about to be published**: the
added lines of the outgoing diff, the commit messages, and the PR title/body.

- **Generic rules** (in the repo): private keys, GitHub/AWS tokens,
  credential-looking assignments, absolute home paths, non-noreply emails,
  coordinates, Japanese postal codes.
- **Personal terms** (`.leakcheck-terms`, **gitignored**): station names,
  street, SSID… Template: `.leakcheck-terms.example`.
- Suppress a deliberate hit with `leakcheck:ok` on the line.

**Why local and not a hosted CI job:** the personal list *is* the sensitive
thing. A CI runner would need it, so it would have to be committed or stored as
a hosted secret — either defeats the purpose. A hosted job can only run the
generic rules, which GitHub's own secret scanning already does better.

**Limits, stated plainly.** It checks what you *publish*, not what was already
published. It matches strings, not meaning — a paraphrase of your address
passes. `git push --no-verify` bypasses the hook (and should be a conscious
act). `make pr` runs it against the PR body *before* asking for confirmation.

## Still open (needs the owner — these change GitHub settings)

1. **Secret scanning + push protection** — free on public repos, catches
   provider-format secrets server-side, blocks the push:
   ```bash
   gh api -X PATCH repos/buscandoaverroes/eki-bin \
     -f 'security_and_analysis[secret_scanning][status]=enabled' \
     -f 'security_and_analysis[secret_scanning_push_protection][status]=enabled'
   ```
2. **Dependabot security updates** (Settings → Code security) — the pins above
   are only useful if something tells you when one is vulnerable.
3. **Branch protection on `main` (and `dev`)** — require a PR, block force
   pushes. Part of the tabled repo-hygiene pass (`dev-status.md`). Adding
   `CODEOWNERS` for `scripts/` and `Makefile` makes review of the files that
   run with your credentials mandatory rather than habitual.

## Standing habits

- Read any diff touching `scripts/` or the `Makefile` before running it.
- `make pr` shows the body — read it, do not skim it.
- Before gifting a unit: blank `WIFI_*` in the `config.py` you upload, and
  check the schedule on it is only the one intended.
