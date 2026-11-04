"""Telegram commands: /watch, /list, /remove, /cinemas, /status, /help.

Read at the start of each run. Only messages from the owner's chat are acted on.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .models import Watch
from .notify import e
from .scene import normalize

log = logging.getLogger(__name__)

MAX_RANGE_DAYS = 14
MONTHS = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]

HELP = (
    "<b>Commands</b>\n"
    "/watch <i>movie</i> <i>date</i> [<i>cinema</i>]: alert me when booking opens\n"
    "   <code>/watch dune 23 Dec</code>\n"
    "   <code>/watch avengers 16-20 Dec cfc</code>\n"
    "   Dates: 23 Dec, 23-12, 2026-12-23, 16-20 Dec, today, tomorrow\n"
    "   No cinema = all cinemas. Put the date last.\n"
    "/list: what I'm watching\n"
    "/remove <i>number</i>: stop a watch from /list\n"
    "/cinemas: cinema names you can use\n"
    "/status: last check and any problems\n\n"
    "I read messages each time I run (about every 15 minutes), so replies can take a while."
)


class CommandError(Exception):
    pass


@dataclass
class Reply:
    text: str
    watch_id: str | None = None  # main adds the first check's result for a new watch


def _date(day: int, month: int, year: int | None, today: date) -> date:
    if year is not None:
        return date(year if year > 99 else 2000 + year, month, day)
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)  # no year = the next one to come


def parse_date_spec(spec: str, today: date) -> list[date] | None:
    """The dates a spec means, or None if it isn't a date."""
    s = spec.strip().lower()
    try:
        if s in ("today", "tomorrow"):
            return [today + timedelta(days=s == "tomorrow")]
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
            return [date(int(m[1]), int(m[2]), int(m[3]))]
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?", s):
            return [_date(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, today)]
        if m := re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s+([a-z]+)\.?(?:\s+(\d{4}))?", s):
            d1, d2, mon, yr = m.groups()
        elif m := re.fullmatch(r"([a-z]+)\.?\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?(?:\s+(\d{4}))?", s):
            mon, d1, d2, yr = m.groups()
        else:
            return None
        if len(mon) < 3 or mon[:3] not in MONTHS:
            return None
        month = MONTHS.index(mon[:3]) + 1
        start = _date(int(d1), month, int(yr) if yr else None, today)
        end = date(start.year, month, int(d2)) if d2 else start
        if end < start:
            return None
        if (end - start).days >= MAX_RANGE_DAYS:
            raise CommandError(f"That range is too long; the most is {MAX_RANGE_DAYS} days.")
        return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    except ValueError:  # e.g. 31 Feb
        return None


def resolve_cinemas(token: str, config) -> list[str]:
    """A cinema id, a branch (cfc), or a chain name (scene) -> cinema ids."""
    t = token.lower()
    for c in config.enabled_cinemas:
        if t in (c.id.lower(), c.branch.lower()):
            return [c.id]
    return [c.id for c in config.enabled_cinemas if c.provider == t]


def parse_watch(args: str, config, today: date) -> tuple[str, list[date], list[str]]:
    tokens = args.split()
    cinemas: list[str] = []
    if len(tokens) > 1 and (ids := resolve_cinemas(tokens[-1], config)):
        cinemas, tokens = ids, tokens[:-1]
    dates = None
    for n in (4, 3, 2, 1):
        if len(tokens) > n and (dates := parse_date_spec(" ".join(tokens[-n:]), today)):
            tokens = tokens[:-n]
            break
    if not dates:
        raise CommandError("I couldn't find a date. Put it last, e.g. <code>/watch dune 23 Dec</code>.")
    if not cinemas and len(tokens) > 1 and (ids := resolve_cinemas(tokens[-1], config)):
        cinemas, tokens = ids, tokens[:-1]
    movie = " ".join(tokens).strip()
    if len(normalize(movie)) < 2:
        raise CommandError("Which movie? e.g. <code>/watch dune 23 Dec</code>.")
    future = [d for d in dates if d >= today]
    if not future:
        raise CommandError(f"{dates[-1]:%a %d %b %Y} has already passed.")
    return movie, future, cinemas


def watches(state: dict) -> list[Watch]:
    return [Watch.from_dict(w) for w in state["watches"]]


def fmt_dates(dates: list[date]) -> str:
    if len(dates) > 2 and all((b - a).days == 1 for a, b in zip(dates, dates[1:])):
        return f"{dates[0]:%a %d %b} to {dates[-1]:%a %d %b}"
    return ", ".join(f"{d:%a %d %b}" for d in dates)


