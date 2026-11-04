"""Load and validate watches.yaml, with errors that name the line."""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .models import Cinema, Watch
from .providers import IMPLEMENTED, KNOWN_PROVIDERS, branch_problem


class ConfigError(Exception):
    pass


@dataclass
class Settings:
    timezone: str = "Africa/Cairo"
    heartbeat_hour: int = 9
    error_alert_after: int = 3
    notify_new_showtimes: bool = True

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)


@dataclass
class Config:
    settings: Settings
    cinemas: list[Cinema]
    watches: list[Watch] = field(default_factory=list)

    @property
    def enabled_cinemas(self) -> list[Cinema]:
        return [c for c in self.cinemas if c.enabled]

    def cinema(self, cinema_id: str) -> Cinema | None:
        return next((c for c in self.cinemas if c.id == cinema_id), None)


class _Loader(yaml.SafeLoader):
    """SafeLoader that records the line of every mapping as __line__."""


def _construct_mapping(loader, node, deep=False):
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
    mapping["__line__"] = node.start_mark.line + 1
    mapping["__lines__"] = {k.value: k.start_mark.line + 1 for k, _ in node.value if hasattr(k, "value")}
    return mapping


def _line(m: dict, key: str | None = None):
    """Line of `key` in mapping m, else the line the mapping starts on."""
    return (m.get("__lines__") or {}).get(key) or m.get("__line__")


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def _err(name: str, line, msg: str) -> ConfigError:
    where = f"{name} line {line}" if line else name
    return ConfigError(f"{where}: {msg}")


def _check_keys(name, m: dict, allowed: set[str], what: str):
    for key in m:
        if key not in ("__line__", "__lines__") and key not in allowed:
            raise _err(name, _line(m, key), f"unknown key '{key}' in {what} (allowed: {', '.join(sorted(allowed))})")


def parse_date(value) -> dt.date:
    """Accept a YAML date or a 'YYYY-MM-DD' string."""
    if isinstance(value, dt.datetime):
        raise ValueError(f"'{value}' has a time; use YYYY-MM-DD")
    if isinstance(value, dt.date):
        return value
    if isinstance(value, str):
        return dt.date.fromisoformat(value.strip())
    raise ValueError(f"'{value}' is not a date; use YYYY-MM-DD")


def load_config(path: str) -> Config:
    name = path.rsplit("/", 1)[-1]
    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.load(f, Loader=_Loader)
    except FileNotFoundError:
        raise ConfigError(f"{path} not found")
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        line = mark.line + 1 if mark else None
        raise _err(name, line, f"not valid YAML ({getattr(exc, 'problem', exc)})")
    except ValueError as exc:  # e.g. an unquoted impossible date like 2026-13-01
        raise ConfigError(f"{name}: bad value ({exc}); write dates as \"YYYY-MM-DD\"")
    return parse_config(raw or {}, name)


