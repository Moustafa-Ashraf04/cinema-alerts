# Cinema pre-booking alert bot

## Purpose
Checks Vox Cinemas Egypt showtime pages on a schedule (GitHub Actions, every 15 minutes)
and sends a Telegram alert when a watched movie becomes bookable at a watched branch
on a watched date. Owner: one person in Cairo (Africa/Cairo). Alert-only, never buys.

## Outcome that matters
A missed or late alert is the worst failure. A false alert is bad. A silent failure
(the scraper breaks and nobody knows) is almost as bad as a missed alert.

## Rules
- OPEN means at least one bookable showtime for the exact requested date. A page that
  is unrecognised, from a different date, blocked, or failed is ERROR, never OPEN or CLOSED.
- ERROR never changes stored state. Repeated errors raise one problem alert and, later, one recovery message.
- One request per provider, cinema and date. Clear User-Agent. Timeouts. Back off on 429/503.
- No evasion of blocks: no proxies, spoofed fingerprints or captcha solving. If blocked, stop and tell the owner.
- Secrets only in GitHub Secrets or a local .env that is git-ignored. Never print or commit them.
- The owner edits only watches.yaml. Keep that file simple and validated with readable errors.
- Parsers are tested against saved fixtures in tests/fixtures. When a site changes, add the new
  fixture first, then fix the parser.

## Commands
- Tests: python -m pytest -q
- Dry run: python -m monitor.main --dry-run
- Telegram self-test: python -m monitor.main --selftest
- Rehearse an alert: python -m monitor.main --fixture tests/fixtures/vox/<open file>

## Working agreement
- Small steps, one commit per step, tests green before moving on.
- Report evidence (command output, run links), not guesses. Say plainly what was not tested.
- Ask before: making anything public, deleting data, changing repo or account settings, or adding a new dependency.
