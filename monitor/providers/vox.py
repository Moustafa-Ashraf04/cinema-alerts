"""Vox Cinemas Egypt: parked.

egy.voxcinemas.com is behind Akamai Bot Manager and drops every honest,
non-browser request (docs/DISCOVERY.md). We do not evade it, so this provider
only builds URLs and reports ERROR. It stays here so Vox can come back if a
polite source appears.
"""

from __future__ import annotations

from datetime import date
from urllib.parse import urlencode

from ..models import CheckResult, Cinema, Status
from .base import Provider


def build_url(cinema: str, movies: list[str], d: date) -> str:
    params = [("c", cinema)] + [("m", m) for m in movies] + [("d", d.strftime("%Y%m%d"))]
    return "https://egy.voxcinemas.com/showtimes?" + urlencode(params)


class VoxProvider(Provider):
    name = "vox"

    def check(self, cinema: Cinema, movie_query: str, dates: list[date]) -> dict[date, CheckResult]:
        return {d: CheckResult(Status.ERROR, reason="Vox is parked: its site blocks the bot") for d in dates}
