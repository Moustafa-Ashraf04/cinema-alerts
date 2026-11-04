import os
from datetime import date

import pytest
from conftest import ROOT

from monitor.commands import CommandError, handle, parse_date_spec, parse_watch, process_updates
from monitor.config import load_config
from monitor.state import empty_state

TODAY = date(2026, 11, 4)
CFG = load_config(os.path.join(ROOT, "watches.yaml"))


@pytest.mark.parametrize("spec, expected", [
    ("2026-12-23", [date(2026, 12, 23)]),
    ("23-12", [date(2026, 12, 23)]),
    ("23/12/2026", [date(2026, 12, 23)]),
    ("23 Dec", [date(2026, 12, 23)]),
    ("23 december", [date(2026, 12, 23)]),
    ("Dec 23", [date(2026, 12, 23)]),
    ("16-20 Dec", [date(2026, 12, d) for d in range(16, 21)]),
    ("3 Jan", [date(2027, 1, 3)]),  # no year: the next 3 Jan to come
    ("today", [TODAY]),
    ("tomorrow", [date(2026, 11, 5)]),
    ("31 Feb", None),
    ("dune", None),
    ("20-16 Dec", None),
])
def test_date_specs(spec, expected):
    assert parse_date_spec(spec, TODAY) == expected


def test_long_range_is_refused():
    with pytest.raises(CommandError):
        parse_date_spec("1-30 Dec", TODAY)


@pytest.mark.parametrize("args, movie, n_dates, cinemas", [
    ("dune 23 Dec", "dune", 1, []),
    ("avengers doomsday 16-20 Dec cfc", "avengers doomsday", 5, ["scene-cfc"]),
    ("spider man 2026-12-23 district5", "spider man", 1, ["scene-district5"]),
    ("dune cfc 23 Dec", "dune", 1, ["scene-cfc"]),
    ("dune 23 Dec scene", "dune", 1, ["scene-cfc", "scene-district5"]),
])
def test_parse_watch(args, movie, n_dates, cinemas):
    m, dates, cs = parse_watch(args, CFG, TODAY)
    assert (m, len(dates), cs) == (movie, n_dates, cinemas)


@pytest.mark.parametrize("args", ["dune", "23 Dec", "dune 2026-11-01"])
def test_parse_watch_errors(args):
    with pytest.raises(CommandError):
        parse_watch(args, CFG, TODAY)


def msg(uid, text, chat=111):
    return {"update_id": uid, "message": {"chat": {"id": chat}, "text": text}}


def test_only_owner_chat_is_obeyed_and_offset_advances():
    state = empty_state()
    replies = process_updates([msg(5, "/watch dune 23 Dec", chat=999), msg(6, "/watch dune 23 Dec")],
                              "111", state, CFG, TODAY)
    assert len(replies) == 1 and replies[0].watch_id == "w1"
    assert [w["movie"] for w in state["watches"]] == ["dune"]
    assert state["telegram_offset"] == 6


def test_watch_list_remove_and_duplicates():
    state = empty_state()
    handle("/watch verity 25 Dec", state, CFG, TODAY)
    assert "already" in handle("/watch Verity 25 Dec", state, CFG, TODAY).text
    assert "1. <b>verity</b>" in handle("/list", state, CFG, TODAY).text
    with pytest.raises(CommandError):
        handle("/remove 2", state, CFG, TODAY)
    assert "Stopped" in handle("/remove 1", state, CFG, TODAY).text
    assert state["watches"] == []
    assert "not watching anything" in handle("/list", state, CFG, TODAY).text


def test_help_cinemas_and_unknown():
    state = empty_state()
    assert "/watch" in handle("/help", state, CFG, TODAY).text
    assert "<code>cfc</code>" in handle("/cinemas", state, CFG, TODAY).text
    assert "/help" in handle("/frobnicate", state, CFG, TODAY).text
    assert "/help" in handle("hello", state, CFG, TODAY).text
