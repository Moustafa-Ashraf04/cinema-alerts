# Cinema alerts

A free bot that sends you a Telegram message when a cinema opens bookings for a movie you're waiting for.

It checks **Scene Cinemas** (Cairo Festival City and District 5) every 15 minutes on GitHub's servers. When a movie you're watching gets bookable showtimes on a date you picked, you get a message with the times and a **Book now** button. It only alerts you: it never buys tickets or logs in.

Vox and Premiere are switched off for now because their websites block bots. See [docs/DISCOVERY.md](docs/DISCOVERY.md).

---

## Day to day: talk to the bot in Telegram

| You send | What happens |
|---|---|
| `/watch dune 23 Dec` | Watch *Dune* on 23 December at all cinemas |
| `/watch avengers 16-20 Dec` | Watch 16 to 20 December (at most 14 days) |
| `/watch spider man 2026-12-23 cfc` | Only at Scene Cairo Festival City (`d5` = District 5) |
| `/list` | What's being watched, numbered, with the latest result |
| `/remove 3` | Stop watch number 3 from `/list` |
| `/cinemas` | The short cinema names you can use |
| `/status` | Last check and anything that's failing |
| `/help` | This list |

- **Put the date last.** Formats that work: `23 Dec`, `Dec 23`, `23-12`, `23/12/2026`, `2026-12-23`, `16-20 Dec`, `today`, `tomorrow`. A date without a year means the next 23 Dec to come.
- **The movie name can be part of the title.** `dune`, `avengers doomsday` and `spider man` all work. The bot's reply tells you which film(s) it matched. If the film isn't listed on Scene's site yet, it keeps checking by name until it appears.
- **Replies aren't instant.** The bot reads your messages when it runs, about every 15 minutes, and sometimes later (see *Known limits*).
- Only your Telegram chat can give commands; anyone else is ignored.
- Dates that have passed are removed automatically.

## What each message means

| Message | Meaning | What to do |
|---|---|---|
| 🎟 **Booking is OPEN** | A watched film has bookable showtimes on your date. Each time is a link; **Book now** opens the movie page | Book! |
| ➕ **New showtimes** | An already open film got extra times. Only the new ones are listed | Optional |
| ⚠️ **Problem** | The same check failed 3 runs in a row, so the bot can't tell whether booking opened. Sent once, not every run | Usually temporary. If it lasts a day, see *If the site changes* |
| ✅ **Recovered** | Checks work again after a Problem | Nothing |
| 💓 **Alive** | Daily at about 09:00 Cairo time: "watching N movies, last check HH:MM" | Nothing. **If this stops arriving, see below** |
| 👀 **Watching …** | Reply to `/watch`, with what it matched and the first result | — |

## If the daily 💓 message stops arriving

Something stopped the bot. Check, in this order:

1. Open the repo on GitHub → **Actions** tab → **monitor** on the left.
2. If you see a yellow banner saying the workflow was disabled, click **Enable workflow**. GitHub disables schedules in public repos after 60 days without activity. The bot re-enables itself every 30 days to prevent this (see *Keepalive*), but this is the fix if it ever slips.
3. If runs are there but red, click the newest one to read what failed.
4. If runs are green but nothing arrives, run a self-test: **Actions → monitor → Run workflow → tick "selftest" → Run workflow**. If that message doesn't arrive, the Telegram secrets need resetting (`gh secret set TELEGRAM_BOT_TOKEN`, `gh secret set TELEGRAM_CHAT_ID`).

## Where to see what it's doing

- **Logs:** GitHub → **Actions** → **monitor** → any run → **check** → **Run monitor**. Each line shows a watch, a cinema, a date and its status: `OPEN`, `CLOSED` or `ERROR`, with the reason.
- **Saved state:** the `state` branch, file `state.json`. It's only updated when something changes.

## Pausing and restarting

- **Pause:** GitHub → **Actions** → **monitor** → **⋯** (top right) → **Disable workflow**.
- **Restart:** same place → **Enable workflow**.
- **Run once now:** **Actions → monitor → Run workflow**. Tick **dry_run** to see what it would send without sending anything.

