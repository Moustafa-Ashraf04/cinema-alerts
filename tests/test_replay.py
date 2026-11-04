"""End to end on saved pages: /watch in Telegram -> checks -> alerts, across several runs."""

from datetime import datetime, timezone

from conftest import DictFetcher, FakeTelegram, read

from monitor.main import run
from monitor.notify import TelegramError
from monitor.scene import fragment_url, home_url, movie_url

SLUG = "avengers-doomsday-infinity-vision-sx-4dx"
D23 = datetime(2026, 12, 23).date()
EARLY = datetime(2026, 11, 4, 3, 0, tzinfo=timezone.utc)  # 05:00 Cairo, before the 09:00 heartbeat
CONFIG = """settings:
  timezone: Africa/Cairo
cinemas:
  - id: scene-cfc
    provider: scene
    branch: cfc
    name: Scene Cairo Festival City
"""

CLOSED = {home_url("cfc"): (200, read("cfc_home_20261104.html")),
          movie_url("cfc", SLUG): (200, read("synthetic_cfc_movie_avengers_without_23dec.html"))}
OPEN = {home_url("cfc"): (200, read("cfc_home_20261104.html")),
        movie_url("cfc", SLUG): (200, read("cfc_movie_avengers-sx-4dx_20261104.html")),
        fragment_url("cfc", SLUG, D23): (200, read("cfc_ajax_avengers-sx-4dx_23-12-2026_open.html"))}
BROKEN = {home_url("cfc"): (200, "<html><body><h1>New design</h1></body></html>")}


def setup(tmp_path):
    (tmp_path / "watches.yaml").write_text(CONFIG)
    tg = FakeTelegram()

    def go(pages, now=EARLY):
        return run(tg, DictFetcher(pages), config_path=str(tmp_path / "watches.yaml"),
                   state_path=str(tmp_path / "state.json"), now=now)
    return tg, go


def opens(tg):
    return [t for t, _ in tg.sent if "Booking is OPEN" in t]


def test_nothing_is_checked_until_you_send_watch(tmp_path):
    tg, go = setup(tmp_path)
    f = DictFetcher(OPEN)
    run(tg, f, config_path=str(tmp_path / "watches.yaml"), state_path=str(tmp_path / "state.json"), now=EARLY)
    assert f.requests_made == 0 and tg.sent == []


def test_watch_closed_closed_open_open_gives_one_alert(tmp_path):
    tg, go = setup(tmp_path)
    tg.say("/watch avengers 23 Dec", 1)
    for pages in [CLOSED, CLOSED, OPEN, OPEN]:
        assert go(pages) == 0
    reply = tg.sent[0][0]
    assert "Watching <b>avengers</b>" in reply and "not open yet (Avengers: Doomsday)" in reply
    assert len(opens(tg)) == 1 and len(tg.sent) == 2  # the reply + one alert, nothing repeated
    text, button = tg.sent[1]
    assert "Avengers: Doomsday" in text and "Wed 23 Dec 2026" in text and "12:00 PM" in text
    assert button == ("Book now", movie_url("cfc", SLUG))


def test_three_failed_runs_one_problem_then_recovery(tmp_path):
    tg, go = setup(tmp_path)
    tg.say("/watch avengers 23 Dec", 1)
    go(OPEN)
    for _ in range(4):
        go(BROKEN)
    go(OPEN)
    texts = [t for t, _ in tg.sent]
    assert sum("Problem" in t for t in texts) == 1 and sum("Recovered" in t for t in texts) == 1
    assert len(opens(tg)) == 1  # recovery doesn't repeat the open alert


def test_failed_alert_is_retried_next_run(tmp_path):
    tg, go = setup(tmp_path)
    tg.say("/watch avengers 23 Dec", 1)
    go(CLOSED)
    real_send = tg.send

    def failing(text, button=None):
        raise TelegramError("Telegram sendMessage failed: HTTP 502")
    tg.send = failing
    assert go(OPEN) == 1  # the run is marked failed
    tg.send = real_send
    go(OPEN)
    assert len(opens(tg)) == 1


def test_remove_stops_checking_and_past_dates_are_dropped(tmp_path):
    tg, go = setup(tmp_path)
    tg.say("/watch avengers 23 Dec", 1)
    go(CLOSED)
    tg.say("/remove 1", 2)
    f = DictFetcher(OPEN)
    run(tg, f, config_path=str(tmp_path / "watches.yaml"), state_path=str(tmp_path / "state.json"), now=EARLY)
    assert "Stopped" in tg.sent[-1][0] and f.requests_made == 0
    tg.say("/watch avengers 23 Dec", 3)
    go(CLOSED)
    after = datetime(2026, 12, 24, 3, 0, tzinfo=timezone.utc)
    f = DictFetcher(OPEN)
    run(tg, f, config_path=str(tmp_path / "watches.yaml"), state_path=str(tmp_path / "state.json"), now=after)
    assert f.requests_made == 0  # 23 Dec has passed, so the watch is gone


def test_heartbeat_once_a_day_after_nine(tmp_path):
    tg, go = setup(tmp_path)
    noon = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)  # 12:00 Cairo
    go({}, now=noon)
    go({}, now=noon)
    assert sum("Alive" in t for t, _ in tg.sent) == 1