def cinema_names(watch: Watch, config) -> str:
    if not watch.cinemas:
        return "all cinemas"
    return ", ".join(config.cinema(c).name if config.cinema(c) else c for c in watch.cinemas)


def watch_summary(state: dict, watch: Watch, config) -> str:
    """One line per cinema: what the latest check found."""
    lines = []
    for cid in watch.cinemas or [c.id for c in config.enabled_cinemas]:
        cinema = config.cinema(cid)
        statuses, titles = set(), set()
        for d in watch.dates:
            entry = state["entries"].get(f"{watch.id}|{cid}|{d.isoformat()}") or {}
            titles.update(entry.get("titles", []))
            statuses.add("checking failed" if entry.get("errors") else
                         {"OPEN": "OPEN", "CLOSED": "not open yet"}.get(entry.get("status"), "not checked yet"))
        found = f" ({', '.join(sorted(titles))})" if titles else " (no matching film listed yet)"
        lines.append(f"   {e(cinema.name if cinema else cid)}: {e(', '.join(sorted(statuses)) + found)}")
    return "\n".join(lines)


def process_updates(updates: list[dict], chat_id: str, state: dict, config, today: date) -> list[Reply]:
    replies = []
    for u in sorted(updates, key=lambda u: u.get("update_id", 0)):
        state["telegram_offset"] = max(state.get("telegram_offset", 0), int(u.get("update_id", 0)))
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id", "")) != str(chat_id):
            log.info("ignored a message from another chat")
            continue
        try:
            replies.append(handle((msg.get("text") or "").strip(), state, config, today))
        except CommandError as exc:
            replies.append(Reply("❌ " + str(exc)))
    return replies


def handle(text: str, state: dict, config, today: date) -> Reply:
    if not text.startswith("/"):
        return Reply("Send /help to see what I can do.")
    head, _, args = text.partition(" ")
    cmd = head.split("@")[0].lower()

    if cmd in ("/start", "/help"):
        return Reply(HELP)

    if cmd == "/cinemas":
        lines = ["<b>Cinemas</b> (put the short name after the date):"]
        lines += [f"• {e(c.name)}: <code>{e(c.branch)}</code>" for c in config.enabled_cinemas]
        return Reply("\n".join(lines))

    if cmd == "/watch":
        movie, dates, cinemas = parse_watch(args, config, today)
        for w in watches(state):
            if (normalize(w.movie), w.dates, sorted(w.cinemas)) == (normalize(movie), dates, sorted(cinemas)):
                return Reply(f"I'm already watching <b>{e(movie)}</b> for {e(fmt_dates(dates))}.")
        watch = Watch(f"w{state['next_watch_no']}", movie, dates, cinemas)
        state["next_watch_no"] += 1
        state["watches"].append(watch.to_dict())
        return Reply(f"👀 Watching <b>{e(movie)}</b> on {e(fmt_dates(dates))} at {e(cinema_names(watch, config))}.\n"
                     "First check:", watch_id=watch.id)

    if cmd == "/list":
        ws = watches(state)
        if not ws:
            return Reply("I'm not watching anything. Add one with <code>/watch dune 23 Dec</code>.")
        lines = ["<b>Watching</b>"]
        for i, w in enumerate(ws, start=1):
            lines.append(f"{i}. <b>{e(w.movie)}</b>: {e(fmt_dates(w.dates))}, {e(cinema_names(w, config))}")
            lines.append(watch_summary(state, w, config))
        return Reply("\n".join(lines))

    if cmd == "/remove":
        ws = watches(state)
        if not args.strip().isdigit() or not 1 <= int(args) <= len(ws):
            raise CommandError("Send <code>/remove N</code> with a number from /list.")
        w = ws[int(args) - 1]
        state["watches"] = [x for x in state["watches"] if x["id"] != w.id]
        return Reply(f"🗑 Stopped watching <b>{e(w.movie)}</b>.")

    if cmd == "/status":
        failing = {k: v for k, v in state["entries"].items() if v.get("errors")}
        lines = [f"Last saved check: {e(state.get('last_check') or 'never')} (UTC)",
                 f"Watches: {len(state['watches'])}, checks: {len(state['entries'])}, failing: {len(failing)}"]
        lines += [f"• {e(k)}: {e(str(v.get('last_error', ''))[:150])}" for k, v in list(failing.items())[:10]]
        return Reply("\n".join(lines))

    return Reply("I don't know that command. Send /help.")
