import os

import pytest
from conftest import ROOT

from monitor.config import ConfigError, load_config

GOOD = """settings:
  timezone: Africa/Cairo
cinemas:
  - id: scene-cfc
    provider: scene
    branch: cfc
watches:
  - id: dune
    movie: Dune
    dates: ["2026-12-23"]
"""


def load(tmp_path, text):
    p = tmp_path / "watches.yaml"
    p.write_text(text)
    return load_config(str(p))


def test_repo_watches_yaml_is_valid():
    cfg = load_config(os.path.join(ROOT, "watches.yaml"))
    assert [c.id for c in cfg.enabled_cinemas] == ["scene-cfc", "scene-district5"]


def test_good(tmp_path):
    cfg = load(tmp_path, GOOD)
    assert cfg.watches[0].dates[0].isoformat() == "2026-12-23"


@pytest.mark.parametrize("bad, words", [
    (GOOD.replace('"2026-12-23"', '"2026-13-01"'), ["line 10", "bad date"]),
    (GOOD.replace('"2026-12-23"', '"23 Dec"'), ["line 10", "bad date"]),
    (GOOD.replace('"2026-12-23"', "2026-13-01"), ["YYYY-MM-DD"]),
    (GOOD + "  - id: dune\n    movie: Dune 2\n    dates: [\"2026-12-24\"]\n", ["line 11", "duplicate watch id 'dune'"]),
    (GOOD.replace("provider: scene", "provider: cinemark"), ["line 5", "unknown provider 'cinemark'"]),
    (GOOD.replace("provider: scene", "provider: vox"), ["parked"]),
    (GOOD.replace("branch: cfc", "branch: zayed"), ["unknown Scene branch"]),
    (GOOD.replace("    movie: Dune", "    moive: Dune"), ["line 9", "unknown key 'moive'"]),
    (GOOD.replace("timezone: Africa/Cairo", "timezone: Mars/Base"), ["unknown timezone"]),
])
def test_bad_configs_have_readable_errors(tmp_path, bad, words):
    with pytest.raises(ConfigError) as exc:
        load(tmp_path, bad)
    for w in words:
        assert w in str(exc.value)