## Editing `watches.yaml` (optional)

Most of the time `/watch` is easier. `watches.yaml` holds the settings, the cinema list, and any watches you want kept in the file. To edit it on GitHub: open the file → ✏️ pencil → change → **Commit changes**. The next run uses it.

**Worked example.** Watch *Avengers: Doomsday* on opening weekend, IMAX only, at District 5:

```yaml
watches:
  - id: avengers-weekend          # any name, no spaces; must be unique
    movie: Avengers Doomsday      # part of the title is enough
    dates: ["2026-12-17", "2026-12-18", "2026-12-19"]   # always "YYYY-MM-DD" in quotes
    cinemas: [scene-district5]    # optional; leave out for all cinemas
    formats: [IMAX]               # optional; leave out for any format
```

- **Change a date:** edit the list in `dates:`.
- **Stop watching:** delete the whole block, from `- id:` down to its last line.
- **Cinemas** are listed under `cinemas:`. The ids are `scene-cfc` and `scene-district5`. Leave `premiere-americana` and `vox-almaza` at `enabled: false`.
- **Settings:** `heartbeat_hour` (Cairo time of the 💓 message), `error_alert_after` (failed runs before a ⚠️ Problem), and `notify_new_showtimes` (`true`/`false`).

If you make a mistake, the bot doesn't guess. It sends a ⚠️ message naming the line, e.g. `watches.yaml line 9: watch 'x' has a bad date '2026-12-32'`, and checks nothing until it's fixed.

## Known limits

- **Not instant.** Checks are every 15 minutes, and GitHub often starts scheduled runs **5–20 minutes late** (sometimes more when GitHub is busy). Seats for big releases can go fast. The faster option is a free external trigger every 1–2 minutes (ask for the "faster checks" upgrade).
- **Command replies** arrive on the next run, not instantly.
- **Scene only.** Vox (Akamai bot protection) and Premiere (its data API refuses bots) are parked. The code is ready to add them if a polite source turns up.
- **Sold-out seats:** no sold-out showtime has been seen on Scene's site yet, so how they're marked is unknown. A time without a booking link is treated as not bookable.
- **Uses about 1 minute of GitHub's runners per run.** Free and unlimited for public repos.

## If the site changes

Scene may redesign its pages. The bot then reports ⚠️ **Problem** instead of guessing. To fix it (or ask Claude Code to):

1. Save the new page into `tests/fixtures/scene/` (the run log says which page failed).
2. Update the parser in `monitor/providers/scene.py` until it reads the new page.
3. Run the tests: `python -m pytest -q`. They must all pass, using only saved pages.
4. Commit. The next run sends ✅ **Recovered**.

## Keepalive

GitHub switches off scheduled workflows in public repositories after 60 days with no repository activity, and doesn't define exactly what counts as activity. So the workflow doesn't rely on the state commits: every 30 days it calls GitHub's **enable workflow** API on itself, and records the date as `keepalive` in `state.json`. The commonly used keepalive tools take this approach. It needs the `actions: write` permission, for this repo only. GitHub also emails the repo owner before disabling a workflow. And if it ever happens anyway, the missing 💓 message tells you.

---

## For developers

- Tests (no network; real connections fail the test): `python -m pytest -q`
- Dry run (prints messages, saves nothing): `python -m monitor.main --dry-run`
- Telegram self-test: `python -m monitor.main --selftest` (needs `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment; never commit them)
- Rehearse an alert from saved pages: `python -m monitor.main --fixture tests/fixtures/scene/replay_open` (add `--dry-run` to only print)
- Layout: `monitor/providers/` (one file per cinema chain, all with the same `check()` interface), `state.py` (transitions), `notify.py` (Telegram), `commands.py` (bot commands), `main.py` (the run).
- Workflows: `monitor.yml` (every 15 min), `probe.yml` (manual reachability check), `telegram-test.yml` (manual one-off).
- Rules for changes are in [CLAUDE.md](CLAUDE.md).
