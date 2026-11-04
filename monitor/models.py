from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum


class Status(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Showtime:
    time: str
    format: str
    url: str
    sold_out: bool = False

    @property
    def key(self) -> str:
        return self.url or f"{self.format}|{self.time}"

    def to_dict(self) -> dict:
        return {"time": self.time, "format": self.format, "url": self.url, "sold_out": self.sold_out}

    @classmethod
    def from_dict(cls, d: dict) -> "Showtime":
        return cls(d["time"], d.get("format", ""), d.get("url", ""), bool(d.get("sold_out", False)))


@dataclass(frozen=True)
class Cinema:
    id: str
    provider: str
    branch: str
    name: str
    enabled: bool = True


@dataclass
class Watch:
    """One /watch from Telegram."""
    id: str
    movie: str
    dates: list[date]
    cinemas: list[str] = field(default_factory=list)  # empty = all enabled cinemas

    def to_dict(self) -> dict:
        return {"id": self.id, "movie": self.movie, "dates": [d.isoformat() for d in self.dates],
                "cinemas": list(self.cinemas)}

    @classmethod
    def from_dict(cls, d: dict) -> "Watch":
        return cls(d["id"], d["movie"], [date.fromisoformat(x) for x in d.get("dates", [])], list(d.get("cinemas", [])))


@dataclass
class CheckResult:
    status: Status
    showtimes: list[Showtime] = field(default_factory=list)
    titles: list[str] = field(default_factory=list)  # titles the typed name matched
    url: str = ""  # page to open for booking
    reason: str = ""  # why CLOSED or ERROR
    partial: bool = False  # OPEN, but some of the film's pages failed

    @property
    def bookable(self) -> list[Showtime]:
        return [s for s in self.showtimes if not s.sold_out]
