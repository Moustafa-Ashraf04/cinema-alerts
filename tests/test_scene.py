from datetime import date

import pytest
from conftest import DictFetcher, read

from monitor.models import Cinema, Status
from monitor.scene import (ParseError, SceneProvider, fragment_url, home_url, movie_url, parse_fragment, parse_home,
                           parse_movie_page, title_matches)

CFC = Cinema("scene-cfc", "scene", "cfc", "Scene Cairo Festival City")
SLUG = "avengers-doomsday-infinity-vision-sx-4dx"
D23, D30 = date(2026, 12, 23), date(2026, 12, 30)

HOME = read("cfc_home_20261104.html")
MOVIE = read("cfc_movie_avengers-sx-4dx_20261104.html")
OPEN_23 = read("cfc_ajax_avengers-sx-4dx_23-12-2026_open.html")


def pages(**over):
    p = {
        home_url("cfc"): (200, HOME),
        movie_url("cfc", SLUG): (200, MOVIE),
        fragment_url("cfc", SLUG, D23): (200, OPEN_23),
    }
    p.update(over)
    return p


# ---- URL builder ----

def test_fragment_url_matches_the_sites_own_request():
    assert fragment_url("cfc", SLUG, D23) == (
        "https://cfc.scenecinemas.com/movie-details/avengers-doomsday-infinity-vision-sx-4dx.html"
        "?business_day=23-12-2026&ajax=1")
    assert home_url("district5") == "https://district5.scenecinemas.com/"


# ---- parsers ----

def test_home_lists_titles_by_slug():
    movies = parse_home(HOME, "cfc")
    assert movies[SLUG] == "Avengers: Doomsday"
    assert movies["dune-part-three"] == "Dune: Part Three"
    assert len(movies) == 21


def test_movie_page_dates():
    page = parse_movie_page(MOVIE)
    assert page.dates == {date(2026, 12, d) for d in range(16, 24)}
    assert not page.no_showtimes


def test_movie_page_with_visible_no_showtimes_notice():
    page = parse_movie_page(read("synthetic_cfc_movie_no_showtimes.html"))
    assert page.dates == set() and page.no_showtimes


def test_fragment_showtimes():
    st = parse_fragment(OPEN_23, "cfc")
    assert [s.time for s in st] == ["12:00 PM", "04:00 PM", "08:00 PM", "12:00 AM"]
    assert {s.format for s in st} == {"ScreenX"}
    assert all(s.url.startswith("https://cfc.scenecinemas.com/showtime-") and not s.sold_out for s in st)


@pytest.mark.parametrize("html", ["", "   \n", "<html><body>Maintenance</body></html>"])
def test_unrecognised_fragment_is_a_parse_error(html):
    with pytest.raises(ParseError):
        parse_fragment(html, "cfc")


def test_fragment_for_another_branch_is_a_parse_error():
    with pytest.raises(ParseError):
        parse_fragment(OPEN_23, "district5")


@pytest.mark.parametrize("query, ok", [
    ("dune", True), ("Dune part 3", False), ("dune part three", True), ("avengers", True),
    ("spider man", False), ("doomsday infinity", True), ("x", False),
])
def test_title_matching(query, ok):
    titles = {"dune-part-three": "Dune: Part Three", "avengers-doomsday-infinity-vision-sx-4dx": "Avengers: Doomsday"}
    assert any(title_matches(query, t, slug) for slug, t in titles.items()) is ok


def test_truncated_and_unknown_movie_pages_are_parse_errors():
    with pytest.raises(ParseError):
        parse_movie_page(MOVIE[: MOVIE.find("glxDaysList") - 400])
    with pytest.raises(ParseError):
        parse_movie_page("<html><body><h1>Something else</h1></body></html>")


# ---- check(): OPEN / CLOSED / ERROR ----

def check(fetch_pages, query="avengers", dates=(D23,)):
    return SceneProvider(DictFetcher(fetch_pages)).check(CFC, query, list(dates))


def test_open_date():
    r = check(pages())[D23]
    assert r.status == Status.OPEN
    assert len(r.bookable) == 4 and r.titles == ["Avengers: Doomsday"]
    assert r.url == movie_url("cfc", SLUG)


def test_date_not_on_sale_is_closed_without_fetching_it():
    f = DictFetcher(pages())
    r = SceneProvider(f).check(CFC, "avengers", [D30])[D30]
    assert r.status == Status.CLOSED
    assert fragment_url("cfc", SLUG, D30) not in f.urls


def test_film_not_listed_is_closed():
    assert check(pages(), query="batman")[D23].status == Status.CLOSED


def test_date_removed_from_strip_is_closed():
    p = pages(**{movie_url("cfc", SLUG): (200, read("synthetic_cfc_movie_avengers_without_23dec.html"))})
    assert check(p)[D23].status == Status.CLOSED


@pytest.mark.parametrize("override", [
    {home_url("cfc"): (403, "Forbidden")},
    {home_url("cfc"): (200, "<html>Just a moment...</html>")},
    {movie_url("cfc", SLUG): (503, "")},
    {movie_url("cfc", SLUG): (200, "")},
    {fragment_url("cfc", SLUG, D23): (200, "")},  # date is in the strip but no times came back
    {fragment_url("cfc", SLUG, D23): (200, OPEN_23[: len(OPEN_23) // 3])},  # truncated
    {fragment_url("cfc", SLUG, D23): (200, OPEN_23, "https://cfc.scenecinemas.com/")},  # redirected
])
def test_failures_are_error_never_open(override):
    r = check(pages(**override))[D23]
    assert r.status == Status.ERROR and r.reason


def test_two_movies_on_one_branch_give_separate_results():
    dune = movie_url("cfc", "dune-part-three")
    p = pages(**{dune: (200, read("synthetic_cfc_movie_no_showtimes.html"))})
    f = DictFetcher(p)
    prov = SceneProvider(f)
    assert prov.check(CFC, "avengers", [D23])[D23].status == Status.OPEN
    assert prov.check(CFC, "dune", [D23])[D23].status == Status.CLOSED


def test_format_labels_from_every_ex_group():
    d5 = parse_fragment(read("district5_ajax_avengers-sx-4dx_23-12-2026_standard.html"), "district5")
    assert {s.format for s in d5} == {"Standard & Deluxe"} and len(d5) == 4
    dune = parse_fragment(read("cfc_ajax_dune-part-three_23-12-2026_standard.html"), "cfc")
    assert {s.format for s in dune} == {"Standard"} and [s.time for s in dune][-1] == "12:00 AM"
