"""End to end: run the monitor on saved pages, as GitHub would, and count alerts."""

import os
import shutil
from datetime import datetime, timezone

from conftest import ROOT, SCENE, FakeTelegram, read

from monitor.main import parse_args, run
from monitor.providers.base import FixtureFetcher

NOW = datetime(2026, 11, 4, 10, 0, tzinfo=timezone.utc)


def go(folder, state, tg):
    args = parse_args(["--fixture", os.path.join(SCENE, folder), "--state", state])
    return run(args, tg, FixtureFetcher(os.path.join(SCENE, folder)), now=NOW)


def opens(tg):
    return [t for t, _ in tg.sent if "Booking is OPEN" in t]


def test_closed_closed_open_open_gives_exactly_one_alert(tmp_path):
    state, tg = str(tmp_path / "state.json"), FakeTelegram()
    for folder in ["replay_closed", "replay_closed", "replay_open", "replay_open"]:
        assert go(folder, state, tg) == 0
    assert len(tg.sent) == 1 and len(opens(tg)) == 1
    text, button = tg.sent[0]
    assert "Avengers: Doomsday" in text and "Wed 23 Dec 2026" in text and "12:00 PM" in text
    assert button == ("Book now", "https://cfc.scenecinemas.com/movie-details/avengers-doomsday-infinity-vision-sx-4dx.html")


def test_three_failed_runs_one_problem_then_recovery(tmp_path):
    broken = tmp_path / "broken"
    shutil.copytree(os.path.join(SCENE, "replay_open"), broken)
    # the site "changes": the homepage no longer has the structure we know
    (broken / "home.html").write_text("<html><body><h1>New design</h1></body></html>")
    manifest = (broken / "manifest.json").read_text().replace("../cfc_home_20261104.html", "home.html")
    (broken / "manifest.json").write_text(manifest.replace('"../', f'"{SCENE}/'))
    state, tg = str(tmp_path / "state.json"), FakeTelegram()

    args = parse_args(["--fixture", str(broken), "--state", state])
    for _ in range(4):
        run(args, tg, FixtureFetcher(str(broken)), now=NOW)
    assert [t for t, _ in tg.sent if "Problem" in t] and len(tg.sent) == 1

    assert go("replay_open", state, tg) == 0
    texts = [t for t, _ in tg.sent]
    assert sum("Recovered" in t for t in texts) == 1 and len(opens(tg)) == 1


def test_failed_alert_is_retried_next_run(tmp_path):
    state = str(tmp_path / "state.json")

    class Flaky(FakeTelegram):
        fail = True

        def send(self, text, button=None):
            from monitor.notify import TelegramError
            if self.fail:
                raise TelegramError("Telegram sendMessage failed: HTTP 502")
            super().send(text, button)

    tg = Flaky()
    assert go("replay_open", state, tg) == 1  # run marked failed
    tg.fail = False
    go("replay_open", state, tg)
    assert len(opens(tg)) == 1


def test_telegram_watch_command_gets_a_reply_with_the_first_result(tmp_path, monkeypatch):
    # non-fixture mode reads commands; serve the network from the replay folder
    folder = os.path.join(SCENE, "replay_open")
    monkeypatch.chdir(tmp_path)
    shutil.copy(os.path.join(folder, "watches.yaml"), tmp_path / "watches.yaml")
    tg = FakeTelegram(updates=[{"update_id": 1, "message": {"chat": {"id": 111}, "text": "/watch avengers 23 Dec"}}])
    args = parse_args(["--state", str(tmp_path / "state.json")])
    run(args, tg, FixtureFetcher(folder), now=NOW)
    texts = [t for t, _ in tg.sent]
    reply = next(t for t in texts if "Watching" in t)
    assert "OPEN" in reply and "Avengers: Doomsday" in reply
    assert len(opens(tg)) == 2  # the yaml watch and the new Telegram watch, same date
    assert any("Alive" in t for t in texts)  # 12:00 Cairo, after the 09:00 heartbeat hour