def parse_config(raw: dict, name: str = "watches.yaml") -> Config:
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}: the file must be a mapping with settings, cinemas and watches")
    _check_keys(name, raw, {"settings", "cinemas", "watches"}, "the top level")

    # settings
    s = raw.get("settings") or {}
    _check_keys(name, s, {"timezone", "heartbeat_hour", "error_alert_after", "notify_new_showtimes"}, "settings")
    settings = Settings(
        timezone=s.get("timezone", "Africa/Cairo"),
        heartbeat_hour=s.get("heartbeat_hour", 9),
        error_alert_after=s.get("error_alert_after", 3),
        notify_new_showtimes=s.get("notify_new_showtimes", True),
    )
    line = s.get("__line__")
    try:
        ZoneInfo(str(settings.timezone))
    except (ZoneInfoNotFoundError, ValueError):
        raise _err(name, line, f"unknown timezone '{settings.timezone}'")
    if not isinstance(settings.heartbeat_hour, int) or not 0 <= settings.heartbeat_hour <= 23:
        raise _err(name, line, "heartbeat_hour must be a whole number from 0 to 23")
    if not isinstance(settings.error_alert_after, int) or settings.error_alert_after < 1:
        raise _err(name, line, "error_alert_after must be a whole number of 1 or more")
    if not isinstance(settings.notify_new_showtimes, bool):
        raise _err(name, line, "notify_new_showtimes must be true or false")

    # cinemas
    cinemas: list[Cinema] = []
    for c in raw.get("cinemas") or []:
        if not isinstance(c, dict):
            raise ConfigError(f"{name}: each cinema must be a mapping with id, provider and branch")
        line = c.get("__line__")
        _check_keys(name, c, {"id", "provider", "branch", "name", "enabled"}, "a cinema")
        cid, provider, branch = c.get("id"), c.get("provider"), c.get("branch")
        if not cid or not isinstance(cid, str):
            raise _err(name, line, "cinema is missing an id")
        if any(x.id == cid for x in cinemas):
            raise _err(name, _line(c, "id"), f"duplicate cinema id '{cid}'")
        if provider not in KNOWN_PROVIDERS:
            raise _err(name, _line(c, "provider"), f"unknown provider '{provider}' (known: {', '.join(sorted(KNOWN_PROVIDERS))})")
        enabled = c.get("enabled", True)
        if not isinstance(enabled, bool):
            raise _err(name, _line(c, "enabled"), "enabled must be true or false")
        if enabled and provider not in IMPLEMENTED:
            raise _err(name, _line(c, "enabled") or _line(c, "provider"), f"provider '{provider}' is parked (its site blocks the bot); set enabled: false")
        problem = branch_problem(provider, branch)
        if problem:
            raise _err(name, _line(c, "branch"), problem)
        cinemas.append(Cinema(cid, provider, str(branch), str(c.get("name") or cid), enabled))
    if not any(c.enabled for c in cinemas):
        raise ConfigError(f"{name}: no enabled cinemas")

    # watches (optional; most are added with /watch in Telegram)
    watches: list[Watch] = []
    for w in raw.get("watches") or []:
        if not isinstance(w, dict):
            raise ConfigError(f"{name}: each watch must be a mapping with id, movie and dates")
        line = w.get("__line__")
        _check_keys(name, w, {"id", "movie", "dates", "cinemas", "formats"}, "a watch")
        wid = w.get("id")
        if not wid or not isinstance(wid, str):
            raise _err(name, line, "watch is missing an id")
        if wid.startswith("tg-"):
            raise _err(name, line, f"watch id '{wid}' can't start with 'tg-' (reserved for Telegram watches)")
        if any(x.id == wid for x in watches):
            raise _err(name, _line(w, "id"), f"duplicate watch id '{wid}'")
        movie = w.get("movie")
        if not movie or not isinstance(movie, str):
            raise _err(name, _line(w, "movie"), f"watch '{wid}' needs a movie name")
        raw_dates = w.get("dates")
        if not isinstance(raw_dates, list) or not raw_dates:
            raise _err(name, _line(w, "dates"), f"watch '{wid}' needs a list of dates, e.g. dates: [\"2026-12-23\"]")
        dates = []
        for d in raw_dates:
            try:
                dates.append(parse_date(d))
            except ValueError:
                raise _err(name, _line(w, "dates"), f"watch '{wid}' has a bad date '{d}'; use YYYY-MM-DD")
        wc = w.get("cinemas") or []
        for cid in wc:
            if not any(c.id == cid for c in cinemas):
                raise _err(name, _line(w, "cinemas"), f"watch '{wid}' names unknown cinema '{cid}'")
        formats = w.get("formats") or []
        if not isinstance(formats, list) or not all(isinstance(f, str) for f in formats):
            raise _err(name, _line(w, "formats"), f"watch '{wid}' formats must be a list like [\"IMAX\"]")
        watches.append(Watch(wid, movie.strip(), sorted(set(dates)), list(wc), formats, "config"))

    return Config(settings, cinemas, watches)
