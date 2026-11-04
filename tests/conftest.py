import os
import socket
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
FIX = os.path.join(ROOT, "tests", "fixtures")
SCENE = os.path.join(FIX, "scene")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Tests use saved pages only. Any real connection attempt fails the test."""
    def guard(*args, **kwargs):
        raise AssertionError("tests must not touch the network")
    monkeypatch.setattr(socket.socket, "connect", guard)
    monkeypatch.setattr(socket, "create_connection", guard)


def read(name: str, folder: str = SCENE) -> str:
    with open(os.path.join(folder, name), encoding="utf-8") as f:
        return f.read()


class FakeTelegram:
    """Collects messages instead of sending them."""

    def __init__(self, updates=None, chat_id="111"):
        self.sent: list[tuple[str, tuple | None]] = []
        self.updates = list(updates or [])
        self.chat_id = chat_id
        self.configured = True
        self.offsets = []

    def send(self, text, button=None):
        self.sent.append((text, button))

    def get_updates(self, offset):
        self.offsets.append(offset)
        out = [u for u in self.updates if u["update_id"] >= offset]
        return out


class DictFetcher:
    """Serves {url: (status, text)}; unknown URLs fail like the network."""

    def __init__(self, pages: dict):
        from monitor.providers.base import FetchResult
        self._FR = FetchResult
        self.pages = pages
        self.requests_made = 0
        self.urls = []

    def get(self, url):
        self.requests_made += 1
        self.urls.append(url)
        if url not in self.pages:
            return self._FR(url, 0, error="no saved page for this URL")
        status, text, *final = self.pages[url]
        return self._FR(url, status, text, final[0] if final else url)
