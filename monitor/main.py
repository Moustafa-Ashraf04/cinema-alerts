"""Entry point: read commands, check cinemas, diff against state, notify, save.

python -m monitor.main [--dry-run] [--selftest] [--fixture DIR] [--state PATH] [--config PATH]
"""

from __future__ import annotations

import argparse
import dataclasses
import logging
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone

from . import commands
from .config import ConfigError, load_config
from .matching import normalize
from .models import CheckResult, Status
from .notify import Telegram, TelegramError, fmt_heartbeat, fmt_new, fmt_open, fmt_problem, fmt_recovered
from .providers import make_providers
from .providers.base import Fetcher, FixtureFetcher
from .state import empty_state, entry_key, load_state, save_state, transition

log = logging.getLogger("monitor")


def parse_args(argv=None):
    p = argparse.ArgumentParser(prog="python -m monitor.main", description="Cinema pre-booking alert bot")
    p.add_argument("--dry-run", action="store_true", help="print messages instead of sending; don't save state")
    p.add_argument("--selftest", action="store_true", help="send one test message and exit")
    p.add_argument("--fixture", metavar="DIR", help="use saved pages (DIR/manifest.json) instead of the network")
    p.add_argument("--state", metavar="PATH", help="state file (default state.json; in --fixture mode, none)")
    p.add_argument("--config", metavar="PATH", help="config file (default watches.yaml, or DIR/watches.yaml with --fixture)")
    return p.parse_args(argv)


def apply_formats(res: CheckResult, formats: list[str]) -> CheckResult:
    if not formats or res.status == Status.ERROR:
        return res
    wanted = [f.lower() for f in formats]
    kept = [s for s in res.showtimes if any(w in s.format.lower() for w in wanted)]
    if res.status == Status.OPEN and not any(not s.sold_out for s in kept):
        return dataclasses.replace(res, status=Status.CLOSED, showtimes=kept,
                                   reason=f"no showtimes in {', '.join(formats)}")
    return dataclasses.replace(res, showtimes=kept)


