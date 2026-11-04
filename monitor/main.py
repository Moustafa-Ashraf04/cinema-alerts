"""One run: read Telegram commands, check cinemas, compare with saved state, alert, save.

python -m monitor.main [--dry-run] [--selftest] [--state PATH] [--config PATH]
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from . import commands
from .config import ConfigError, load_config
from .fetch import Fetcher
from .models import CheckResult, Status
from .notify import Telegram, TelegramError, e, fmt_heartbeat, fmt_new, fmt_open, fmt_problem, fmt_recovered
from .scene import SceneProvider, normalize
from .state import entry_key, load_state, save_state, transition

log = logging.getLogger("monitor")


def run(tg, fetcher, *, config_path="watches.yaml", state_path="state.json", dry_run=False,
        now: datetime | None = None) -> int:
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        log.error("config error: %s", exc)
        tg.send(f"⚠️ <b>Problem</b>: watches.yaml has an error, so nothing was checked.\n<code>{e(str(exc))}</code>")
        return 2

    s = cfg.settings
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(s.tz)
    today = local.date()
    now_s = now.isoformat(timespec="seconds")
    state, problem = load_state(state_path)
    failures = 0

    def send(text: str, button=None) -> bool:
        nonlocal failures
        try:
            tg.send(text, button)
            return True
        except TelegramError as exc:
            log.error("%s", exc)
            failures += 1
            return False

    if problem:
        send("⚠️ <b>Problem</b>: " + e(problem))

    # 1. commands from Telegram
    try:
        updates = tg.get_updates(int(state["telegram_offset"]) + 1)
    except TelegramError as exc:
        log.error("%s", exc)
        updates = []
    replies = commands.process_updates(updates, tg.chat_id, state, cfg, today)

    # 2. forget past dates, then check each (cinema, movie) once for all its dates
    for w in state["watches"]:
        w["dates"] = [d for d in w["dates"] if d >= today.isoformat()]
    state["watches"] = [w for w in state["watches"] if w["dates"]]
    watches = commands.watches(state)

    def targets(w):
        return [c for c in (w.cinemas or [c.id for c in cfg.enabled_cinemas]) if cfg.cinema(c) and cfg.cinema(c).enabled]

    groups: dict[tuple[str, str], set] = defaultdict(set)
    for w in watches:
        for cid in targets(w):
            groups[(cid, normalize(w.movie))].update(w.dates)

    scene = SceneProvider(fetcher)
    results = {}
    for (cid, query), dates in sorted(groups.items()):
        try:
            results[(cid, query)] = scene.check(cfg.cinema(cid), query, sorted(dates))
        except Exception as exc:  # a bug must not stop the other checks
            log.exception("check crashed for %s / %s", cid, query)
            results[(cid, query)] = {d: CheckResult(Status.ERROR, reason=f"crashed: {type(exc).__name__}") for d in dates}

    # 3. compare with saved state and alert
    problems, problem_keys, recovered, live = [], [], [], set()
    for w in watches:
        for cid in targets(w):
            cinema = cfg.cinema(cid)
            for d in w.dates:
                key = entry_key(w.id, cid, d)
                live.add(key)
                res = results[(cid, normalize(w.movie))][d]
                prev = state["entries"].get(key)
                entry, events = transition(prev, res, notify_new=s.notify_new_showtimes,
                                           error_after=s.error_alert_after, now=now_s)
                entry["titles"] = res.titles or (prev or {}).get("titles", [])
                log.info("%s | %s | %s | %s | %d bookable%s", w.movie, cid, d, res.status.value, len(res.bookable),
                         f" | {res.reason}" if res.reason else "")
                sent = True
                for ev in events:
                    if ev.kind == "open":
                        sent &= send(*fmt_open(w.movie, res.titles, cinema, d, ev.showtimes, res.url))
                    elif ev.kind == "new":
                        sent &= send(*fmt_new(w.movie, res.titles, cinema, d, ev.showtimes, res.url))
                    elif ev.kind == "problem":
                        problems.append((w.movie, cinema, d, res.reason))
                        problem_keys.append(key)
                    else:
                        recovered.append((w.movie, cinema, d))
                if sent:
                    state["entries"][key] = entry
                elif prev is not None:  # alert didn't go out: keep the old entry so it's retried next run
                    state["entries"][key] = prev
    if problems and not send(fmt_problem(problems, s.error_alert_after)):
        for key in problem_keys:
            state["entries"][key]["problem_alerted"] = False
    if recovered:
        send(fmt_recovered(recovered))
    state["entries"] = {k: v for k, v in state["entries"].items() if k in live}

    # 4. replies to commands (after the checks, so a new watch shows its first result)
    for r in replies:
        w = next((x for x in watches if x.id == r.watch_id), None)
        send(r.text + ("\n" + commands.watch_summary(state, w, cfg) if w else ""))

    # 5. daily heartbeat
    if local.hour >= s.heartbeat_hour and state.get("last_heartbeat") != today.isoformat():
        failing = sum(1 for v in state["entries"].values() if v.get("errors"))
        if send(fmt_heartbeat(len(watches), local.strftime("%H:%M Cairo time"), failing)):
            state["last_heartbeat"] = today.isoformat()

    state["last_check"] = now_s
    if not dry_run:
        save_state(state_path, state)
    log.info("done: %d watches, %d checks, %d requests%s", len(watches), len(live), fetcher.requests_made,
             " (dry run: nothing saved)" if dry_run else "")
    return 1 if failures else 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    p = argparse.ArgumentParser(prog="python -m monitor.main")
    p.add_argument("--dry-run", action="store_true", help="print messages instead of sending; save nothing")
    p.add_argument("--selftest", action="store_true", help="send one test message and exit")
    p.add_argument("--state", default="state.json")
    p.add_argument("--config", default="watches.yaml")
    args = p.parse_args(argv)
    tg = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""),
                  dry_run=args.dry_run)
    try:
        if args.selftest:
            tg.send("🎬 Cinema bot self-test: messages reach you.")
            log.info("self-test message sent")
            return 0
        return run(tg, Fetcher(), config_path=args.config, state_path=args.state, dry_run=args.dry_run)
    except TelegramError as exc:
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
