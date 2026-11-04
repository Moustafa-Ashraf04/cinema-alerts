# Cinema alerts

A free bot that sends you a Telegram message when **Scene Cinemas** opens bookings for a movie you're waiting for.

You tell it what to watch from Telegram. Every 15 minutes it checks the cinema websites on GitHub's servers. When a movie you picked gets bookable showtimes on a date you picked, you get the times and a **Book now** button. It only alerts you: it never buys or logs in.

## Tell the bot what to watch

| You send | What happens |
|---|---|
| `/watch dune 23 Dec` | Watch *Dune* on 23 December at all cinemas |
| `/watch avengers 16-20 Dec` | A range of dates (at most 14 days) |
| `/watch spider man 23 Dec cfc` | Only at one cinema (see `/cinemas`) |
| `/list` | Everything you're watching, numbered, with the latest result |
| `/remove 2` | Stop watch number 2 from `/list` |
| `/cinemas` | The cinema short names |
| `/status` | Last check and anything failing |
| `/help` | This list |

- **Put the date last.** Formats that work: `23 Dec`, `Dec 23`, `23-12`, `23/12/2026`, `2026-12-23`, `16-20 Dec`, `today`, `tomorrow`. With no year, it means the next 23 Dec to come.
- **Part of the title is enough.** `dune` and `avengers doomsday` both work. The reply tells you which film(s) it matched. If the film isn't on the cinema's site yet, it keeps checking until it appears.
- **Replies take a while.** The bot reads your messages when it runs, about every 15 minutes, and sometimes later.
- Dates that have passed are removed automatically. Only your chat can give commands.

## What the messages mean

| Message | Meaning |
|---|---|
| 🎟 **Booking is OPEN** | Bookable showtimes on your date. Tap a time, or **Book now** |
| ➕ **New showtimes** | An open movie got extra times. Only the new ones are listed |
| ⚠️ **Problem** | A check failed 3 runs in a row, so the bot can't see if booking opened. Sent once |
| ✅ **Recovered** | Checks work again |
| 💓 **Alive** | Daily at about 09:00 Cairo time. **If it stops, see below** |

## If the 💓 message stops

1. On GitHub, open the repo → **Actions** → **monitor**.
2. If there's a banner saying the workflow is disabled, click **Enable workflow**.
3. If the latest runs are red, open the newest to see why.
4. If runs are green but nothing arrives: **Run workflow** → tick **selftest** → **Run workflow**. If that test message doesn't arrive either, reset the Telegram secrets (`gh secret set TELEGRAM_BOT_TOKEN`, `gh secret set TELEGRAM_CHAT_ID`).

## Pause, restart, logs

- **Pause / restart:** **Actions** → **monitor** → **⋯** → **Disable workflow** / **Enable workflow**.
- **Run once now:** **Actions** → **monitor** → **Run workflow**. Tick **dry_run** to see what it would send without sending.
- **Logs:** open any run → **check** → **Run monitor**. Each line shows a movie, a cinema, a date and `OPEN`, `CLOSED` or `ERROR`.
- **Saved state** (your watches and results): the `state` branch, `state.json`.

## Settings and cinemas: `watches.yaml`

You only need this file to change a setting or add another Scene branch. Movies and dates aren't set here.

- `heartbeat_hour`: the hour for the 💓 message (Cairo time).
- `error_alert_after`: failed runs before a ⚠️ Problem.
- `notify_new_showtimes`: `true` or `false`.
- **Add a Scene branch:** copy a cinema block and change `id`, `branch` (the part before `.scenecinemas.com`) and `name`.

If the file has a mistake, the bot sends a ⚠️ message naming the line and checks nothing until it's fixed.

## Known limits

- **Not instant.** Checks are every 15 minutes, and GitHub often starts them 5–20 minutes late.
- **Scene only.** Vox and Premiere block bots (details in [docs/DISCOVERY.md](docs/DISCOVERY.md)).
- **Sold-out seats:** not seen on Scene's site yet. A time without a booking link counts as not bookable.

## If the site changes

The bot sends ⚠️ **Problem** instead of guessing. To fix it (or ask Claude Code to):

1. Save the new page into `tests/fixtures/scene/`.
2. Update `monitor/scene.py` until it reads the page.
3. Run `python -m pytest -q`. Every test must pass.
4. Commit. The next run sends ✅ **Recovered**.

## Keepalive

GitHub switches off schedules in public repos after 60 days without activity. Every 30 days the workflow re-enables itself through GitHub's API and notes the date in `state.json`. That's why it has the `actions: write` permission.

## Files

- `monitor/scene.py`: reads Scene's pages
- `monitor/commands.py`: the Telegram commands
- `monitor/state.py`: decides when to alert
- `monitor/notify.py`: sends Telegram messages
- `monitor/main.py`: one run, start to finish
- `monitor/config.py`, `models.py`, `fetch.py`: settings, data types, polite web requests
- `.github/workflows/monitor.yml`: runs it every 15 minutes
- `tests/`: tests on saved pages (`python -m pytest -q`)
