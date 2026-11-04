"""Polite HTTP: one request at a time, clear User-Agent, timeout, backoff on 429/503."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)

USER_AGENT = "cinema-alert-bot (personal use)"
TIMEOUT = 20


@dataclass
class FetchResult:
    url: str
    status: int  # 0 when no response arrived
    text: str = ""
    final_url: str = ""  # after redirects
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.status == 200 and not self.error and self.final_url in ("", self.url)

    def describe(self) -> str:
        if self.error:
            return self.error
        if self.final_url and self.final_url != self.url:
            return "redirected to a different page"
        return f"HTTP {self.status}"


class Fetcher:
    """Responses are cached for the run, so watches that share a page cost one request."""

    def __init__(self, session: requests.Session | None = None, *, delay: float = 1.0, retries: int = 2,
                 sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay, self.retries, self.sleep = delay, retries, sleep
        self.cache: dict[str, FetchResult] = {}
        self.requests_made = 0
        self._last = 0.0

    def get(self, url: str) -> FetchResult:
        if url not in self.cache:
            self.cache[url] = self._get(url)
        return self.cache[url]

    def _get(self, url: str) -> FetchResult:
        for attempt in range(self.retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            self.requests_made += 1
            try:
                r = self.session.get(url, timeout=TIMEOUT)
            except requests.Timeout:
                result = FetchResult(url, 0, error="timed out")
            except requests.RequestException as exc:
                result = FetchResult(url, 0, error=f"connection failed ({type(exc).__name__})")
            else:
                result = FetchResult(url, r.status_code, r.text, r.url)
                if r.status_code not in (429, 503) or attempt == self.retries:
                    return result
                backoff = _retry_after(r.headers.get("Retry-After"), 5 * 2 ** attempt)
                log.warning("HTTP %s, waiting %ss", r.status_code, backoff)
                self.sleep(backoff)
                continue
            if attempt < self.retries:
                self.sleep(3)
        return result


def _retry_after(value: str | None, default: float) -> float:
    try:
        return min(max(float(value), 1.0), 60.0) if value else default
    except ValueError:
        return default
