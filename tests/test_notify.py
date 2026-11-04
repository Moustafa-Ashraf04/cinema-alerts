import logging
from datetime import date

import pytest
import requests

from monitor.models import Cinema, Showtime
from monitor.notify import Telegram, TelegramError, fmt_open

TOKEN = "000:FAKE-TOKEN-FOR-TESTS-ONLY"


class Resp:
    def __init__(self, status, body):
        self.status_code, self._body = status, body

    def json(self):
        return self._body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, json=None, timeout=None):
        self.calls.append((url, json, timeout))
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def tg(responses):
    s = Session(responses)
    return Telegram(TOKEN, "42", session=s, sleep=lambda _: None), s


def test_send_uses_html_button_and_timeout():
    t, s = tg([Resp(200, {"ok": True})])
    t.send("hi", ("Book now", "https://x/y"))
    url, payload, timeout = s.calls[0]
    assert url.endswith("/sendMessage") and timeout == 10
    assert payload["parse_mode"] == "HTML" and payload["chat_id"] == "42"
    assert payload["reply_markup"]["inline_keyboard"][0][0] == {"text": "Book now", "url": "https://x/y"}


def test_retries_on_5xx_then_succeeds():
    t, s = tg([Resp(502, {}), Resp(500, {}), Resp(200, {"ok": True})])
    t.send("hi")
    assert len(s.calls) == 3


def test_gives_up_after_three_retries():
    t, s = tg([Resp(500, {})] * 4)
    with pytest.raises(TelegramError):
        t.send("hi")
    assert len(s.calls) == 4


def test_no_retry_on_4xx():
    t, s = tg([Resp(400, {"ok": False, "description": "Bad Request: chat not found"})])
    with pytest.raises(TelegramError, match="chat not found"):
        t.send("hi")
    assert len(s.calls) == 1


def test_token_never_in_errors_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    boom = requests.ConnectionError(f"Max retries exceeded with url: /bot{TOKEN}/sendMessage")
    t, _ = tg([boom] * 4)
    with pytest.raises(TelegramError) as exc:
        t.send("hi")
    assert TOKEN not in str(exc.value) and TOKEN not in caplog.text
    t, _ = tg([Resp(401, {"ok": False, "description": f"Unauthorized {TOKEN}"})])
    with pytest.raises(TelegramError) as exc:
        t.send("hi")
    assert TOKEN not in str(exc.value)


def test_dynamic_text_is_escaped():
    cinema = Cinema("c", "scene", "cfc", "Scene <CFC> & Co")
    st = [Showtime("12:00 PM", "4DX <3D>", 'https://x/showtime-1?a=1&b="2"')]
    text, button = fmt_open("<b>movie</b>", ["Tom & Jerry <2>"], cinema, date(2026, 12, 23), st, "https://x/m")
    assert "Tom &amp; Jerry &lt;2&gt;" in text and "Scene &lt;CFC&gt; &amp; Co" in text
    assert "4DX &lt;3D&gt;" in text and "&quot;2&quot;" in text and "<CFC>" not in text
    assert button == ("Book now", "https://x/m")
