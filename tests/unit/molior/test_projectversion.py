"""
Test the apt sources line of mirrors (ProjectVersion.get_apt_repo).
"""
from types import SimpleNamespace
from unittest.mock import patch

from molior.model.projectversion import ProjectVersion


def _mirror(dist, components, workaround, is_basemirror=False):
    project = SimpleNamespace(is_mirror=True, is_basemirror=is_basemirror, name="mcp")
    basemirror = SimpleNamespace(project=SimpleNamespace(name="bookworm"), name="12.8")
    return SimpleNamespace(project=project, name="20250105", basemirror=basemirror, external_repo=False,
                           mirror_distribution=dist, mirror_components=components,
                           mirror_slash_workaround=workaround)


def _line(mirror):
    def load(self, file_path):
        self._config = {"aptly": {"apt_url": "http://aptly:8000", "apt_url_public": ""}}

    with patch("molior.molior.configuration.Configuration._load_config", load):
        return ProjectVersion.get_apt_repo(mirror, internal=True)


URL = "deb http://aptly:8000/bookworm/12.8/mirrors/mcp/20250105 "


def test_mirror_plain_dist():
    assert _line(_mirror("bookworm", "main,contrib", False)) == URL + "bookworm main contrib"
    assert _line(_mirror("bookworm", "main,contrib", True)) == URL + "bookworm main contrib"


def test_mirror_slash_dist():
    assert _line(_mirror("bookworm/current", "non-free", True)) == URL + "bookworm_-current non-free"
    assert _line(_mirror("bookworm/current", "non-free", False)) == URL + "bookworm/current non-free"


def test_mirror_flat():
    assert _line(_mirror("./", "main", True)) == URL + "._- main"
    assert _line(_mirror("./", "", False)) == URL + ". main"
