"""Telegram commands: /watch, /list, /remove, /cinemas, /status, /help.

Read with getUpdates at the start of each run. Only messages from the owner's
chat are acted on; everything else is ignored.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, timedelta

from .matching import normalize
from .models import Watch
from .notify import e, fmt_date

log = logging.getLogger(__name__)

MAX_RANGE_DAYS = 14
MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], start=1)}
ALIASES = {"d5": "district5", "festival": "cfc"}

HELP = (
    "<b>Commands</b>\n"
    "/watch <i>movie</i> <i>date</i> [<i>cinema</i>]: alert me when booking opens\n"
    "   e.g. <code>/watch dune 23 Dec</code>\n"
    "   <code>/watch avengers 16-20 Dec cfc</code>\n"
    "   <code>/watch spider man 2026-12-23</code>\n"
    "   Dates: 23 Dec, 23-12, 2026-12-23, 16-20 Dec, today, tomorrow\n"
    "   No cinema = all cinemas. Put the date last.\n"
    "/list: what I'm watching\n"
    "/remove <i>number</i>: stop a watch from /list\n"
    "/cinemas: cinema names you can use\n"
    "/status: last check and any problems\n\n"
    "I read commands each time I run (about every 15 minutes), so replies can take a while."
)


class CommandError(Exception):
    pass


@dataclass
class Reply:
    text: str
    watch_id: str | None = None  # main adds the first check's result for new watches


def _month(name: str) -> int | None:
    return MONTHS.get(name.lower().rstrip(".")[:3]) if len(name) >= 3 else None


def _infer(day: int, month: int, year: int | None, today: date) -> date:
    if year is not None:
        return date(year if year > 99 else 2000 + year, month, day)
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def parse_date_spec(spec: str, today: date) -> list[date] | None:
    """Return the dates a spec means, or None if it is not a date."""
    s = spec.strip().lower()
    try:
        if s == "today":
            return [today]
        if s == "tomorrow":
            return [today + timedelta(days=1)]
        if m := re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s):
            return [date(int(m[1]), int(m[2]), int(m[3]))]
        if m := re.fullmatch(r"(\d{1,2})[/.-](\d{1,2})(?:[/.-](\d{2}|\d{4}))?", s):
            return [_infer(int(m[1]), int(m[2]), int(m[3]) if m[3] else None, today)]
        m = (re.fullmatch(r"(\d{1,2})(?:\s*-\s*(\d{1,2}))?\s+([a-z]+\.?)(?:\s+(\d{4}))?", s)
             or re.fullmatch(r"([a-z]+\.?)\s+(\d{1,2})(?:\s*-\s*(\d{1,2}))?(?:\s+(\d{4}))?", s))
        if m:
            if m[1].isdigit():
                d1, d2, mon, yr = m[1], m[2], m[3], m[4]
            else:
                mon, d1, d2, yr = m[1], m[2], m[3], m[4]
            month = _month(mon)
            if not month:
                return None
            start = _infer(int(d1), month, int(yr) if yr else None, today)
            if not d2:
                return [start]
            end = date(start.year, month, int(d2))
            if end < start:
                return None
            if (end - start).days + 1 > MAX_RANGE_DAYS:
                raise CommandError(f"That range is too long; the most is {MAX_RANGE_DAYS} days.")
            return [start + timedelta(days=i) for i in range((end - start).days + 1)]
    except ValueError:  # e.g. 31 Feb
        return None
    return None


def resolve_cinemas(token: str, config) -> list[str]:
    t = ALIASES.get(token.lower(), token.lower())
    enabled = config.enabled_cinemas
    for c in enabled:
        if t in (c.id.lower(), c.branch.lower()):
            return [c.id]
    by_provider = [c.id for c in enabled if c.provider == t]
    return by_provider


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
        raise CommandError(f"{e(fmt_date(dates[-1]))} has already passed.")
    return movie, future, cinemas


def all_watches(state: dict, config) -> list[Watch]:
    return list(config.watches) + [Watch.from_dict(w) for w in state["watches"]]


def cinema_names(watch: Watch, config) -> str:
    if not watch.cinemas:
        return "all cinemas"
    return ", ".join((config.cinema(c).name if config.cinema(c) else c) for c in watch.cinemas)


def fmt_dates(dates: list[date]) -> str:
    if len(dates) > 2 and all((b - a).days == 1 for a, b in zip(dates, dates[1:])):
        return f"{dates[0]:%a %d %b} to {dates[-1]:%a %d %b}"
    return ", ".join(f"{d:%a %d %b}" for d in dates)


def watch_summary(state: dict, watch: Watch, config) -> str:
    """One line per cinema: what the latest check found."""
    lines = []
    targets = watch.cinemas or [c.id for c in config.enabled_cinemas]
    for cid in targets:
        cinema = config.cinema(cid)
        statuses, titles = [], set()
        for d in watch.dates:
            entry = state["entries"].get(f"{watch.id}|{cid}|{d.isoformat()}") or {}
            titles.update(entry.get("titles", []))
            if entry.get("errors"):
                statuses.append("checking failed")
            else:
                statuses.append({"OPEN": "OPEN", "CLOSED": "not open yet"}.get(entry.get("status"), "not checked yet"))
        uniq = sorted(set(statuses))
        found = f" ({e(', '.join(sorted(titles)))})" if titles else " (no matching film listed yet)"
        lines.append(f"   {e(cinema.name if cinema else cid)}: {e(', '.join(uniq))}{found}")
    return "\n".join(lines)


def process_updates(updates: list[dict], chat_id: str, state: dict, config, today: date) -> list[Reply]:
    replies: list[Reply] = []
    for u in sorted(updates, key=lambda u: u.get("update_id", 0)):
        state["telegram_offset"] = max(state.get("telegram_offset", 0), int(u.get("update_id", 0)))
        msg = u.get("message") or {}
        if str((msg.get("chat") or {}).get("id", "")) != str(chat_id):
            log.info("ignored a message from another chat")
            continue
        text = (msg.get("text") or "").strip()
        try:
            reply = handle(text, state, config, today)
        except CommandError as exc:
            reply = Reply("❌ " + str(exc))
        if reply:
            replies.append(reply)
    return replies


def handle(text: str, state: dict, config, today: date) -> Reply | None:
    if not text.startswith("/"):
        return Reply("Send /help to see what I can do.")
    head, _, args = text.partition(" ")
    cmd = head.split("@")[0].lower()

    if cmd in ("/start", "/help"):
        return Reply(HELP)

    if cmd == "/cinemas":
        lines = ["<b>Cinemas</b> (use the short name after a date):"]
        for c in config.cinemas:
            lines.append(f"• {e(c.name)}: <code>{e(c.branch if c.enabled else c.id)}</code>"
                         + ("" if c.enabled else " (parked: site blocks the bot)"))
        lines.append("Or <code>scene</code> for every Scene branch.")
        return Reply("\n".join(lines))

    if cmd == "/watch":
        movie, dates, cinemas = parse_watch(args, config, today)
        key = (normalize(movie), dates, sorted(cinemas))
        for w in all_watches(state, config):
            if (normalize(w.movie), [d for d in w.dates if d >= today], sorted(w.cinemas)) == key:
                return Reply(f"I'm already watching <b>{e(movie)}</b> for {e(fmt_dates(dates))}.")
        wid = f"tg-{state['next_watch_no']}"
        state["next_watch_no"] += 1
        watch = Watch(wid, movie, dates, cinemas, [], "telegram")
        state["watches"].append(watch.to_dict())
        return Reply(f"👀 Watching <b>{e(movie)}</b> on {e(fmt_dates(dates))} at {e(cinema_names(watch, config))}.\n"
                     f"First check:", watch_id=wid)

    if cmd == "/list":
        watches = all_watches(state, config)
        if not watches:
            return Reply("I'm not watching anything. Add one with <code>/watch dune 23 Dec</code>.")
        lines = ["<b>Watching</b>"]
        for i, w in enumerate(watches, start=1):
            dates = [d for d in w.dates if d >= today] or w.dates
            src = "" if w.source == "telegram" else " (from watches.yaml)"
            lines.append(f"{i}. <b>{e(w.movie)}</b>: {e(fmt_dates(dates))}, {e(cinema_names(w, config))}{src}")
            lines.append(watch_summary(state, w, config))
        return Reply("\n".join(lines))

    if cmd == "/remove":
        watches = all_watches(state, config)
        if not args.strip().isdigit() or not 1 <= int(args) <= len(watches):
            raise CommandError("Send <code>/remove N</code> with a number from /list.")
        w = watches[int(args) - 1]
        if w.source != "telegram":
            raise CommandError(f"<b>{e(w.movie)}</b> comes from watches.yaml; remove it there.")
        state["watches"] = [x for x in state["watches"] if x["id"] != w.id]
        return Reply(f"🗑 Stopped watching <b>{e(w.movie)}</b>.")

    if cmd == "/status":
        entries = state["entries"]
        failing = [k for k, v in entries.items() if v.get("errors")]
        lines = [f"Last saved check: {e(state.get('last_check') or 'never')} (UTC)",
                 f"Watches: {len(all_watches(state, config))}, checks: {len(entries)}, failing: {len(failing)}"]
        for k in failing[:10]:
            lines.append(f"• {e(k)}: {e(str(entries[k].get('last_error', ''))[:150])}")
        return Reply("\n".join(lines))

    return Reply("I don't know that command. Send /help.")
