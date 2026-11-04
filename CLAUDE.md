# Cinema pre-booking alert bot

## Purpose
Checks Scene Cinemas showtime pages every 15 minutes (GitHub Actions) and sends a Telegram
alert when a movie the owner is watching becomes bookable on a date they picked.
Movies and dates come only from the owner's Telegram /watch commands; nothing is hard-coded.
Owner: one person in Cairo (Africa/Cairo). Alert-only, never buys.

## Outcome that matters
A missed or late alert is the worst failure. A false alert is bad. A silent failure
(the scraper breaks and nobody knows) is almost as bad as a missed alert.

## Rules
- OPEN means at least one bookable showtime for the exact requested date. A page that
  is unrecognised, from a different date, blocked, or failed is ERROR, never OPEN or CLOSED.
- ERROR never changes stored state. Repeated errors raise one problem alert and, later, one recovery message.
- One request per page per run (the fetcher caches). Clear User-Agent. Timeouts. Back off on 429/503.
- No evasion of blocks: no proxies, spoofed fingerprints or captcha solving. If blocked, stop and tell the owner.
- Secrets only in GitHub Secrets or a local .env that is git-ignored. Never print or commit them.
- Keep it simple: few files, no unused code, nothing fixed in code that the owner might want to change.
- Parsers are tested against saved pages in tests/fixtures. When a site changes, add the new
  page first, then fix the parser.
- Commits are authored by the owner only. No Claude "Co-Authored-By" lines or other Claude attribution.

## Commands
- Tests: python -m pytest -q
- Dry run: python -m monitor.main --dry-run
- Telegram self-test: python -m monitor.main --selftest

## Working agreement
- Small steps, tests green before moving on.
- Report evidence (command output, run links), not guesses. Say plainly what was not tested.
- Ask before: making anything public, deleting data, changing repo or account settings, or adding a new dependency.
