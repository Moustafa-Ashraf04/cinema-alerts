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
"""


def load(tmp_path, text):
    p = tmp_path / "watches.yaml"
    p.write_text(text)
    return load_config(str(p))


def test_repo_watches_yaml_is_valid():
    cfg = load_config(os.path.join(ROOT, "watches.yaml"))
    assert [c.id for c in cfg.enabled_cinemas] == ["scene-cfc", "scene-district5"]


def test_any_scene_branch_is_config_only(tmp_path):
    cfg = load(tmp_path, GOOD + "  - id: new\n    provider: scene\n    branch: new-branch\n")
    assert cfg.cinema("new").branch == "new-branch"


@pytest.mark.parametrize("bad, words", [
    (GOOD + "  - id: scene-cfc\n    provider: scene\n    branch: d5\n", ["line 7", "duplicate cinema id"]),
    (GOOD.replace("provider: scene", "provider: cinemark"), ["line 5", "unknown provider 'cinemark'"]),
    (GOOD.replace("branch: cfc", "branch: Cairo Festival"), ["line 6", "branch must be"]),
    (GOOD.replace("    branch: cfc", "    brnach: cfc"), ["line 6", "unknown key 'brnach'"]),
    (GOOD.replace("timezone: Africa/Cairo", "timezone: Mars/Base"), ["line 2", "unknown timezone"]),
    (GOOD + "watches: []\n", ["unknown key 'watches'"]),
    (GOOD.replace("cfc\n", "cfc\n    enabled: false\n"), ["no enabled cinemas"]),
])
def test_bad_configs_have_readable_errors(tmp_path, bad, words):
    with pytest.raises(ConfigError) as exc:
        load(tmp_path, bad)
    for w in words:
        assert w in str(exc.value)