def run(args, tg: Telegram, fetcher, now: datetime | None = None) -> int:
    config_path = args.config or (os.path.join(args.fixture, "watches.yaml")
                                  if args.fixture and os.path.exists(os.path.join(args.fixture, "watches.yaml"))
                                  else "watches.yaml")
    try:
        cfg = load_config(config_path)
    except ConfigError as exc:
        log.error("config error: %s", exc)
        try:
            tg.send(f"⚠️ <b>Problem</b>: watches.yaml has an error, so nothing was checked.\n<code>{commands.e(str(exc))}</code>")
        except TelegramError as texc:
            log.error("%s", texc)
        return 2

    if args.selftest:
        tg.send("🎬 Cinema bot self-test: messages reach you.")
        log.info("self-test message sent")
        return 0

    tz = cfg.settings.tz
    now = now or datetime.now(timezone.utc)
    local = now.astimezone(tz)
    today = local.date()
    now_s = now.isoformat(timespec="seconds")

    use_state_file = bool(args.state) or not args.fixture
    state_path = args.state or "state.json"
    if use_state_file:
        state, problem = load_state(state_path)
    else:
        state, problem = empty_state(), None
    persist = use_state_file and not args.dry_run
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
        send("⚠️ <b>Problem</b>: " + commands.e(problem))

    # 1. commands from Telegram
    replies: list[commands.Reply] = []
    if not args.fixture and tg.configured:
        try:
            updates = tg.get_updates(int(state.get("telegram_offset", 0)) + 1)
        except TelegramError as exc:
            log.error("%s", exc)
            updates = []
        replies = commands.process_updates(updates, tg.chat_id, state, cfg, today)

    # 2. drop past dates, then collect what to check
    for w in state["watches"]:
        w["dates"] = [d for d in w["dates"] if d >= today.isoformat()]
    state["watches"] = [w for w in state["watches"] if w["dates"]]
    watches = []
    for w in commands.all_watches(state, cfg):
        w.dates = [d for d in w.dates if d >= today]
        if w.dates:
            watches.append(w)

    def targets(w):
        return [c for c in (w.cinemas or [c.id for c in cfg.enabled_cinemas]) if cfg.cinema(c) and cfg.cinema(c).enabled]

    groups: dict[tuple[str, str], set] = defaultdict(set)
    for w in watches:
        for cid in targets(w):
            groups[(cid, normalize(w.movie))].update(w.dates)

    providers = make_providers(fetcher)
    results: dict[tuple[str, str], dict] = {}
    for (cid, query), dates in sorted(groups.items()):
        cinema = cfg.cinema(cid)
        provider = providers.get(cinema.provider)
        ds = sorted(dates)
        if provider is None:
            results[(cid, query)] = {d: CheckResult(Status.ERROR, reason="provider not available") for d in ds}
            continue
        try:
            results[(cid, query)] = provider.check(cinema, query, ds)
        except Exception as exc:  # a bug must not stop the other checks
            log.exception("check crashed for %s / %s", cid, query)
            results[(cid, query)] = {d: CheckResult(Status.ERROR, reason=f"crashed: {type(exc).__name__}") for d in ds}

    # 3. transitions and alerts
    s = cfg.settings
    problems, problem_keys, recovered = [], [], []
    live = set()
    for w in watches:
        for cid in targets(w):
            cinema = cfg.cinema(cid)
            for d in w.dates:
                key = entry_key(w.id, cid, d)
                live.add(key)
                res = apply_formats(results[(cid, normalize(w.movie))][d], w.formats)
                prev = state["entries"].get(key)
                entry, events = transition(prev, res, notify_new=s.notify_new_showtimes,
                                           error_after=s.error_alert_after, now=now_s)
                entry["titles"] = res.titles or (prev or {}).get("titles", [])
                log.info("%s | %s | %s | %s | %d bookable%s", w.id, cid, d, res.status.value, len(res.bookable),
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
                    elif ev.kind == "recovered":
                        recovered.append((w.movie, cinema, d))
                if sent:
                    state["entries"][key] = entry
                elif prev is not None:  # keep the old entry so the alert is tried again next run
                    state["entries"][key] = prev
    if problems and not send(fmt_problem(problems, s.error_alert_after)):
        for key in problem_keys:
            state["entries"][key]["problem_alerted"] = False
    if recovered:
        send(fmt_recovered(recovered))
    for key in list(state["entries"]):
        if key not in live:
            del state["entries"][key]

    # 4. replies to commands (after the checks, so new watches show their first result)
    for r in replies:
        text = r.text
        if r.watch_id:
            w = next((x for x in commands.all_watches(state, cfg) if x.id == r.watch_id), None)
            if w:
                text += "\n" + commands.watch_summary(state, w, cfg)
        send(text)

    # 5. daily heartbeat
    if not args.fixture and local.hour >= s.heartbeat_hour and state.get("last_heartbeat") != today.isoformat():
        failing = sum(1 for v in state["entries"].values() if v.get("errors"))
        if send(fmt_heartbeat(len(watches), local.strftime("%H:%M Cairo time"), failing)):
            state["last_heartbeat"] = today.isoformat()

    state["last_check"] = now_s
    if persist:
        save_state(state_path, state)
    log.info("done: %d watches, %d checks, %d requests%s", len(watches), len(live), fetcher.requests_made,
             "" if persist else " (state not saved)")
    return 1 if failures else 0


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s", stream=sys.stdout)
    args = parse_args(argv)
    tg = Telegram(os.environ.get("TELEGRAM_BOT_TOKEN", ""), os.environ.get("TELEGRAM_CHAT_ID", ""),
                  dry_run=args.dry_run)
    fetcher = FixtureFetcher(args.fixture) if args.fixture else Fetcher()
    try:
        return run(args, tg, fetcher)
    except TelegramError as exc:  # e.g. --selftest without secrets
        log.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
