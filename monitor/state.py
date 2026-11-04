"""State file (state.json on the `state` branch): load, save and transitions."""

from __future__ import annotations

import copy
import json
import logging
import os
from dataclasses import dataclass, field
from datetime import date

from .models import CheckResult, Showtime, Status

log = logging.getLogger(__name__)

VERSION = 1


def empty_state() -> dict:
    return {
        "version": VERSION,
        "watches": [],  # added with /watch in Telegram
        "next_watch_no": 1,
        "telegram_offset": 0,
        "entries": {},  # entry_key -> entry
        "last_check": None,
        "last_heartbeat": None,
        "keepalive": None,
    }


def load_state(path: str) -> tuple[dict, str | None]:
    """Return (state, problem). Missing file = first run. A corrupt file is moved aside."""
    if not os.path.exists(path):
        return empty_state(), None
    try:
        with open(path, encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict) or state.get("version") != VERSION or not isinstance(state.get("entries"), dict):
            raise ValueError("unexpected layout")
    except (ValueError, OSError) as exc:
        corrupt = os.path.join(os.path.dirname(path) or ".", "state.corrupt.json")
        os.replace(path, corrupt)
        log.error("state file unreadable (%s), moved to %s", type(exc).__name__, corrupt)
        return empty_state(), "The saved state was unreadable, so it was moved to state.corrupt.json and the bot started fresh."
    merged = empty_state()
    merged.update(state)
    return merged, None


def save_state(path: str, state: dict) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)


def entry_key(watch_id: str, cinema_id: str, d: date) -> str:
    return f"{watch_id}|{cinema_id}|{d.isoformat()}"


@dataclass
class Event:
    kind: str  # "open", "new", "problem", "recovered"
    showtimes: list[Showtime] = field(default_factory=list)


def transition(entry: dict | None, result: CheckResult, *, notify_new: bool, error_after: int,
               now: str) -> tuple[dict, list[Event]]:
    """Pure function: previous entry + this run's result -> new entry + events to announce."""
    e = copy.deepcopy(entry) if entry else {
        "status": None, "showtimes": [], "first_open": None, "errors": 0, "problem_alerted": False, "last_ok": None,
    }
    events: list[Event] = []

    if result.status == Status.ERROR:  # never changes the stored status
        e["errors"] += 1
        e["last_error"] = result.reason
        if e["errors"] >= error_after and not e["problem_alerted"]:
            e["problem_alerted"] = True
            events.append(Event("problem"))
        return e, events

    if e["problem_alerted"]:
        events.append(Event("recovered"))
    e["errors"] = 0
    e["problem_alerted"] = False
    e.pop("last_error", None)
    e["last_ok"] = now

    bookable = result.bookable
    if result.status == Status.OPEN:
        stored = [Showtime.from_dict(s) for s in e["showtimes"]]
        known = {s.key for s in stored}
        if e["status"] != Status.OPEN.value:
            events.append(Event("open", bookable))
            e["first_open"] = e["first_open"] or now
        elif notify_new:
            new = [s for s in bookable if s.key not in known]
            if new:
                events.append(Event("new", new))
        if result.partial:  # some pages failed: keep what we knew so they don't look "new" later
            keep = {s.key: s for s in stored}
            keep.update({s.key: s for s in bookable})
            bookable = list(keep.values())
        e["status"] = Status.OPEN.value
        e["showtimes"] = [s.to_dict() for s in bookable]
    else:
        e["status"] = Status.CLOSED.value
        e["showtimes"] = []
    return e, events
