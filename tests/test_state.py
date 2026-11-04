import json

from monitor.models import CheckResult, Showtime, Status
from monitor.state import load_state, save_state, transition

A = Showtime("12:00 PM", "ScreenX", "https://x/showtime-a")
B = Showtime("04:00 PM", "ScreenX", "https://x/showtime-b")
C = Showtime("08:00 PM", "ScreenX", "https://x/showtime-c")

OPEN_AB = CheckResult(Status.OPEN, [A, B])
OPEN_ABC = CheckResult(Status.OPEN, [A, B, C])
CLOSED = CheckResult(Status.CLOSED)
ERROR = CheckResult(Status.ERROR, reason="HTTP 503")


def step(entry, result, notify_new=True):
    return transition(entry, result, notify_new=notify_new, error_after=3, now="t")


def kinds(events):
    return [e.kind for e in events]


def test_never_seen_to_open_alerts_on_first_run():
    e, ev = step(None, OPEN_AB)
    assert kinds(ev) == ["open"] and e["status"] == "OPEN" and e["first_open"] == "t"


def test_closed_to_open_alerts_once():
    e, ev = step(None, CLOSED)
    assert ev == []
    e, ev = step(e, OPEN_AB)
    assert kinds(ev) == ["open"]
    e, ev = step(e, OPEN_AB)
    assert ev == []


def test_new_showtimes_alert_with_only_the_new_ones():
    e, _ = step(None, OPEN_AB)
    e, ev = step(e, OPEN_ABC)
    assert kinds(ev) == ["new"] and ev[0].showtimes == [C]


def test_new_showtimes_off():
    e, _ = step(None, OPEN_AB)
    _, ev = step(e, OPEN_ABC, notify_new=False)
    assert ev == []


def test_error_does_not_change_status():
    e, _ = step(None, OPEN_AB)
    e2, ev = step(e, ERROR)
    assert ev == [] and e2["status"] == "OPEN" and e2["showtimes"] == e["showtimes"]
    e3, _ = step(None, ERROR)
    assert e3["status"] is None


def test_three_errors_one_problem_alert_then_one_recovery():
    e, _ = step(None, CLOSED)
    all_events = []
    for _ in range(5):
        e, ev = step(e, ERROR)
        all_events += kinds(ev)
    assert all_events == ["problem"]
    e, ev = step(e, CLOSED)
    assert kinds(ev) == ["recovered"]
    e, ev = step(e, CLOSED)
    assert ev == []


def test_reopen_after_close_alerts_again():
    e, _ = step(None, OPEN_AB)
    e, _ = step(e, CLOSED)
    _, ev = step(e, OPEN_AB)
    assert kinds(ev) == ["open"]


def test_partial_result_keeps_known_showtimes():
    e, _ = step(None, OPEN_AB)
    e, ev = step(e, CheckResult(Status.OPEN, [A], partial=True))
    assert ev == [] and len(e["showtimes"]) == 2
    _, ev = step(e, OPEN_AB)
    assert ev == []


def test_missing_state_file_is_a_first_run(tmp_path):
    state, problem = load_state(str(tmp_path / "state.json"))
    assert problem is None and state["entries"] == {}


def test_corrupt_state_is_moved_aside(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json")
    state, problem = load_state(str(p))
    assert problem and state["entries"] == {}
    assert (tmp_path / "state.corrupt.json").exists() and not p.exists()


def test_save_and_reload(tmp_path):
    p = str(tmp_path / "s" / "state.json")
    state, _ = load_state(p)
    state["entries"]["k"] = {"status": "OPEN"}
    save_state(p, state)
    assert json.load(open(p))["entries"]["k"]["status"] == "OPEN"
    assert load_state(p)[0]["entries"]["k"]["status"] == "OPEN"
