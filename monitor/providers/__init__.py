"""Provider registry."""

from __future__ import annotations

from .base import Provider
from .scene import BRANCHES as SCENE_BRANCHES
from .scene import SceneProvider

KNOWN_PROVIDERS = {"scene", "premiere", "vox"}
IMPLEMENTED: dict[str, type[Provider]] = {"scene": SceneProvider}


def branch_problem(provider: str, branch) -> str | None:
    if not branch or not isinstance(branch, str):
        return "cinema is missing a branch"
    if provider == "scene" and branch not in SCENE_BRANCHES:
        return f"unknown Scene branch '{branch}' (known: {', '.join(SCENE_BRANCHES)})"
    return None


def make_providers(fetcher) -> dict[str, Provider]:
    return {name: cls(fetcher) for name, cls in IMPLEMENTED.items()}
