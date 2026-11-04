"""Match a typed movie name ("dune", "spider man") to a site's title."""

from __future__ import annotations

import re


def normalize(text: str) -> str:
    text = re.sub(r"\([^)]*\)", " ", text.lower())  # drop "(2D)" and similar
    return re.sub(r"[^a-z0-9؀-ۿ]+", " ", text).strip()


def title_matches(query: str, title: str, slug: str = "") -> bool:
    """Every word typed must start a word of the title (or the URL slug)."""
    q = normalize(query).split()
    if not q:
        return False
    for candidate in (title, slug.replace("-", " ").replace("_", " ")):
        words = normalize(candidate).split()
        if words and all(any(w.startswith(t) for w in words) for t in q):
            return True
    return False
