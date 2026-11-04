"""Scene Cinemas (<branch>.scenecinemas.com). Evidence for every selector: docs/DISCOVERY.md."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime

from bs4 import BeautifulSoup

from .models import CheckResult, Cinema, Showtime, Status

TIME_RE = re.compile(r"^\d{1,2}:\d{2}\s?[AP]M$", re.I)
FORMAT_GROUP_RE = re.compile(r"^ex_[a-z0-9]+_content$")  # e.g. ex_imax_content, ex_stand_content
FORMAT_LABEL_RE = re.compile(r"^ex_[a-z0-9]+$")  # e.g. <span class="ex_imax">ScreenX</span>
SHOWTIME_RE = re.compile(r"^https://([a-z0-9-]+)\.scenecinemas\.com/showtime-[0-9a-f]+$")


class ParseError(Exception):
    """The page is not one we recognise. Always reported as ERROR."""


def base_url(branch: str) -> str:
    return f"https://{branch}.scenecinemas.com"


def home_url(branch: str) -> str:
    return base_url(branch) + "/"


def movie_url(branch: str, slug: str) -> str:
    return f"{base_url(branch)}/movie-details/{slug}.html"


def fragment_url(branch: str, slug: str, d: date) -> str:
    # The same request the page's own LoadShowtimes() makes.
    return f"{movie_url(branch, slug)}?business_day={d:%d-%m-%Y}&ajax=1"


def normalize(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text.lower())  # drop "(2D)" and similar
    return re.sub(r"[^a-z0-9؀-ۿ]+", " ", text).strip()


def title_matches(query: str, title: str, slug: str = "") -> bool:
    """Every word typed must start a word of the title (or of the URL slug)."""
    q = normalize(query).split()
    for candidate in (title, slug.replace("-", " ").replace("_", " ")):
        words = normalize(candidate).split()
        if q and words and all(any(w.startswith(t) for w in words) for t in q):
            return True
    return False


def parse_home(html: str, branch: str) -> dict[str, str]:
    """{slug: title} for every film listed on the branch homepage."""
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
    no_showtimes: bool  # the site's own "There is no showtimes" notice is visible


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
    visible = False
    if notice is not None:
        box = notice.find_parent("div")
        visible = "display:none" not in ((box.get("style") or "") if box else "").replace(" ", "").lower()
    if dates and not soup.find(id="ShowtimesAjax"):
        raise ParseError("date list without a showtimes area")
    if not dates and not visible:
        raise ParseError("movie page has neither dates nor a no-showtimes notice")
    if dates and visible:
        raise ParseError("movie page shows dates and a no-showtimes notice at once")
    return MoviePage(dates, visible)


def parse_fragment(html: str, branch: str) -> list[Showtime]:
    """Parse the ?business_day=...&ajax=1 fragment for one date."""
    if not html or not html.strip():
        raise ParseError("empty showtimes fragment")
    soup = BeautifulSoup(html, "html.parser")
    if not soup.select("div.program_item"):
        raise ParseError("showtimes fragment not recognised")
    showtimes: list[Showtime] = []
    for a in soup.select("div.program_item div.showtimes a"):
        text = a.get_text(" ", strip=True)
        if not TIME_RE.match(text):
            continue
        group = a.find_parent("div", class_=FORMAT_GROUP_RE)
        label = group.find("span", class_=FORMAT_LABEL_RE) if group else None
        fmt = label.get_text(" ", strip=True) if label else "Standard"
        link = SHOWTIME_RE.match(a.get("href", ""))
        if link and link.group(1) != branch:
            raise ParseError("showtimes fragment is for a different branch")
        # a time without a booking link is shown but not bookable
        showtimes.append(Showtime(text.upper(), fmt, a["href"] if link else "", sold_out=not link))
    if not showtimes:
        raise ParseError("showtimes fragment has no times")
    return showtimes


class SceneProvider:
    def __init__(self, fetcher):
        self.fetcher = fetcher

    def check(self, cinema: Cinema, movie_query: str, dates: list[date]) -> dict[date, CheckResult]:
        """OPEN, CLOSED or ERROR for each requested date."""
        branch = cinema.branch

        def every_date(status: Status, reason: str) -> dict[date, CheckResult]:
            return {d: CheckResult(status, reason=reason) for d in dates}

        home = self.fetcher.get(home_url(branch))
        if not home.ok:
            return every_date(Status.ERROR, f"homepage: {home.describe()}")
        try:
            movies = parse_home(home.text, branch)
        except ParseError as exc:
            return every_date(Status.ERROR, f"homepage: {exc}")

        matches = {slug: t for slug, t in movies.items() if title_matches(movie_query, t, slug)}
        if not matches:
            return every_date(Status.CLOSED, "not listed at this branch yet")
        titles = sorted(set(matches.values()))

        showtimes: dict[date, list[Showtime]] = {d: [] for d in dates}
        errors: dict[date, list[str]] = {d: [] for d in dates}
        book_url: dict[date, str] = {}
        for slug in sorted(matches):
            page = self.fetcher.get(movie_url(branch, slug))
            try:
                if not page.ok:
                    raise ParseError(page.describe())
                info = parse_movie_page(page.text)
            except ParseError as exc:
                for d in dates:
                    errors[d].append(f"{slug}: {exc}")
                continue
            for d in dates:
                if d not in info.dates:
                    continue  # positive evidence: this date isn't on sale on this page
                frag = self.fetcher.get(fragment_url(branch, slug, d))
                try:
                    if not frag.ok:
                        raise ParseError(frag.describe())
                    found = parse_fragment(frag.text, branch)
                except ParseError as exc:
                    errors[d].append(f"{slug} {d}: {exc}")
                    continue
                showtimes[d].extend(found)
                if any(not s.sold_out for s in found):
                    book_url.setdefault(d, movie_url(branch, slug))

        results = {}
        for d in dates:
            if any(not s.sold_out for s in showtimes[d]):
                results[d] = CheckResult(Status.OPEN, showtimes[d], titles, book_url[d], partial=bool(errors[d]))
            elif errors[d]:
                results[d] = CheckResult(Status.ERROR, titles=titles, reason="; ".join(errors[d]))
            else:
                results[d] = CheckResult(Status.CLOSED, showtimes[d], titles, reason="no bookable showtimes on this date")
        return results
