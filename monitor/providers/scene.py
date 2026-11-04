"""Scene Cinemas (cfc.scenecinemas.com, district5.scenecinemas.com).

See docs/DISCOVERY.md for the evidence behind every selector here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup

from ..matching import title_matches
from ..models import CheckResult, Cinema, Showtime, Status
from .base import ParseError, Provider

BRANCHES = {"cfc": "Cairo Festival City", "district5": "District 5"}

TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s?[AP]M$", re.I)
FORMAT_GROUP_RE = re.compile(r"^ex_[a-z0-9]+_content$")
FORMAT_LABEL_RE = re.compile(r"^ex_[a-z0-9]+$")


def base_url(branch: str) -> str:
    return f"https://{branch}.scenecinemas.com"


def home_url(branch: str) -> str:
    return base_url(branch) + "/"


def movie_url(branch: str, slug: str) -> str:
    return f"{base_url(branch)}/movie-details/{slug}.html"


def fragment_url(branch: str, slug: str, d: date) -> str:
    # The same request the page's own LoadShowtimes() makes.
    return f"{movie_url(branch, slug)}?business_day={d:%d-%m-%Y}&ajax=1"


def parse_home(html: str, branch: str) -> dict[str, str]:
    """Return {slug: title} for every film listed on the branch homepage."""
    if not html or not html.strip():
        raise ParseError("empty homepage")
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select("li.film-cards-list-item") and not soup.find("h1", string=re.compile("Now Showing", re.I)):
        raise ParseError("homepage has no Now Showing list")
    pattern = re.compile(rf"^{re.escape(base_url(branch))}/movie-details/([^/?#]+)\.html$")
    movies: dict[str, str] = {}
    for a in soup.find_all("a", href=pattern):
        title = (a.get("title") or "").strip()
        slug = pattern.match(a["href"]).group(1)
        if title and slug not in movies:
            movies[slug] = re.sub(r"\s+", " ", title)
    return movies


@dataclass
class MoviePage:
    dates: set[date]
    no_showtimes: bool  # the page's own "There is no showtimes" notice is visible


def parse_movie_page(html: str) -> MoviePage:
    if not html or not html.strip():
        raise ParseError("empty movie page")
    soup = BeautifulSoup(html, "html.parser")
    dates = set()
    for li in soup.select("li.calanderdays[id^=data-]"):
        try:
            dates.add(datetime.strptime(li["id"][5:], "%d-%m-%Y").date())
        except ValueError:
            raise ParseError(f"unexpected date id '{li['id']}'")
    notice = soup.find("h1", string=re.compile(r"There is no showtimes", re.I))
    visible_notice = False
    if notice is not None:
        container = notice.find_parent("div")
        style = (container.get("style") or "").replace(" ", "").lower() if container else ""
        visible_notice = "display:none" not in style
    if dates and not soup.find(id="ShowtimesAjax"):
        raise ParseError("date list without a showtimes area")
    if not dates and not visible_notice:
        raise ParseError("movie page has neither dates nor a no-showtimes notice")
    if dates and visible_notice:
        raise ParseError("movie page shows dates and a no-showtimes notice at once")
    return MoviePage(dates, visible_notice)


def parse_fragment(html: str, branch: str) -> list[Showtime]:
    """Parse the ?business_day=...&ajax=1 fragment for one date."""
    if not html or not html.strip():
        raise ParseError("empty showtimes fragment")
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div.program_item")
    if not items:
        raise ParseError("showtimes fragment not recognised")
    link = re.compile(rf"^{re.escape(base_url(branch))}/showtime-[0-9a-f]+$")
    showtimes: list[Showtime] = []
    for item in items:
        place = item.select_one("div.branch")
        if place is None or BRANCHES[branch].lower() not in place.get_text(" ", strip=True).lower():
            raise ParseError("showtimes fragment is for a different branch")
        for a in item.select("div.showtimes a"):
            text = a.get_text(" ", strip=True)
            if not TIME_RE.match(text):
                continue
            # Each format is a <div class="ex_<kind>_content"> with a <span class="ex_<kind>"> label,
            # e.g. ex_imax / "ScreenX", ex_stand / "Standard & Deluxe".
            group = a.find_parent("div", class_=FORMAT_GROUP_RE)
            label = group.find("span", class_=FORMAT_LABEL_RE) if group else None
            fmt = label.get_text(" ", strip=True) if label else "Standard"
            href = a.get("href", "")
            if link.match(href):
                showtimes.append(Showtime(text.upper(), fmt, href))
            else:  # a time without a booking link: shown, but not bookable
                showtimes.append(Showtime(text.upper(), fmt, "", sold_out=True))
    if not showtimes:
        raise ParseError("showtimes fragment has no times")
    return showtimes


class SceneProvider(Provider):
    name = "scene"

    def check(self, cinema: Cinema, movie_query: str, dates: list[date]) -> dict[date, CheckResult]:
        branch = cinema.branch

        def all_dates(status: Status, reason: str, **kw) -> dict[date, CheckResult]:
            return {d: CheckResult(status, reason=reason, **kw) for d in dates}

        home = self.fetcher.get(home_url(branch))
        if not home.ok:
            return all_dates(Status.ERROR, f"homepage: {home.describe()}")
        try:
            movies = parse_home(home.text, branch)
        except ParseError as exc:
            return all_dates(Status.ERROR, f"homepage: {exc}")

        matches = {slug: title for slug, title in movies.items() if title_matches(movie_query, title, slug)}
        if not matches:
            return all_dates(Status.CLOSED, "not listed at this branch yet")
        titles = sorted(set(matches.values()))

        showtimes: dict[date, list[Showtime]] = {d: [] for d in dates}
        errors: dict[date, list[str]] = {d: [] for d in dates}
        book_url: dict[date, str] = {}
        for slug in sorted(matches):
            page = self.fetcher.get(movie_url(branch, slug))
            if not page.ok:
                for d in dates:
                    errors[d].append(f"{slug}: {page.describe()}")
                continue
            try:
                info = parse_movie_page(page.text)
            except ParseError as exc:
                for d in dates:
                    errors[d].append(f"{slug}: {exc}")
                continue
            for d in dates:
                if d not in info.dates:
                    continue  # positive evidence: this date is not on sale for this page
                frag = self.fetcher.get(fragment_url(branch, slug, d))
                if not frag.ok:
                    errors[d].append(f"{slug} {d}: {frag.describe()}")
                    continue
                try:
                    found = parse_fragment(frag.text, branch)
                except ParseError as exc:
                    errors[d].append(f"{slug} {d}: {exc}")
                    continue
                showtimes[d].extend(found)
                if any(not s.sold_out for s in found):
                    book_url.setdefault(d, movie_url(branch, slug))

        results = {}
        for d in dates:
            bookable = [s for s in showtimes[d] if not s.sold_out]
            if bookable:
                results[d] = CheckResult(Status.OPEN, showtimes[d], titles, book_url[d], partial=bool(errors[d]))
            elif errors[d]:
                results[d] = CheckResult(Status.ERROR, titles=titles, reason="; ".join(errors[d]))
            else:
                results[d] = CheckResult(Status.CLOSED, showtimes[d], titles, movie_url(branch, sorted(matches)[0]),
                                         reason="no bookable showtimes on this date")
        return results
