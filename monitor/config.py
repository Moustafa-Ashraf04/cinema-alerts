"""Load and validate watches.yaml (settings and cinemas), with errors that name the line."""

from __future__ import annotations

import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml

from .models import Cinema

PROVIDERS = {"scene"}


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

    @property
    def enabled_cinemas(self) -> list[Cinema]:
        return [c for c in self.cinemas if c.enabled]

    def cinema(self, cinema_id: str) -> Cinema | None:
        return next((c for c in self.cinemas if c.id == cinema_id), None)


class _Loader(yaml.SafeLoader):
    """Records the line of every mapping key, for readable errors."""


def _construct_mapping(loader, node, deep=False):
    mapping = yaml.SafeLoader.construct_mapping(loader, node, deep=deep)
    mapping["__lines__"] = {k.value: k.start_mark.line + 1 for k, _ in node.value}
    mapping["__lines__"][None] = node.start_mark.line + 1
    return mapping


_Loader.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping)


def load_config(path: str) -> Config:
    name = path.rsplit("/", 1)[-1]

    def fail(m: dict, key, msg: str):
        line = m.get("__lines__", {}).get(key) or m.get("__lines__", {}).get(None)
        raise ConfigError(f"{name} line {line}: {msg}" if line else f"{name}: {msg}")

    def check_keys(m: dict, allowed: set[str], what: str):
        for key in m:
            if key != "__lines__" and key not in allowed:
                fail(m, key, f"unknown key '{key}' in {what} (allowed: {', '.join(sorted(allowed))})")

    try:
        with open(path, encoding="utf-8") as f:
            raw = yaml.load(f, Loader=_Loader) or {}
    except FileNotFoundError:
        raise ConfigError(f"{path} not found")
    except yaml.YAMLError as exc:
        mark = getattr(exc, "problem_mark", None)
        raise ConfigError(f"{name}{f' line {mark.line + 1}' if mark else ''}: not valid YAML")
    if not isinstance(raw, dict):
        raise ConfigError(f"{name}: expected settings and cinemas")
    check_keys(raw, {"settings", "cinemas"}, "the top level")

    s = raw.get("settings") or {}
    check_keys(s, {"timezone", "heartbeat_hour", "error_alert_after", "notify_new_showtimes"}, "settings")
    settings = Settings(**{k: v for k, v in s.items() if k != "__lines__"})
    try:
        ZoneInfo(str(settings.timezone))
    except (ZoneInfoNotFoundError, ValueError):
        fail(s, "timezone", f"unknown timezone '{settings.timezone}'")
    if not isinstance(settings.heartbeat_hour, int) or not 0 <= settings.heartbeat_hour <= 23:
        fail(s, "heartbeat_hour", "heartbeat_hour must be a whole number from 0 to 23")
    if not isinstance(settings.error_alert_after, int) or settings.error_alert_after < 1:
        fail(s, "error_alert_after", "error_alert_after must be a whole number of 1 or more")
    if not isinstance(settings.notify_new_showtimes, bool):
        fail(s, "notify_new_showtimes", "notify_new_showtimes must be true or false")

    cinemas: list[Cinema] = []
    for c in raw.get("cinemas") or []:
        if not isinstance(c, dict):
            raise ConfigError(f"{name}: each cinema needs id, provider and branch")
        check_keys(c, {"id", "provider", "branch", "name", "enabled"}, "a cinema")
        cid, provider, branch = c.get("id"), c.get("provider"), c.get("branch")
        if not isinstance(cid, str) or not cid:
            fail(c, None, "cinema is missing an id")
        if any(x.id == cid for x in cinemas):
            fail(c, "id", f"duplicate cinema id '{cid}'")
        if provider not in PROVIDERS:
            fail(c, "provider", f"unknown provider '{provider}' (known: {', '.join(sorted(PROVIDERS))})")
        if not isinstance(branch, str) or not re.fullmatch(r"[a-z0-9-]+", branch):
            fail(c, "branch", "branch must be the part before .scenecinemas.com, e.g. cfc")
        enabled = c.get("enabled", True)
        if not isinstance(enabled, bool):
            fail(c, "enabled", "enabled must be true or false")
        cinemas.append(Cinema(cid, provider, branch, str(c.get("name") or cid), enabled))
    if not any(c.enabled for c in cinemas):
        raise ConfigError(f"{name}: no enabled cinemas")
    return Config(settings, cinemas)
