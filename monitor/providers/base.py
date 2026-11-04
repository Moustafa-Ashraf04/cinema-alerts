"""Provider interface and the polite HTTP fetcher every provider shares."""

from __future__ import annotations

import json
import logging
import os
import re
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date

import requests

from ..models import CheckResult, Cinema

log = logging.getLogger(__name__)

USER_AGENT = "cinema-alert-bot (personal use)"
TIMEOUT = 20


class ParseError(Exception):
    """The page is not one we recognise. Always reported as ERROR."""


@dataclass
class FetchResult:
    url: str  # the URL requested
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
    """One request at a time, a clear User-Agent, a timeout, and backoff on 429/503.

    Responses are cached for the run, so watches that share a page cost one request.
    """

    def __init__(self, session: requests.Session | None = None, *, delay: float = 1.0,
                 max_retries: int = 2, sleep=time.sleep):
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.delay = delay
        self.max_retries = max_retries
        self.sleep = sleep
        self.cache: dict[str, FetchResult] = {}
        self.requests_made = 0
        self._last = 0.0

    def get(self, url: str) -> FetchResult:
        if url not in self.cache:
            self.cache[url] = self._get(url)
        return self.cache[url]

    def _get(self, url: str) -> FetchResult:
        for attempt in range(self.max_retries + 1):
            wait = self.delay - (time.monotonic() - self._last)
            if wait > 0:
                self.sleep(wait)
            self._last = time.monotonic()
            self.requests_made += 1
            try:
                r = self.session.get(url, timeout=TIMEOUT, allow_redirects=True)
            except requests.Timeout:
                result = FetchResult(url, 0, error="timed out")
            except requests.RequestException as exc:
                result = FetchResult(url, 0, error=f"connection failed ({type(exc).__name__})")
            else:
                result = FetchResult(url, r.status_code, r.text, r.url)
                if r.status_code in (429, 503) and attempt < self.max_retries:
                    backoff = _retry_after(r.headers.get("Retry-After"), 5 * 2 ** attempt)
                    log.warning("HTTP %s from %s, waiting %ss", r.status_code, _host(url), backoff)
                    self.sleep(backoff)
                    continue
                return result
            if attempt < self.max_retries:
                self.sleep(3)
        return result


def _retry_after(value: str | None, default: float) -> float:
    try:
        return min(max(float(value), 1.0), 60.0) if value else default
    except ValueError:
        return default


def _host(url: str) -> str:
    m = re.match(r"https?://([^/]+)", url)
    return m.group(1) if m else url


class FixtureFetcher:
    """Serves saved pages instead of the network, for tests and alert rehearsals.

    `manifest.json` maps each URL to a file in the same folder, or to
    {"file": ..., "status": ..., "final_url": ...}. Unknown URLs fail like a network error.
    """

    def __init__(self, folder: str):
        self.folder = folder
        with open(os.path.join(folder, "manifest.json"), encoding="utf-8") as f:
            self.manifest: dict = json.load(f)
        self.requests_made = 0

    def get(self, url: str) -> FetchResult:
        self.requests_made += 1
        entry = self.manifest.get(url)
        if entry is None:
            return FetchResult(url, 0, error="no saved page for this URL")
        if isinstance(entry, str):
            entry = {"file": entry}
        text = ""
        if entry.get("file"):
            with open(os.path.join(self.folder, entry["file"]), encoding="utf-8", errors="replace") as f:
                text = f.read()
        return FetchResult(url, int(entry.get("status", 200)), text, entry.get("final_url", url))


class Provider(ABC):
    """One cinema chain. Scene, Premiere and Vox implement the same interface."""

    name: str = ""

    def __init__(self, fetcher):
        self.fetcher = fetcher

    @abstractmethod
    def check(self, cinema: Cinema, movie_query: str, dates: list[date]) -> dict[date, CheckResult]:
        """Return OPEN, CLOSED or ERROR for each requested date."""
