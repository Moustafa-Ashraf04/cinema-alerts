import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
SCENE = os.path.join(ROOT, "tests", "fixtures", "scene")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests use saved pages only. Any real connection attempt fails the test."""
    def guard(*args, **kwargs):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


def read(name: str) -> str:
    with open(os.path.join(SCENE, name), encoding="utf-8") as f:
        return f.read()


class FakeTelegram:
    """Collects messages instead of sending them; serves queued updates once."""

    def __init__(self, chat_id="111"):
        self.sent: list[tuple[str, tuple | None]] = []
        self.updates: list[dict] = []
        self.chat_id = chat_id

    def say(self, text, update_id):
        self.updates.append({"update_id": update_id, "message": {"chat": {"id": int(self.chat_id)}, "text": text}})

    def send(self, text, button=None):
        self.sent.append((text, button))

    def get_updates(self, offset):
        return [u for u in self.updates if u["update_id"] >= offset]


class DictFetcher:
    """Serves {url: (status, text[, final_url])}; unknown URLs fail like the network."""

    def __init__(self, pages: dict):
        self.pages = pages
        self.requests_made = 0
        self.urls: list[str] = []

    def get(self, url):
        from monitor.fetch import FetchResult
        self.requests_made += 1
        self.urls.append(url)
        if url not in self.pages:
            return FetchResult(url, 0, error="no saved page for this URL")
        status, text, *final = self.pages[url]
        return FetchResult(url, status, text, final[0] if final else url)
