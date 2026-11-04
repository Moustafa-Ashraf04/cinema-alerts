"""Telegram Bot API client and message formatting. The token never reaches logs."""

from __future__ import annotations

import html
import logging
import time
from datetime import date

import requests

from .models import Cinema, Showtime

log = logging.getLogger(__name__)

API = "https://api.telegram.org"
TIMEOUT = 10
RETRIES = 3


class TelegramError(Exception):
    pass


class Telegram:
    def __init__(self, token: str, chat_id: str, *, dry_run: bool = False,
                 session: requests.Session | None = None, sleep=time.sleep, out=print):
        self._token = token or ""
        self.chat_id = str(chat_id or "")
        self.dry_run = dry_run
        self.session = session or requests.Session()
        self.sleep = sleep
        self.out = out

    @property
    def configured(self) -> bool:
        return bool(self._token and self.chat_id)

    def _clean(self, text: str) -> str:
        return text.replace(self._token, "***") if self._token else text

    def call(self, method: str, payload: dict) -> dict:
        if not self.configured:
            raise TelegramError("TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID is not set")
        url = f"{API}/bot{self._token}/{method}"
        problem = ""
        for attempt in range(RETRIES + 1):
            try:
                r = self.session.post(url, json=payload, timeout=TIMEOUT)
            except requests.RequestException as exc:  # str(exc) would contain the URL with the token
                problem = f"connection failed ({type(exc).__name__})"
            else:
                try:
                    body = r.json()
                except ValueError:
                    body = {}
                if r.status_code == 200 and body.get("ok"):
                    return body
                description = self._clean(str(body.get("description", "")))[:200]
                problem = f"HTTP {r.status_code} {description}".strip()
                if r.status_code == 429:
                    wait = (body.get("parameters") or {}).get("retry_after", 2 ** attempt)
                    if attempt < RETRIES:
                        self.sleep(min(float(wait), 30.0))
                        continue
                elif r.status_code < 500:
                    raise TelegramError(f"Telegram {method} failed: {problem}")
            if attempt < RETRIES:
                self.sleep(2 ** attempt)
        raise TelegramError(f"Telegram {method} failed after {RETRIES + 1} tries: {problem}")

    def send(self, text: str, button: tuple[str, str] | None = None) -> None:
        if self.dry_run:
            self.out("--- Telegram message (dry run) ---\n" + text + (f"\n[{button[0]}] {button[1]}" if button else ""))
            return
        payload = {"chat_id": self.chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": True}
        if button:
            payload["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
        self.call("sendMessage", payload)

    def get_updates(self, offset: int) -> list[dict]:
        body = self.call("getUpdates", {"offset": offset, "timeout": 0, "allowed_updates": ["message"]})
        return body.get("result", [])


# ---------- message formatting ----------

e = html.escape


def fmt_date(d: date) -> str:
    return d.strftime("%a %d %b %Y")


def _times(showtimes: list[Showtime], limit: int = 12) -> str:
    lines, by_format = [], {}
    for s in showtimes:
        by_format.setdefault(s.format or "Standard", []).append(s)
    shown = 0
    for fmt, items in by_format.items():
        parts = []
        for s in items:
            if shown >= limit:
                break
            parts.append(f'<a href="{e(s.url, quote=True)}">{e(s.time)}</a>' if s.url else e(s.time))
            shown += 1
        if parts:
            lines.append(f"• <b>{e(fmt)}</b>: " + ", ".join(parts))
    if len(showtimes) > shown:
        lines.append(f"…and {len(showtimes) - shown} more")
    return "\n".join(lines)


def fmt_open(movie: str, titles: list[str], cinema: Cinema, d: date, showtimes: list[Showtime], url: str):
    name = ", ".join(titles) or movie
    formats = sorted({s.format for s in showtimes if s.format})
    text = (f"🎟 <b>Booking is OPEN</b>\n<b>{e(name)}</b>\n{e(cinema.name)} · {e(fmt_date(d))}\n"
            + (f"Formats: {e(', '.join(formats))}\n" if formats else "")
            + "\n" + _times(showtimes))
    return text, ("Book now", url)


def fmt_new(movie: str, titles: list[str], cinema: Cinema, d: date, showtimes: list[Showtime], url: str):
    name = ", ".join(titles) or movie
    text = (f"➕ <b>New showtimes</b>\n<b>{e(name)}</b>\n{e(cinema.name)} · {e(fmt_date(d))}\n\n" + _times(showtimes))
    return text, ("Book now", url)


def fmt_problem(items: list[tuple[str, Cinema, date, str]], runs: int) -> str:
    lines = [f"⚠️ <b>Problem</b>: these checks failed {runs} runs in a row, so I can't see if booking opened:"]
    for movie, cinema, d, reason in items[:15]:
        lines.append(f"• {e(movie)} · {e(cinema.name)} · {e(fmt_date(d))}\n  <i>{e(reason[:200])}</i>")
    if len(items) > 15:
        lines.append(f"…and {len(items) - 15} more")
    lines.append("If this keeps happening the site may have changed; see “If the site changes” in the README.")
    return "\n".join(lines)


def fmt_recovered(items: list[tuple[str, Cinema, date]]) -> str:
    lines = ["✅ <b>Recovered</b>: these checks work again:"]
    for movie, cinema, d in items[:15]:
        lines.append(f"• {e(movie)} · {e(cinema.name)} · {e(fmt_date(d))}")
    return "\n".join(lines)


def fmt_heartbeat(n_watches: int, last_check: str, n_errors: int) -> str:
    text = f"💓 Alive. Watching {n_watches} movie{'s' if n_watches != 1 else ''}. Last check: {e(last_check)}."
    if n_errors:
        text += f"\n{n_errors} check{'s are' if n_errors != 1 else ' is'} currently failing; send /status for details."
    return text
